"""
Portfolio service for portfolio-level analytics and snapshots.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pymysql

from utils.krx_calendar import is_korea_trading_day_by_samsung

def create_portfolio_snapshot(
    conn: pymysql.connections.Connection,
    snapshot_date: Optional[date] = None,
) -> int:
    """
    Create a daily portfolio snapshot from open lots.

    Args:
        conn: Database connection
        snapshot_date: Date for the snapshot. If None, uses today.

    Returns:
        Number of snapshot records created
    """
    if snapshot_date is None:
        snapshot_date = date.today()

    # Get total portfolio value from account_summary (추정자산 = 청산 기준 총자산)
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            """
            SELECT prsm_dpst_aset_amt
            FROM account_summary
            WHERE snapshot_date = %s
            """,
            (snapshot_date,),
        )

        summary = cur.fetchone()

    if not summary or not summary["prsm_dpst_aset_amt"]:
        print(f"Warning: No account summary found for {snapshot_date}")
        return 0

    total_portfolio_value = Decimal(str(summary["prsm_dpst_aset_amt"]))

    # Get positions from holdings (actual current positions)
    # Aggregate by stock_code and crd_class (combining all loan_dt)
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            """
            SELECT
                h.stk_cd as stock_code,
                MAX(h.stk_nm) as stock_name,
                h.crd_class,
                SUM(h.rmnd_qty) as total_quantity,
                SUM(h.rmnd_qty * h.avg_prc) / SUM(h.rmnd_qty) as avg_cost_basis,
                MAX(h.cur_prc) as current_price,
                SUM(h.rmnd_qty * h.avg_prc) as total_cost,
                SUM(h.rmnd_qty * (h.cur_prc - h.avg_prc)) as unrealized_pnl
            FROM holdings h
            WHERE h.snapshot_date = %s
              AND h.rmnd_qty > 0
            GROUP BY h.stk_cd, h.crd_class
            ORDER BY h.stk_cd
            """,
            (snapshot_date,)
        )

        positions = cur.fetchall()

    # Delete existing snapshot for this date
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM portfolio_snapshot WHERE snapshot_date = %s",
            (snapshot_date,),
        )

    # Insert new snapshot records
    insert_sql = """
        INSERT INTO portfolio_snapshot (
            snapshot_date, stock_code, stock_name, crd_class,
            total_quantity, avg_cost_basis, current_price,
            market_value, total_cost,
            unrealized_pnl, unrealized_return_pct, portfolio_weight_pct,
            total_portfolio_value
        )
        VALUES (
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            %s
        )
    """

    count = 0

    with conn.cursor() as cur:
        for pos in positions:
            total_qty = pos["total_quantity"]
            avg_cost = Decimal(str(pos["avg_cost_basis"])) if pos["avg_cost_basis"] else Decimal(0)
            current_price = Decimal(str(pos["current_price"])) if pos["current_price"] else Decimal(0)
            total_cost = Decimal(str(pos["total_cost"])) if pos["total_cost"] else Decimal(0)
            unrealized_pnl = Decimal(str(pos["unrealized_pnl"])) if pos["unrealized_pnl"] is not None else Decimal(0)

            # Calculate market value and metrics
            market_value = current_price * Decimal(total_qty)
            unrealized_return_pct = (
                (unrealized_pnl / total_cost * 100) if total_cost > 0 else Decimal(0)
            )
            portfolio_weight_pct = (
                (market_value / total_portfolio_value * 100) if total_portfolio_value > 0 else Decimal(0)
            )

            cur.execute(
                insert_sql,
                (
                    snapshot_date,
                    pos["stock_code"],
                    pos["stock_name"],
                    pos["crd_class"],
                    total_qty,
                    float(avg_cost),
                    float(current_price),
                    float(market_value),
                    float(total_cost),
                    float(unrealized_pnl),
                    float(unrealized_return_pct),
                    float(portfolio_weight_pct),
                    float(total_portfolio_value),
                ),
            )
            count += 1

    conn.commit()
    return count


def get_portfolio_composition(
    conn: pymysql.connections.Connection,
    snapshot_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """
    Get current portfolio composition.

    Args:
        conn: Database connection
        snapshot_date: Date to query. If None, uses latest.

    Returns:
        List of position dictionaries
    """
    if snapshot_date is None:
        snapshot_date = date.today()

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            """
            SELECT
                stock_code,
                stock_name,
                crd_class,
                total_quantity,
                avg_cost_basis,
                current_price,
                market_value,
                total_cost,
                unrealized_pnl,
                unrealized_return_pct,
                portfolio_weight_pct,
                total_portfolio_value
            FROM portfolio_snapshot
            WHERE snapshot_date = %s
            ORDER BY portfolio_weight_pct DESC
            """,
            (snapshot_date,),
        )

        return cur.fetchall()


def get_position_summary(
    conn: pymysql.connections.Connection,
    stock_code: str,
) -> Dict[str, Any]:
    """
    Get detailed summary for a specific position across all lots.

    Args:
        conn: Database connection
        stock_code: Stock code to query

    Returns:
        Dictionary with position summary
    """
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        # Get all lots for this stock
        cur.execute(
            """
            SELECT
                COUNT(*) as num_lots,
                stock_name,
                crd_class,
                MIN(trade_date) as earliest_purchase,
                MAX(trade_date) as latest_purchase,
                SUM(net_quantity) as total_shares,
                SUM(total_cost) as total_cost,
                SUM(total_cost) / SUM(net_quantity) as avg_cost_basis,
                MAX(current_price) as current_price,
                SUM(unrealized_pnl) as total_unrealized_pnl
            FROM daily_lots
            WHERE stock_code = %s AND is_closed = FALSE
            GROUP BY stock_name, crd_class
            """,
            (stock_code,),
        )

        result = cur.fetchone()

        if not result:
            return {}

        total_cost = Decimal(str(result["total_cost"]))
        total_unrealized_pnl = Decimal(str(result["total_unrealized_pnl"]))

        return_pct = (
            (total_unrealized_pnl / total_cost * 100) if total_cost > 0 else Decimal(0)
        )

        result["total_return_pct"] = float(return_pct)

        return result


def backfill_portfolio_snapshots(
    conn: pymysql.connections.Connection,
    start_date: date,
    end_date: Optional[date] = None,
) -> int:
    """
    Backfill portfolio_snapshot table from daily_lots for historical dates.

    This reconstructs portfolio composition by finding which lots were open
    on each historical date.

    Args:
        conn: Database connection
        start_date: Start date for backfill
        end_date: End date for backfill (default: today)

    Returns:
        Total number of snapshot records created
    """
    if end_date is None:
        end_date = date.today()

    print(f"Backfilling portfolio snapshots from {start_date} to {end_date}")
    print("=" * 60)

    total_count = 0
    current_date = start_date

    while current_date <= end_date:
        if is_korea_trading_day_by_samsung(current_date):
            count = _create_portfolio_snapshot_from_lots(conn, current_date)
            if count > 0:
                print(f"[{current_date}] Created {count} position(s)")
                total_count += count
            else:
                print(f"[{current_date}] No positions")

        current_date += timedelta(days=1)

    print("=" * 60)
    print(f"Backfill complete: {total_count} total records")
    return total_count


def _create_portfolio_snapshot_from_lots(
    conn: pymysql.connections.Connection,
    snapshot_date: date,
) -> int:
    """
    Create portfolio snapshot from daily_lots for a specific historical date.

    A lot was open on date X if:
    - trade_date <= X (lot was created before or on that date)
    - AND (is_closed = FALSE OR closed_date > X) (lot wasn't closed yet at that time)
    """
    # Get total portfolio value from daily_portfolio_snapshot (추정자산 = 청산 기준 총자산)
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            """
            SELECT prsm_dpst_aset_amt
            FROM daily_portfolio_snapshot
            WHERE snapshot_date = %s
            """,
            (snapshot_date,),
        )
        snapshot = cur.fetchone()

    if not snapshot or not snapshot["prsm_dpst_aset_amt"]:
        return 0

    total_portfolio_value = Decimal(str(snapshot["prsm_dpst_aset_amt"]))

    # Get lots that were open on this date
    # A lot was open if: trade_date <= snapshot_date AND (is_closed=FALSE OR closed_date > snapshot_date)
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            """
            SELECT
                stock_code,
                MAX(stock_name) as stock_name,
                crd_class,
                SUM(net_quantity) as total_quantity,
                SUM(total_cost) / SUM(net_quantity) as avg_cost_basis,
                SUM(total_cost) as total_cost
            FROM daily_lots
            WHERE trade_date <= %s
              AND (is_closed = FALSE OR closed_date > %s)
              AND net_quantity > 0
            GROUP BY stock_code, crd_class
            HAVING total_quantity > 0
            ORDER BY stock_code
            """,
            (snapshot_date, snapshot_date),
        )
        positions = cur.fetchall()

    if not positions:
        return 0

    # Get last trade prices for each stock on or before snapshot_date
    prices = _get_historical_prices(conn, snapshot_date)

    # Delete existing snapshot for this date
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM portfolio_snapshot WHERE snapshot_date = %s",
            (snapshot_date,),
        )

    # Insert snapshot records
    insert_sql = """
        INSERT INTO portfolio_snapshot (
            snapshot_date, stock_code, stock_name, crd_class,
            total_quantity, avg_cost_basis, current_price,
            market_value, total_cost,
            unrealized_pnl, unrealized_return_pct, portfolio_weight_pct,
            total_portfolio_value
        )
        VALUES (
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            %s
        )
    """

    count = 0

    with conn.cursor() as cur:
        for pos in positions:
            stock_code = pos["stock_code"]
            crd_class = pos["crd_class"]
            total_qty = int(pos["total_quantity"])
            avg_cost = Decimal(str(pos["avg_cost_basis"])) if pos["avg_cost_basis"] else Decimal(0)
            total_cost = Decimal(str(pos["total_cost"])) if pos["total_cost"] else Decimal(0)

            # Get price (from trade history or use avg_cost as fallback)
            current_price = prices.get((stock_code, crd_class), float(avg_cost))
            current_price_dec = Decimal(str(current_price))

            # Calculate metrics
            market_value = current_price_dec * Decimal(total_qty)
            unrealized_pnl = market_value - total_cost
            unrealized_return_pct = (
                (unrealized_pnl / total_cost * 100) if total_cost > 0 else Decimal(0)
            )
            portfolio_weight_pct = (
                (market_value / total_portfolio_value * 100) if total_portfolio_value > 0 else Decimal(0)
            )

            cur.execute(
                insert_sql,
                (
                    snapshot_date,
                    stock_code,
                    pos["stock_name"],
                    crd_class,
                    total_qty,
                    float(avg_cost),
                    float(current_price_dec),
                    float(market_value),
                    float(total_cost),
                    float(unrealized_pnl),
                    float(unrealized_return_pct),
                    float(portfolio_weight_pct),
                    float(total_portfolio_value),
                ),
            )
            count += 1

    conn.commit()
    return count


def _get_historical_prices(
    conn: pymysql.connections.Connection,
    target_date: date,
) -> dict:
    """
    Get last trade prices for all stocks on or before target_date.

    Returns:
        Dict mapping (stock_code, crd_class) -> price
    """
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            """
            SELECT t1.stk_cd, t1.crd_class, t1.cntr_uv as price
            FROM account_trade_history t1
            INNER JOIN (
                SELECT stk_cd, crd_class, MAX(trade_date) as max_date
                FROM account_trade_history
                WHERE trade_date <= %s
                GROUP BY stk_cd, crd_class
            ) t2 ON t1.stk_cd = t2.stk_cd
                AND t1.crd_class = t2.crd_class
                AND t1.trade_date = t2.max_date
            """,
            (target_date,),
        )
        rows = cur.fetchall()

    return {(r["stk_cd"], r["crd_class"]): r["price"] for r in rows}
