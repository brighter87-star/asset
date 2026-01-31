"""
Lot service for daily net lot construction and management.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import pymysql


def _is_buy(io_tp_nm: Optional[str]) -> bool:
    """Check if trade is a buy."""
    if not io_tp_nm:
        return False
    return "매수" in io_tp_nm


def _is_sell(io_tp_nm: Optional[str]) -> bool:
    """Check if trade is a sell."""
    if not io_tp_nm:
        return False
    return "매도" in io_tp_nm and "매수" not in io_tp_nm


def construct_daily_lots(
    conn: pymysql.connections.Connection,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> None:
    """
    Construct daily lots from trade history.

    Args:
        conn: Database connection
        start_date: Start date (YYYY-MM-DD). If None, defaults to 2025-12-11.
        end_date: End date (YYYY-MM-DD). If None, processes up to today.
    """
    where_clauses = []
    params: Dict[str, Any] = {}

    # Default start date: 2025-12-13 (after initial position on 12/12)
    if start_date is None:
        start_date = "2025-12-13"

    if start_date:
        where_clauses.append("trade_date >= %(start_date)s")
        params["start_date"] = start_date

    if end_date:
        where_clauses.append("trade_date <= %(end_date)s")
        params["end_date"] = end_date

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        # Get all trades in the date range
        cur.execute(
            f"""
            SELECT
                stk_cd,
                stk_nm,
                io_tp_nm,
                crd_class,
                trade_date,
                cntr_qty,
                cntr_uv,
                loan_dt
            FROM account_trade_history
            {where_sql}
            ORDER BY trade_date ASC, stk_cd, crd_class, loan_dt
            """,
            params,
        )

        trades = cur.fetchall()

    # Group trades by (stock_code, crd_class, loan_dt, trade_date)
    grouped: Dict[Tuple[str, str, str, date], List[Dict]] = {}

    for trade in trades:
        key = (
            trade["stk_cd"],
            trade["crd_class"] or "CASH",
            trade["loan_dt"] or "",  # Empty string for CASH trades
            trade["trade_date"],
        )
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(trade)

    # Process each group
    for (stock_code, crd_class, loan_dt, trade_date), group in grouped.items():
        buys = [t for t in group if _is_buy(t["io_tp_nm"])]
        sells = [t for t in group if _is_sell(t["io_tp_nm"])]

        buy_qty = sum(t["cntr_qty"] or 0 for t in buys)
        sell_qty = sum(t["cntr_qty"] or 0 for t in sells)
        net_qty = buy_qty - sell_qty

        stock_name = group[0]["stk_nm"]

        if net_qty > 0:
            # Net buy day - create new lot
            total_buy_value = sum(
                (t["cntr_qty"] or 0) * (t["cntr_uv"] or 0) for t in buys
            )
            avg_price = Decimal(total_buy_value) / Decimal(buy_qty) if buy_qty > 0 else Decimal(0)
            total_cost = avg_price * Decimal(net_qty)

            _insert_daily_lot(
                conn,
                stock_code,
                stock_name,
                crd_class,
                loan_dt,
                trade_date,
                net_qty,
                avg_price,
                total_cost,
            )

        elif net_qty < 0:
            # Net sell day - reduce existing lots (LIFO)
            _reduce_lots_lifo(
                conn,
                stock_code,
                crd_class,
                loan_dt,
                abs(net_qty),
                trade_date,
            )

        # If net_qty == 0, no action needed (balanced day)

    conn.commit()


def _insert_daily_lot(
    conn: pymysql.connections.Connection,
    stock_code: str,
    stock_name: str,
    crd_class: str,
    loan_dt: str,
    trade_date: date,
    net_quantity: int,
    avg_purchase_price: Decimal,
    total_cost: Decimal,
) -> None:
    """Insert or update a daily lot."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO daily_lots (
                stock_code, stock_name, crd_class, loan_dt, trade_date,
                net_quantity, avg_purchase_price, total_cost
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                stock_name = VALUES(stock_name),
                net_quantity = VALUES(net_quantity),
                avg_purchase_price = VALUES(avg_purchase_price),
                total_cost = VALUES(total_cost),
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                stock_code,
                stock_name,
                crd_class,
                loan_dt or None,
                trade_date,
                net_quantity,
                float(avg_purchase_price),
                float(total_cost),
            ),
        )


def _reduce_lots_lifo(
    conn: pymysql.connections.Connection,
    stock_code: str,
    crd_class: str,
    loan_dt: str,
    sell_qty: int,
    sell_date: date,
) -> None:
    """
    Reduce existing lots using LIFO (Last In First Out).

    Args:
        conn: Database connection
        stock_code: Stock code
        crd_class: Credit class (CASH/CREDIT)
        loan_dt: Loan date (for CREDIT) or empty string (for CASH)
        sell_qty: Quantity to reduce
        sell_date: Date of the sell transaction
    """
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        # Get open lots ordered by trade_date DESC (LIFO)
        # IMPORTANT: Only close lots that:
        # 1. Were bought BEFORE the sell date
        # 2. Have the SAME loan_dt (for CREDIT trades)
        cur.execute(
            """
            SELECT lot_id, net_quantity
            FROM daily_lots
            WHERE stock_code = %s
              AND crd_class = %s
              AND (loan_dt = %s OR (loan_dt IS NULL AND %s = ''))
              AND is_closed = FALSE
              AND trade_date <= %s
            ORDER BY trade_date DESC
            """,
            (stock_code, crd_class, loan_dt or None, loan_dt or '', sell_date),
        )

        lots = cur.fetchall()

    remaining = sell_qty

    with conn.cursor() as cur:
        for lot in lots:
            if remaining <= 0:
                break

            lot_id = lot["lot_id"]
            lot_qty = lot["net_quantity"]

            if lot_qty <= remaining:
                # Fully close this lot
                cur.execute(
                    """
                    UPDATE daily_lots
                    SET is_closed = TRUE,
                        closed_date = %s,
                        net_quantity = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE lot_id = %s
                    """,
                    (sell_date, lot_id),
                )
                remaining -= lot_qty

            else:
                # Partially reduce this lot
                new_qty = lot_qty - remaining
                cur.execute(
                    """
                    UPDATE daily_lots
                    SET net_quantity = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE lot_id = %s
                    """,
                    (new_qty, lot_id),
                )
                remaining = 0


def update_lot_metrics(conn: pymysql.connections.Connection, today: Optional[date] = None) -> int:
    """
    Update metrics (holding days, current price, PnL) for all open lots.

    Args:
        conn: Database connection
        today: Current date. If None, uses date.today()

    Returns:
        Number of lots updated
    """
    if today is None:
        today = date.today()

    # Get current prices from holdings table
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            """
            SELECT stk_cd, crd_class, cur_prc
            FROM holdings
            WHERE snapshot_date = %s
            """,
            (today,),
        )

        price_data = cur.fetchall()

    # Build price lookup dictionary from holdings
    prices: Dict[Tuple[str, str], int] = {}
    for row in price_data:
        key = (row["stk_cd"], row["crd_class"])
        prices[key] = row["cur_prc"]

    # Get last trade prices as fallback for stocks not in holdings
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            """
            SELECT
                stk_cd,
                crd_class,
                cntr_uv as last_price
            FROM account_trade_history
            WHERE (stk_cd, crd_class, trade_date, ord_tm) IN (
                SELECT stk_cd, crd_class, MAX(trade_date), MAX(ord_tm)
                FROM account_trade_history
                GROUP BY stk_cd, crd_class
            )
            """
        )

        fallback_prices = cur.fetchall()

    # Add fallback prices for stocks not in holdings
    for row in fallback_prices:
        key = (row["stk_cd"], row["crd_class"])
        if key not in prices:
            prices[key] = row["last_price"]

    # Get all open lots
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            """
            SELECT lot_id, stock_code, crd_class, trade_date, avg_purchase_price, net_quantity
            FROM daily_lots
            WHERE is_closed = FALSE
            """
        )

        lots = cur.fetchall()

    updated_count = 0

    with conn.cursor() as cur:
        for lot in lots:
            lot_id = lot["lot_id"]
            stock_code = lot["stock_code"]
            crd_class = lot["crd_class"]
            trade_date = lot["trade_date"]
            avg_price = Decimal(str(lot["avg_purchase_price"]))
            net_qty = lot["net_quantity"]

            # Get current price (from holdings or last trade)
            current_price = prices.get((stock_code, crd_class))

            # Always update holding days
            holding_days = (today - trade_date).days

            # Calculate P&L metrics only if we have a current price
            if current_price is not None:
                current_price_dec = Decimal(str(current_price))
                unrealized_pnl = (current_price_dec - avg_price) * Decimal(net_qty)
                unrealized_return_pct = (
                    ((current_price_dec - avg_price) / avg_price * 100) if avg_price > 0 else Decimal(0)
                )
            else:
                # No price available - use None for price-dependent metrics
                current_price_dec = None
                unrealized_pnl = None
                unrealized_return_pct = None

            # Update lot
            cur.execute(
                """
                UPDATE daily_lots
                SET holding_days = %s,
                    current_price = %s,
                    unrealized_pnl = %s,
                    unrealized_return_pct = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE lot_id = %s
                """,
                (
                    holding_days,
                    float(current_price_dec) if current_price_dec is not None else None,
                    float(unrealized_pnl) if unrealized_pnl is not None else None,
                    float(unrealized_return_pct) if unrealized_return_pct is not None else None,
                    lot_id,
                ),
            )
            updated_count += 1

    conn.commit()
    return updated_count


def get_open_lots(
    conn: pymysql.connections.Connection,
    stock_code: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get all open (not closed) lots, optionally filtered by stock.

    Args:
        conn: Database connection
        stock_code: Optional stock code filter

    Returns:
        List of lot dictionaries
    """
    where_clause = "WHERE is_closed = FALSE"
    params = []

    if stock_code:
        where_clause += " AND stock_code = %s"
        params.append(stock_code)

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            f"""
            SELECT
                lot_id,
                stock_code,
                stock_name,
                crd_class,
                trade_date,
                net_quantity,
                avg_purchase_price,
                total_cost,
                holding_days,
                current_price,
                unrealized_pnl,
                unrealized_return_pct
            FROM daily_lots
            {where_clause}
            ORDER BY unrealized_return_pct DESC
            """,
            params,
        )

        return cur.fetchall()
