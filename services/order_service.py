"""
Order service for automated trading.
Handles position sizing, order execution, and position tracking.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from db.connection import get_connection
from services.kiwoom_service import KiwoomTradingClient, CreditLimitError
from services.trade_logger import trade_logger

# Position state file
POSITIONS_FILE = Path(__file__).resolve().parent.parent / ".positions.json"


class DefaultSettings:
    """Default trading settings."""
    UNIT: int = 1
    TICK_BUFFER: int = 3
    STOP_LOSS_PCT: float = 7.0
    UNIT_BASE_PERCENT: float = 5.0  # 1 unit = 5%
    MAX_LEVERAGE_PCT: float = 120.0  # 최대 레버리지 (순자산 대비 주식자산 %)

    def get_unit_percent(self) -> float:
        return self.UNIT * self.UNIT_BASE_PERCENT

    def get_half_unit_percent(self) -> float:
        return (self.UNIT / 2) * self.UNIT_BASE_PERCENT


class OrderService:
    """
    Manages order execution and position tracking.
    """

    def __init__(self, settings: Any = None):
        self.settings = settings or DefaultSettings()
        self.client = KiwoomTradingClient()
        self.positions: Dict[str, dict] = {}
        self._load_positions()

    def _load_positions(self):
        """Load positions from file."""
        try:
            if POSITIONS_FILE.exists():
                with open(POSITIONS_FILE, "r") as f:
                    self.positions = json.load(f)
        except Exception:
            self.positions = {}

    def _save_positions(self):
        """Save positions to file."""
        try:
            with open(POSITIONS_FILE, "w") as f:
                json.dump(self.positions, f, indent=2, default=str)
        except Exception as e:
            print(f"[ERROR] Failed to save positions: {e}")

    def sync_positions_from_db(self, stop_loss_pct: float = 7.0):
        """
        holdings 테이블에서 보유종목을 로드하여 positions에 동기화.
        오늘 매수분(loan_dt가 오늘인 신용, 또는 오늘 매수한 현금)을 별도 추적.

        Args:
            stop_loss_pct: 기본 손절률 (%)

        Returns:
            synced count
        """
        from datetime import date

        try:
            conn = get_connection()
            today = date.today()
            today_str = today.strftime("%Y%m%d")

            with conn.cursor() as cur:
                # 1. 전체 보유 종목 집계
                cur.execute("""
                    SELECT
                        REPLACE(stk_cd, 'A', '') as stock_code,
                        MAX(stk_nm) as stock_name,
                        crd_class,
                        SUM(rmnd_qty) as total_qty,
                        SUM(rmnd_qty * avg_prc) / SUM(rmnd_qty) as avg_price,
                        SUM(rmnd_qty * avg_prc) as total_cost,
                        MAX(cur_prc) as current_price
                    FROM holdings
                    WHERE snapshot_date = %s AND rmnd_qty > 0
                    GROUP BY stk_cd, crd_class
                """, (today,))
                all_holdings = cur.fetchall()

                # 2. 오늘 매수분 (loan_dt가 오늘인 신용매수)
                cur.execute("""
                    SELECT
                        REPLACE(stk_cd, 'A', '') as stock_code,
                        crd_class,
                        SUM(rmnd_qty) as today_qty,
                        SUM(rmnd_qty * avg_prc) / SUM(rmnd_qty) as today_avg_price
                    FROM holdings
                    WHERE snapshot_date = %s AND rmnd_qty > 0
                      AND loan_dt = %s
                    GROUP BY stk_cd, crd_class
                """, (today, today_str))
                today_credit_buys = {
                    (row[0].zfill(6) if row[0] else "", row[1]): {
                        "qty": int(row[2] or 0),
                        "price": int(row[3] or 0)
                    }
                    for row in cur.fetchall()
                }

            conn.close()

            # 기존 positions 초기화 (DB 기준으로 새로 로드)
            self.positions = {}

            synced = 0
            for row in all_holdings:
                stock_code, stock_name, crd_class, total_qty, avg_price, total_cost, current_price = row

                if not stock_code or not total_qty or total_qty <= 0:
                    continue

                avg_price = int(avg_price or 0)
                current_price = int(current_price or 0)
                total_qty = int(total_qty)
                total_cost = int(total_cost or 0)

                if avg_price <= 0:
                    print(f"[WARN] {stock_code}: avg_price=0, skipping")
                    continue

                stop_loss_price = int(avg_price * (1 - stop_loss_pct / 100))

                # 6자리 종목코드로 정규화
                if len(stock_code) < 6:
                    stock_code = stock_code.zfill(6)

                # 오늘 매수분 확인 (신용: loan_dt 기준)
                today_buy = today_credit_buys.get((stock_code, crd_class), {})
                today_qty = today_buy.get("qty", 0)
                today_entry_price = today_buy.get("price", 0)

                # 오늘 매수분 손절가
                today_stop_loss_price = int(today_entry_price * (1 - stop_loss_pct / 100)) if today_entry_price > 0 else 0

                self.positions[stock_code] = {
                    "symbol": stock_code,
                    "name": stock_name or "",
                    "quantity": total_qty,
                    "entry_price": avg_price,
                    "stop_loss_price": stop_loss_price,
                    "stop_loss_pct": stop_loss_pct,
                    "status": "open",
                    "crd_class": crd_class,
                    "total_cost": total_cost,
                    "current_price": current_price,
                    "source": "holdings",
                    # 오늘 매수분 별도 추적
                    "today_qty": today_qty,
                    "today_entry_price": today_entry_price,
                    "today_stop_loss_price": today_stop_loss_price,
                }
                synced += 1

                if today_qty > 0:
                    print(f"[SYNC] {stock_code}: total={total_qty}, today={today_qty}@{today_entry_price:,}")

            self._save_positions()
            print(f"[SYNC] Loaded {synced} positions from holdings DB")
            return synced

        except Exception as e:
            print(f"[ERROR] Failed to sync from DB: {e}")
            return self._sync_holdings_from_api_fallback(stop_loss_pct)

    def _sync_holdings_from_api_fallback(self, stop_loss_pct: float = 7.0):
        """API에서 보유종목 동기화 (DB 실패 시 fallback)."""
        try:
            holdings = self.client.get_holdings()
            holdings_list = holdings.get("stk_acnt_evlt_prst", [])

            synced = 0
            for item in holdings_list:
                stock_code = item.get("stk_cd", "")
                if not stock_code:
                    continue

                quantity = int(item.get("rmnd_qty", 0) or 0)
                if quantity <= 0:
                    continue

                avg_price = int(item.get("pchs_avg_prc", 0) or 0)
                current_price = int(item.get("cur_prc", 0) or 0)
                stock_name = item.get("stk_nm", "")

                if stock_code not in self.positions:
                    stop_loss_price = int(avg_price * (1 - stop_loss_pct / 100))
                    self.positions[stock_code] = {
                        "symbol": stock_code,
                        "name": stock_name,
                        "quantity": quantity,
                        "entry_price": avg_price,
                        "stop_loss_price": stop_loss_price,
                        "stop_loss_pct": stop_loss_pct,
                        "status": "open",
                        "source": "api_fallback",
                        "current_price": current_price,
                    }
                    synced += 1

            self._save_positions()
            print(f"[SYNC] API fallback: {synced} positions")
            return synced

        except Exception as e:
            print(f"[ERROR] API fallback failed: {e}")
            return 0

    def get_available_capital(self) -> int:
        """Get available KRW capital for trading."""
        try:
            power = self.client.get_buying_power()
            return power["available_amt"]
        except Exception as e:
            print(f"[ERROR] Failed to get buying power: {e}")
            return 0

    def calculate_half_unit_amount(self) -> int:
        """
        Calculate half-unit amount for each buy.
        Each buy uses (UNIT / 2) * 5% of total capital.
        """
        available = self.get_available_capital()

        # Estimate total capital (available + positions value)
        positions_value = sum(
            pos.get("quantity", 0) * pos.get("entry_price", 0)
            for pos in self.positions.values()
            if pos.get("status") == "open"
        )
        total_capital = available + positions_value

        half_unit_pct = self.settings.get_half_unit_percent() / 100
        return int(total_capital * half_unit_pct)

    def calculate_shares(self, price: int) -> int:
        """
        Calculate number of shares to buy for one buy (half unit).

        Args:
            price: Stock price

        Returns:
            Number of shares (rounded down)
        """
        half_unit_amount = self.calculate_half_unit_amount()
        shares = int(half_unit_amount / price)
        return max(shares, 0)

    def add_tick_buffer(self, price: int) -> int:
        """Add tick buffer to price."""
        tick_size = self.client.get_tick_size(price)
        buffer = tick_size * self.settings.TICK_BUFFER
        return price + buffer

    def check_leverage_limit(self, buy_amount: int) -> Dict[str, Any]:
        """
        레버리지 한도 체크.
        매수 후 주식자산이 순자산의 120%를 넘지 않는지 확인.

        Args:
            buy_amount: 매수 예정 금액

        Returns:
            dict: allowed (bool), 현재/예상 레버리지 정보
        """
        try:
            assets = self.client.get_net_assets()
            net_assets = assets["net_assets"]
            stock_assets = assets["stock_assets"]
            current_leverage = assets["leverage_pct"]

            # 매수 후 예상 주식자산
            projected_stock_assets = stock_assets + buy_amount
            projected_leverage = (projected_stock_assets / net_assets * 100) if net_assets > 0 else 999

            max_leverage = getattr(self.settings, 'MAX_LEVERAGE_PCT', 120.0)
            allowed = projected_leverage <= max_leverage

            return {
                "allowed": allowed,
                "net_assets": net_assets,
                "stock_assets": stock_assets,
                "current_leverage_pct": current_leverage,
                "projected_stock_assets": projected_stock_assets,
                "projected_leverage_pct": projected_leverage,
                "max_leverage_pct": max_leverage,
            }

        except Exception as e:
            print(f"[WARNING] Failed to check leverage: {e}")
            # 레버리지 체크 실패시 주문 거부 (안전 우선)
            return {
                "allowed": False,
                "error": str(e),
            }

    def execute_buy(
        self,
        symbol: str,
        target_price: int,
        is_initial: bool = True,
        stop_loss_pct: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Execute buy order (신용매수).

        Args:
            symbol: Stock code (6 digits)
            target_price: Target price (before tick buffer)
            is_initial: True for first buy (0.5 unit), False for pyramid (0.5 unit)
            stop_loss_pct: Custom stop loss %, or use default

        Returns:
            Order result or None if failed
        """
        # Calculate buy price with tick buffer
        buy_price = self.add_tick_buffer(target_price)

        # Calculate shares (half unit each time)
        shares = self.calculate_shares(buy_price)

        if shares <= 0:
            print(f"[{symbol}] Insufficient capital for buy order")
            return None

        # 레버리지 한도 체크
        buy_amount = buy_price * shares
        leverage_check = self.check_leverage_limit(buy_amount)

        if not leverage_check.get("allowed", False):
            print(f"[{symbol}] REJECTED: Leverage limit exceeded")
            trade_logger.log_leverage_rejection(
                symbol=symbol,
                quantity=shares,
                price=buy_price,
                net_assets=leverage_check.get("net_assets", 0),
                current_leverage=leverage_check.get("current_leverage_pct", 0),
                projected_leverage=leverage_check.get("projected_leverage_pct", 0),
                max_leverage=leverage_check.get("max_leverage_pct", 120.0),
            )
            return None

        reason = "initial_entry" if is_initial else "pyramid"
        trade_logger.log_order_attempt(symbol, "BUY", shares, buy_price, "CREDIT", reason)

        use_credit = True  # 기본: 신용매수
        result = None

        try:
            # 1차: 신용매수 시도
            result = self.client.buy_order(symbol, shares, buy_price, use_credit=True)

        except CreditLimitError as e:
            # 신용한도 초과 종목 → 현금매수로 재시도
            print(f"[{symbol}] Credit limit exceeded, retrying with CASH order...")
            trade_logger.log_credit_limit_fallback(
                symbol=symbol,
                quantity=shares,
                price=buy_price,
                error_msg=str(e),
            )

            # 레버리지 재확인 후 현금 주문
            leverage_check = self.check_leverage_limit(buy_amount)
            if not leverage_check.get("allowed", False):
                print(f"[{symbol}] REJECTED: Leverage limit exceeded even for cash order")
                trade_logger.log_leverage_rejection(
                    symbol=symbol,
                    quantity=shares,
                    price=buy_price,
                    net_assets=leverage_check.get("net_assets", 0),
                    current_leverage=leverage_check.get("current_leverage_pct", 0),
                    projected_leverage=leverage_check.get("projected_leverage_pct", 0),
                    max_leverage=leverage_check.get("max_leverage_pct", 120.0),
                )
                return None

            try:
                use_credit = False
                trade_logger.log_order_attempt(symbol, "BUY", shares, buy_price, "CASH", reason)
                result = self.client.buy_order(symbol, shares, buy_price, use_credit=False)
            except Exception as cash_error:
                trade_logger.log_order_result(
                    symbol, "BUY", shares, buy_price,
                    success=False, error=f"Cash order failed: {cash_error}"
                )
                return None

        except Exception as e:
            trade_logger.log_order_result(
                symbol, "BUY", shares, buy_price,
                success=False, error=str(e)
            )
            return None

        if result:
            order_type_str = "CREDIT" if use_credit else "CASH"
            trade_logger.log_order_result(
                symbol, "BUY", shares, buy_price,
                success=True,
                order_no=result.get("order_no", ""),
                order_time=result.get("order_time", ""),
                message=f"{order_type_str} - {result.get('message', '')}",
                reason=reason,
            )

            # Update position tracking
            if symbol not in self.positions:
                self.positions[symbol] = {
                    "symbol": symbol,
                    "status": "open",
                    "entry_price": buy_price,
                    "quantity": shares,
                    "stop_loss_pct": stop_loss_pct or self.settings.STOP_LOSS_PCT,
                    "entry_time": datetime.now().isoformat(),
                    "buy_count": 1,
                    "order_type": order_type_str,
                }
                trade_logger.log_position_update(symbol, "OPEN", shares, buy_price, shares)
            else:
                # Averaging in
                pos = self.positions[symbol]
                old_qty = pos.get("quantity", 0)
                old_price = pos.get("entry_price", buy_price)
                new_qty = old_qty + shares
                new_avg_price = int((old_price * old_qty + buy_price * shares) / new_qty)

                pos["quantity"] = new_qty
                pos["entry_price"] = new_avg_price
                pos["buy_count"] = pos.get("buy_count", 1) + 1
                pos["last_buy_time"] = datetime.now().isoformat()

                trade_logger.log_position_update(symbol, "ADD", shares, buy_price, new_qty)

            self._save_positions()

        return result

    def execute_sell(self, symbol: str, price: int, reason: str = "", sell_qty: int = 0) -> Optional[dict]:
        """
        Execute sell order for position (full or partial).
        Uses kt10001 for CASH positions, kt10007 for CREDIT positions.

        Args:
            symbol: Stock code
            price: Sell price
            reason: Reason for selling (for logging)
            sell_qty: Quantity to sell (0 = sell all)

        Returns:
            Order result or None if failed
        """
        if symbol not in self.positions:
            print(f"[{symbol}] No position to sell")
            return None

        pos = self.positions[symbol]
        total_qty = pos.get("quantity", 0)
        crd_class = pos.get("crd_class", "CASH")

        if total_qty <= 0:
            print(f"[{symbol}] No shares to sell")
            return None

        # 매도 수량 결정 (0이면 전량 매도)
        quantity = sell_qty if sell_qty > 0 else total_qty
        quantity = min(quantity, total_qty)  # 보유 수량 초과 방지

        is_partial = quantity < total_qty
        sell_type = "PARTIAL" if is_partial else "FULL"

        # 신용/현금 구분
        order_type = "CREDIT" if crd_class == "CREDIT" else "CASH"
        trade_logger.log_order_attempt(symbol, "SELL", quantity, price, order_type, f"{reason} ({sell_type})")

        try:
            if crd_class == "CREDIT":
                print(f"[{symbol}] 신용매도 주문 ({sell_type}, {quantity}주)")
                result = self.client.sell_credit_order(symbol, quantity, price)
            else:
                print(f"[{symbol}] 현금매도 주문 ({sell_type}, {quantity}주)")
                result = self.client.sell_order(symbol, quantity, price)

            # Calculate P&L
            entry_price = pos.get("entry_price", price)
            pnl = (price - entry_price) * quantity
            pnl_pct = ((price / entry_price) - 1) * 100

            trade_logger.log_order_result(
                symbol, "SELL", quantity, price,
                success=True,
                order_no=result.get("order_no", ""),
                order_time=result.get("order_time", ""),
                message=f"{sell_type}: {result.get('message', '')}",
                reason=reason,
                pnl=pnl,
            )

            if is_partial:
                # 부분 매도: 수량 차감, today_qty 리셋
                pos["quantity"] = total_qty - quantity
                pos["today_qty"] = 0
                pos["today_entry_price"] = 0
                pos["today_stop_loss_price"] = 0
                trade_logger.log_position_update(symbol, "PARTIAL_SELL", quantity, price, pos["quantity"], pnl)
            else:
                # 전량 매도: 포지션 종료
                pos["status"] = "closed"
                pos["exit_price"] = price
                pos["exit_time"] = datetime.now().isoformat()
                pos["exit_reason"] = reason
                pos["realized_pnl"] = pnl
                pos["realized_pnl_pct"] = pnl_pct
                trade_logger.log_position_update(symbol, "CLOSE", quantity, price, 0, pnl)

            self._save_positions()
            return result

        except Exception as e:
            trade_logger.log_order_result(
                symbol, "SELL", quantity, price,
                success=False, error=str(e)
            )
            return None

    def check_stop_loss(self, symbol: str, current_price: int) -> dict:
        """
        Check if stop loss is triggered.

        Returns:
            dict with:
                - triggered: True if any stop loss triggered
                - type: "today" (today's qty only) or "all" (entire position)
                - qty: quantity to sell
        """
        result = {"triggered": False, "type": None, "qty": 0}

        if symbol not in self.positions:
            return result

        pos = self.positions[symbol]
        if pos.get("status") != "open":
            return result

        entry_price = pos.get("entry_price", 0)
        stop_loss_pct = pos.get("stop_loss_pct", self.settings.STOP_LOSS_PCT)
        total_qty = pos.get("quantity", 0)

        # 오늘 매수분 정보
        today_qty = pos.get("today_qty", 0)
        today_entry_price = pos.get("today_entry_price", 0)

        if entry_price <= 0:
            return result

        # 1. 오늘 매수분 손절 체크 (오늘 매수분이 있고, 오늘 매수가 기준 -7%)
        if today_qty > 0 and today_entry_price > 0:
            today_change_pct = ((current_price / today_entry_price) - 1) * 100
            if today_change_pct <= -stop_loss_pct:
                trade_logger.log_stop_loss(
                    symbol, today_entry_price, current_price,
                    stop_loss_pct, today_change_pct
                )
                print(f"[STOP] {symbol}: Today's buy stop loss triggered ({today_change_pct:+.2f}%)")
                return {
                    "triggered": True,
                    "type": "today",
                    "qty": today_qty,
                    "entry_price": today_entry_price,
                    "change_pct": today_change_pct,
                }

        # 2. 전체 포지션 손절 체크 (전체 평균가 기준 -7%)
        total_change_pct = ((current_price / entry_price) - 1) * 100
        if total_change_pct <= -stop_loss_pct:
            trade_logger.log_stop_loss(symbol, entry_price, current_price, stop_loss_pct, total_change_pct)
            print(f"[STOP] {symbol}: Total position stop loss triggered ({total_change_pct:+.2f}%)")
            return {
                "triggered": True,
                "type": "all",
                "qty": total_qty,
                "entry_price": entry_price,
                "change_pct": total_change_pct,
            }

        return result

    def check_stop_loss_simple(self, symbol: str, current_price: int) -> bool:
        """Simple stop loss check (backward compatible). Returns True if triggered."""
        result = self.check_stop_loss(symbol, current_price)
        return result.get("triggered", False)

    def get_position(self, symbol: str) -> Optional[dict]:
        """Get position for symbol."""
        return self.positions.get(symbol)

    def get_open_positions(self) -> List[dict]:
        """Get all open positions."""
        return [
            pos for pos in self.positions.values()
            if pos.get("status") == "open"
        ]

    def has_position(self, symbol: str) -> bool:
        """Check if we have an open position."""
        pos = self.positions.get(symbol)
        return pos is not None and pos.get("status") == "open"

    def clear_closed_positions(self):
        """Remove closed positions from tracking."""
        self.positions = {
            symbol: pos
            for symbol, pos in self.positions.items()
            if pos.get("status") == "open"
        }
        self._save_positions()
