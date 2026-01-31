"""
Portfolio service for portfolio-level analytics and snapshots.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pymysql


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

    # Get total portfolio value from account_summary
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            """
            SELECT aset_evlt_amt
            FROM account_summary
            WHERE snapshot_date = %s
            """,
            (snapshot_date,),
        )

        summary = cur.fetchone()

    if not summary or not summary["aset_evlt_amt"]:
        print(f"Warning: No account summary found for {snapshot_date}")
        return 0

    total_portfolio_value = Decimal(str(summary["aset_evlt_amt"]))

    # Aggregate lots by stock and crd_class
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            """
            SELECT
                stock_code,
                stock_name,
                crd_class,
                SUM(net_quantity) as total_quantity,
                SUM(total_cost) / SUM(net_quantity) as avg_cost_basis,
                MAX(current_price) as current_price,
                SUM(total_cost) as total_cost,
                SUM(unrealized_pnl) as unrealized_pnl
            FROM daily_lots
            WHERE is_closed = FALSE
            GROUP BY stock_code, stock_name, crd_class
            HAVING total_quantity > 0
            """
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
                unrealized_pnl,
                unrealized_return_pct,
                portfolio_weight_pct
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
