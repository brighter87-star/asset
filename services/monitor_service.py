"""
Monitor service for price monitoring and trading strategy execution.
"""

import json
import os
import pandas as pd
from datetime import datetime, time, date
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from db.connection import get_connection
from services.kiwoom_service import KiwoomTradingClient, get_stock_code, get_stock_name
from services.lot_service import get_latest_lot
from services.order_service import OrderService
from services.trade_logger import trade_logger

# Watchlist file paths (CSV takes priority over xlsx)
WATCHLIST_DIR = Path(__file__).resolve().parent.parent
WATCHLIST_CSV = WATCHLIST_DIR / "watchlist.csv"
WATCHLIST_XLSX = WATCHLIST_DIR / "watchlist.xlsx"
SETTINGS_CSV = WATCHLIST_DIR / "settings.csv"
PURCHASED_STOCKS_FILE = WATCHLIST_DIR / "purchased_stocks.json"
DAILY_TRIGGERS_FILE = WATCHLIST_DIR / "daily_triggers.json"
SOLD_TODAY_FILE = WATCHLIST_DIR / "sold_today.json"

# Korea timezone
KST = ZoneInfo("Asia/Seoul")


class TradingSettings:
    """Trading settings loaded from Excel."""

    # 1 unit = always 5% of assets (fixed)
    UNIT_BASE_PERCENT: float = 5.0

    def __init__(self):
        self.UNIT: int = 1              # Total units (1, 2, 3...)
        self.TICK_BUFFER: int = 3       # Target price + N ticks
        self.STOP_LOSS_PCT: float = 7.0 # Stop loss %
        self.MAX_LEVERAGE_PCT: float = 120.0  # Max leverage (stock / net assets %)
        self.VOLUME_MA_DAYS: int = 10   # Volume moving average period
        self.VOLUME_MULTIPLIER: float = 1.5  # Volume threshold multiplier

    def update(self, key: str, value):
        """Update setting value."""
        if hasattr(self, key):
            expected_type = type(getattr(self, key))
            setattr(self, key, expected_type(value))

    def get_unit_percent(self) -> float:
        """Get total percentage for position (UNIT * 5%)."""
        return self.UNIT * self.UNIT_BASE_PERCENT

    def get_half_unit_percent(self) -> float:
        """Get half unit percentage for each buy (UNIT/2 * 5%)."""
        return (self.UNIT / 2) * self.UNIT_BASE_PERCENT


class MonitorService:
    """
    Monitors prices and executes trading strategy.
    """

    def __init__(self):
        self.trading_settings = TradingSettings()
        self.client = KiwoomTradingClient()
        self.order_service = OrderService(settings=self.trading_settings)
        self.watchlist: List[dict] = []
        self.daily_triggers: Dict[str, dict] = {}  # Track triggered entries today
        self._file_mtime: float = 0  # File modification time
        self._pre_market_reloaded: bool = False  # Track pre-market reload
        self.purchased_stocks: Dict[str, dict] = {}  # Track purchased stocks
        self._unit_value_cache: int = 0  # Cached unit value
        self._unit_value_time: float = 0  # Cache timestamp
        self.sold_today: Dict[str, dict] = {}  # Track sold stocks to prevent re-buy
        self.close_actions_done: set = set()  # Track symbols processed by close logic (reset daily)
        self.pending_vi_orders: Dict[str, dict] = {}  # VI 대기 주문 {symbol: {order_no, time, ...}}
        self._load_purchased_stocks()
        self._load_daily_triggers()
        self._load_sold_today()

    def _load_purchased_stocks(self):
        """Load purchased stocks from JSON file."""
        try:
            if PURCHASED_STOCKS_FILE.exists():
                with open(PURCHASED_STOCKS_FILE, 'r', encoding='utf-8') as f:
                    self.purchased_stocks = json.load(f)
                print(f"[INFO] Loaded {len(self.purchased_stocks)} purchased stocks from file")
        except Exception as e:
            print(f"[WARNING] Failed to load purchased stocks: {e}")
            self.purchased_stocks = {}

    def _save_purchased_stocks(self):
        """Save purchased stocks to JSON file."""
        try:
            with open(PURCHASED_STOCKS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.purchased_stocks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[WARNING] Failed to save purchased stocks: {e}")

    def _load_sold_today(self):
        """Load sold_today from JSON file (persists across restarts within same day)."""
        try:
            if SOLD_TODAY_FILE.exists():
                with open(SOLD_TODAY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    saved_date = data.get("date")
                    today = datetime.now(KST).strftime("%Y-%m-%d")
                    if saved_date == today:
                        self.sold_today = data.get("sold", {})
                        if self.sold_today:
                            print(f"[INFO] Loaded {len(self.sold_today)} sold stocks from file")
                    else:
                        self.sold_today = {}
        except Exception as e:
            print(f"[WARNING] Failed to load sold_today: {e}")
            self.sold_today = {}

    def _save_sold_today(self):
        """Save sold_today to JSON file."""
        try:
            today = datetime.now(KST).strftime("%Y-%m-%d")
            data = {"date": today, "sold": self.sold_today}
            with open(SOLD_TODAY_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[WARNING] Failed to save sold_today: {e}")

    def _load_daily_triggers(self):
        """Load daily triggers from JSON file (persists across restarts)."""
        try:
            if DAILY_TRIGGERS_FILE.exists():
                with open(DAILY_TRIGGERS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Check if the saved date matches today
                    saved_date = data.get("date")
                    today = datetime.now(KST).strftime("%Y-%m-%d")
                    if saved_date == today:
                        self.daily_triggers = data.get("triggers", {})
                        print(f"[INFO] Loaded {len(self.daily_triggers)} daily triggers from file")
                    else:
                        # Different day, reset triggers
                        self.daily_triggers = {}
                        print(f"[INFO] Daily triggers file is from {saved_date}, starting fresh for {today}")
        except Exception as e:
            print(f"[WARNING] Failed to load daily triggers: {e}")
            self.daily_triggers = {}

    def _save_daily_triggers(self):
        """Save daily triggers to JSON file (persists across restarts)."""
        try:
            today = datetime.now(KST).strftime("%Y-%m-%d")
            data = {
                "date": today,
                "triggers": self.daily_triggers
            }
            with open(DAILY_TRIGGERS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[WARNING] Failed to save daily triggers: {e}")

    def mark_as_purchased(self, symbol: str, name: str = "", price: int = 0):
        """
        Mark a stock as purchased to prevent duplicate buys.
        User must manually remove from watchlist.csv to enable re-buying.
        """
        self.purchased_stocks[symbol] = {
            "name": name or get_stock_name(symbol),
            "purchased_at": datetime.now(KST).isoformat(),
            "price": price,
        }
        self._save_purchased_stocks()
        print(f"[INFO] Marked {symbol} as purchased (remove from watchlist.csv to re-enable)")

    def is_already_purchased(self, symbol: str) -> bool:
        """Check if stock was already purchased."""
        return symbol in self.purchased_stocks

    def sync_and_detect_sold(self, stop_loss_pct: float = None) -> List[str]:
        """
        Sync positions from DB and detect any sold stocks.

        Compares positions before and after sync.
        Any position that was held before but is gone after sync
        is marked as sold_today to prevent re-buying.

        Returns:
            List of newly detected sold symbols
        """
        if stop_loss_pct is None:
            stop_loss_pct = self.trading_settings.STOP_LOSS_PCT

        # Get current positions before sync
        positions_before = set(self.order_service.positions.keys())

        # Sync from DB
        self.order_service.sync_positions_from_db(stop_loss_pct=stop_loss_pct)

        # Get positions after sync
        positions_after = set(self.order_service.positions.keys())

        # Detect sold stocks (was held before, not held after)
        newly_sold = positions_before - positions_after

        for symbol in newly_sold:
            if symbol not in self.sold_today:
                self.sold_today[symbol] = {
                    "sold_at": datetime.now(KST).isoformat(),
                    "reason": "detected_sold"
                }
                print(f"[SOLD] {symbol} detected as sold - will not re-buy today")

        if newly_sold:
            self._save_sold_today()

        return list(newly_sold)

    def is_sold_today(self, symbol: str) -> bool:
        """Check if stock was sold today (should not re-buy)."""
        return symbol in self.sold_today

    def mark_as_sold_today(self, symbol: str, reason: str = "manual"):
        """Mark a stock as sold today."""
        self.sold_today[symbol] = {
            "sold_at": datetime.now(KST).isoformat(),
            "reason": reason
        }
        self._save_sold_today()
        print(f"[SOLD] {symbol} marked as sold today - will not re-buy")

    def was_sold_after_added(self, symbol: str, added_date: str) -> bool:
        """
        Check if a stock was sold after it was added to watchlist.

        Args:
            symbol: Stock code
            added_date: Date string when added to watchlist (YYYY-MM-DD or similar)

        Returns:
            True if there's a sell record after added_date (EXPIRED status)
        """
        if not added_date:
            return False

        try:
            # Parse added_date (handle various formats)
            from datetime import datetime as dt
            added_date_str = str(added_date).split()[0]  # Take date part only

            # Try parsing different formats
            for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"]:
                try:
                    added_dt = dt.strptime(added_date_str, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                return False  # Can't parse date

            today = date.today()

            # 1. Check sold_today (real-time tracking, no DB sync needed)
            # If added_date == today and symbol in sold_today → still expired
            # (user would need to update target_price to reset)
            if symbol in self.sold_today:
                # sold_today has today's sells - always counts as expired
                # unless user updates target_price (which sets added_date = today AFTER sell)
                if added_dt < today:
                    return True  # added before today, sold today → expired
                # If added_dt == today, we need to check if sold_today was before the update
                # Since we can't know exact update time, assume user updated AFTER seeing the loss
                # So if added_date == today, user has acknowledged and reset it → not expired
                # But if there's a sell in sold_today and we're checking, it means the sale
                # happened during this session. If added_date was already today (pre-set),
                # then user set it today morning BEFORE the trade → still expired
                # To be safe, if sold_today has this symbol, mark as expired unless
                # we explicitly know user updated after the sell.
                # Since sold_today tracks real-time, if it's there, it's today's sell.
                return True

            # 2. Check DB for sells on or after added_date
            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT COUNT(*) FROM account_trade_history
                        WHERE REPLACE(stk_cd, 'A', '') = %s
                          AND trade_date >= %s
                          AND (io_tp_nm LIKE '%%매도%%' OR io_tp_nm LIKE '%%상환%%')
                    """, (symbol, added_dt))
                    count = cur.fetchone()[0]
                return count > 0
            finally:
                conn.close()

        except Exception as e:
            print(f"[WARNING] Failed to check sell history for {symbol}: {e}")
            return False

    def clear_purchased_stock(self, symbol: str):
        """Remove stock from purchased list (called when removed from watchlist)."""
        if symbol in self.purchased_stocks:
            del self.purchased_stocks[symbol]
            self._save_purchased_stocks()
            print(f"[INFO] Cleared {symbol} from purchased stocks")

    def _get_watchlist_file(self) -> Optional[Path]:
        """Get watchlist file path (CSV priority)."""
        if WATCHLIST_CSV.exists():
            return WATCHLIST_CSV
        if WATCHLIST_XLSX.exists():
            return WATCHLIST_XLSX
        return None

    def _get_file_mtime(self) -> float:
        """Get file modification time."""
        try:
            watchlist_file = self._get_watchlist_file()
            if watchlist_file:
                mtime = os.path.getmtime(watchlist_file)
                # Also check settings.csv
                if SETTINGS_CSV.exists():
                    mtime = max(mtime, os.path.getmtime(SETTINGS_CSV))
                return mtime
            return 0
        except Exception:
            return 0

    def _check_file_changed(self) -> bool:
        """Check if file has been modified since last load."""
        current_mtime = self._get_file_mtime()
        if current_mtime > self._file_mtime:
            return True
        return False

    def load_settings(self) -> bool:
        """
        Load settings from CSV or Excel 'settings' sheet.

        Expected columns:
        - key: Setting name (UNIT, TICK_BUFFER, STOP_LOSS_PCT)
        - value: Setting value
        """
        try:
            df = None

            # CSV takes priority
            if SETTINGS_CSV.exists():
                df = pd.read_csv(SETTINGS_CSV)
                print(f"[SETTINGS] Loading from {SETTINGS_CSV.name}")
            elif WATCHLIST_XLSX.exists():
                try:
                    df = pd.read_excel(WATCHLIST_XLSX, sheet_name="settings")
                except Exception:
                    pass  # settings sheet may not exist

            if df is None or df.empty:
                return False

            df.columns = df.columns.str.lower().str.strip()

            for _, row in df.iterrows():
                key = str(row.get("key", "")).strip().upper()
                value = row.get("value")

                if key and not pd.isna(value):
                    self.trading_settings.update(key, value)

            print(f"[SETTINGS] UNIT={self.trading_settings.UNIT} "
                  f"({self.trading_settings.get_unit_percent()}%), "
                  f"TICK={self.trading_settings.TICK_BUFFER}, "
                  f"SL={self.trading_settings.STOP_LOSS_PCT}%, "
                  f"LEV={self.trading_settings.MAX_LEVERAGE_PCT}%, "
                  f"VOL_MA={self.trading_settings.VOLUME_MA_DAYS}d, "
                  f"VOL_MULT={self.trading_settings.VOLUME_MULTIPLIER}x")

            trade_logger.log_settings_change({
                "UNIT": self.trading_settings.UNIT,
                "TICK_BUFFER": self.trading_settings.TICK_BUFFER,
                "STOP_LOSS_PCT": self.trading_settings.STOP_LOSS_PCT,
                "MAX_LEVERAGE_PCT": self.trading_settings.MAX_LEVERAGE_PCT,
                "VOLUME_MA_DAYS": self.trading_settings.VOLUME_MA_DAYS,
                "VOLUME_MULTIPLIER": self.trading_settings.VOLUME_MULTIPLIER,
            })
            return True

        except Exception as e:
            print(f"[WARNING] Failed to load settings: {e}")
            return False

    def load_watchlist(self) -> List[dict]:
        """
        Load watchlist from CSV or Excel 'watchlist' sheet.
        CSV takes priority over xlsx.

        Expected columns (ticker 또는 name 중 하나는 필수):
        - ticker: (Optional) Stock code (e.g., 005930)
        - name: (Optional) Stock name (종목명) - ticker 대신 사용 가능
        - target_price: Target price for breakout
        - stop_loss_pct: (Optional) Custom stop loss %
        """
        watchlist_file = self._get_watchlist_file()
        if not watchlist_file:
            print(f"[WARNING] Watchlist not found (watchlist.csv or watchlist.xlsx)")
            return []

        try:
            # Load settings first
            self.load_settings()

            # Load watchlist (CSV or xlsx)
            if watchlist_file.suffix == '.csv':
                df = pd.read_csv(watchlist_file)
                print(f"[INFO] Loading watchlist from {watchlist_file.name}")
            else:
                df = pd.read_excel(watchlist_file, sheet_name="watchlist")

            # Normalize column names
            df.columns = df.columns.str.lower().str.strip()

            watchlist = []
            for _, row in df.iterrows():
                # ticker와 name 둘 다 확인
                ticker = ""
                name = ""

                if "ticker" in row and not pd.isna(row["ticker"]):
                    ticker = str(row["ticker"]).strip()
                    # Ensure 6-digit format
                    if ticker and len(ticker) < 6:
                        ticker = ticker.zfill(6)

                if "name" in row and not pd.isna(row["name"]):
                    name = str(row["name"]).strip()

                target_price = row.get("target_price")

                if pd.isna(target_price):
                    continue

                # ticker가 없으면 name으로 조회
                if not ticker and name:
                    ticker = get_stock_code(name)
                    if not ticker:
                        print(f"[WARNING] Cannot find ticker for '{name}', skipping")
                        continue

                # name이 없으면 ticker로 조회
                if ticker and not name:
                    name = get_stock_name(ticker)

                if not ticker:
                    print(f"[WARNING] No ticker or name provided, skipping row")
                    continue

                item = {
                    "ticker": ticker,
                    "target_price": int(target_price),
                    "stop_loss_pct": None,
                    "name": name,
                    "exchange": "KRX",  # Default exchange
                    "max_units": 1,  # Default max units
                    "added_date": None,
                }

                # Optional custom stop loss
                if "stop_loss_pct" in row and not pd.isna(row["stop_loss_pct"]):
                    item["stop_loss_pct"] = float(row["stop_loss_pct"])

                # Optional exchange (KRX or NXT)
                if "exchange" in row and not pd.isna(row["exchange"]):
                    item["exchange"] = str(row["exchange"]).strip().upper()

                # Optional max_units (default 1)
                if "max_units" in row and not pd.isna(row["max_units"]):
                    item["max_units"] = int(row["max_units"])

                # Optional added_date
                if "added_date" in row and not pd.isna(row["added_date"]):
                    item["added_date"] = str(row["added_date"])

                watchlist.append(item)

            self.watchlist = watchlist
            self._file_mtime = self._get_file_mtime()

            # Clean up purchased_stocks: remove stocks no longer in watchlist
            watchlist_tickers = {item["ticker"] for item in watchlist}
            removed_from_purchased = []
            for ticker in list(self.purchased_stocks.keys()):
                if ticker not in watchlist_tickers:
                    removed_from_purchased.append(ticker)
                    del self.purchased_stocks[ticker]

            if removed_from_purchased:
                self._save_purchased_stocks()
                print(f"[INFO] Cleared {len(removed_from_purchased)} stocks from purchased list (removed from watchlist)")

            print(f"[INFO] Loaded {len(watchlist)} items from watchlist")
            return watchlist

        except Exception as e:
            print(f"[ERROR] Failed to load watchlist: {e}")
            return []

    def reload_if_changed(self) -> bool:
        """Reload watchlist if file has changed."""
        if self._check_file_changed():
            print(f"[INFO] File changed, reloading...")
            self.load_watchlist()
            return True
        return False

    def get_current_time_kst(self) -> datetime:
        """Get current time in Korea."""
        return datetime.now(KST)

    def is_market_open(self) -> bool:
        """Check if KRX market is open (9:00 AM - 3:30 PM KST)."""
        now_kst = self.get_current_time_kst()
        market_open = time(9, 0)
        market_close = time(15, 30)

        # Check weekday (Mon=0, Sun=6)
        if now_kst.weekday() >= 5:
            return False

        current_time = now_kst.time()
        return market_open <= current_time < market_close

    def is_near_market_close(self, minutes: int = 5) -> bool:
        """Check if we're within N minutes of KRX market close (15:30)."""
        now_kst = self.get_current_time_kst()
        market_close = time(15, 30)

        if now_kst.weekday() >= 5:
            return False

        current_time = now_kst.time()

        # Calculate minutes until close
        close_minutes = market_close.hour * 60 + market_close.minute
        current_minutes = current_time.hour * 60 + current_time.minute

        minutes_until_close = close_minutes - current_minutes

        return 0 < minutes_until_close <= minutes

    def is_nxt_session(self) -> bool:
        """Check if NXT market is open (8:00 - 20:00 KST)."""
        now_kst = self.get_current_time_kst()

        if now_kst.weekday() >= 5:
            return False

        current_time = now_kst.time()
        nxt_open = time(8, 0)
        nxt_close = time(20, 0)

        return nxt_open <= current_time < nxt_close

    def is_near_nxt_close(self, minutes: int = 5) -> bool:
        """Check if we're within N minutes of NXT market close (20:00)."""
        now_kst = self.get_current_time_kst()
        nxt_close = time(20, 0)

        if now_kst.weekday() >= 5:
            return False

        current_time = now_kst.time()

        # Calculate minutes until NXT close
        close_minutes = nxt_close.hour * 60 + nxt_close.minute
        current_minutes = current_time.hour * 60 + current_time.minute

        minutes_until_close = close_minutes - current_minutes

        return 0 < minutes_until_close <= minutes

    def is_any_market_active(self) -> bool:
        """Check if any trading/monitoring is possible (8:00~20:00, skip 15:20~15:40)."""
        return self.is_nxt_session()

    def is_market_open_time(self) -> bool:
        """Check if it's exactly market open time (within first minute)."""
        now_kst = self.get_current_time_kst()
        current_time = now_kst.time()

        market_open_start = time(9, 0)
        market_open_end = time(9, 1)

        return market_open_start <= current_time < market_open_end

    def is_pre_market_time(self) -> bool:
        """Check if it's 5 minutes before market open (8:55 AM KST)."""
        now_kst = self.get_current_time_kst()

        if now_kst.weekday() >= 5:
            return False

        current_time = now_kst.time()
        pre_market_start = time(8, 55)
        pre_market_end = time(8, 56)

        return pre_market_start <= current_time < pre_market_end

    def is_breakout_entry_allowed(self) -> bool:
        """
        Check if breakout entry is allowed at current time.

        돌파 매수: 8:00 ~ 15:20 (동시호가 시작 전까지)
        """
        now_kst = self.get_current_time_kst()

        if now_kst.weekday() >= 5:
            return False

        current_time = now_kst.time()

        return time(8, 0) <= current_time < time(15, 20)

    def get_current_session(self) -> Optional[str]:
        """
        Get current trading session name.

        Returns:
            "morning" for 8:00~15:00 - 돌파 매수 0.5 unit
            None if not in any session
        """
        now_kst = self.get_current_time_kst()

        if now_kst.weekday() >= 5:
            return None

        current_time = now_kst.time()

        # 돌파 매수: 8:00 ~ 15:00
        if time(8, 0) <= current_time < time(15, 0):
            return "morning"

        return None

    def is_krx_afternoon_close_session(self) -> bool:
        """Check if we're in KRX afternoon close session (15:15 ~ 15:28) for pyramiding/cut loss.

        15:15~15:20: trade history 동기화 + 지정가 주문
        15:20~15:28: 동시호가 (미처리 종목 재시도, 15:30 마감 전 여유)
        """
        now_kst = self.get_current_time_kst()

        if now_kst.weekday() >= 5:
            return False

        current_time = now_kst.time()
        return time(15, 15) <= current_time < time(15, 28)

    def is_before_krx_simultaneous_auction(self) -> bool:
        """Check if we're before KRX 동시호가 (before 15:20)."""
        now_kst = self.get_current_time_kst()

        if now_kst.weekday() >= 5:
            return True  # Not a trading day, so not relevant

        current_time = now_kst.time()
        return current_time < time(15, 20)

    def is_nxt_only_hours(self) -> bool:
        """
        Check if we're in NXT-only trading hours (KRX closed, NXT open).

        Returns True during:
        - 8:00 ~ 9:00 (NXT morning before KRX opens)
        - 15:40 ~ 20:00 (NXT afternoon/evening after KRX closes)

        During these hours, price queries should use NXT market.
        """
        now_kst = self.get_current_time_kst()

        if now_kst.weekday() >= 5:
            return False

        current_time = now_kst.time()

        # NXT morning session (before KRX opens): 8:00 ~ 9:00
        nxt_morning = time(8, 0) <= current_time < time(9, 0)

        # NXT afternoon/evening session (after KRX closes): 15:40 ~ 20:00
        nxt_afternoon = time(15, 40) <= current_time < time(20, 0)

        return nxt_morning or nxt_afternoon

    def get_current_market_display(self) -> str:
        """
        Get current market display string for UI.

        Returns:
        - "KRX" during KRX hours (9:00-15:40)
        - "NXT" during NXT-only hours (8:00-9:00, 15:40-20:00)
        - "CLOSED" outside trading hours
        """
        now_kst = self.get_current_time_kst()

        if now_kst.weekday() >= 5:
            return "CLOSED"

        current_time = now_kst.time()

        # All markets closed (before 8:00 or after 20:00)
        if current_time < time(8, 0) or current_time >= time(20, 0):
            return "CLOSED"

        # NXT morning (8:00-9:00)
        if time(8, 0) <= current_time < time(9, 0):
            return "NXT"

        # KRX regular session (9:00-15:40)
        if time(9, 0) <= current_time < time(15, 40):
            return "KRX"

        # NXT afternoon/evening (15:40-20:00)
        if time(15, 40) <= current_time < time(20, 0):
            return "NXT"

        return "CLOSED"

    def check_pre_market_reload(self) -> bool:
        """
        Check and perform pre-market reload (5 min before open).
        Returns True if reload was performed.
        """
        if not self.is_pre_market_time():
            self._pre_market_reloaded = False
            return False

        if self._pre_market_reloaded:
            return False

        print(f"[PRE-MARKET] Reloading settings and watchlist...")
        self.load_watchlist()
        self._pre_market_reloaded = True
        return True

    def get_price(self, symbol: str) -> Optional[dict]:
        """Get current price for symbol (auto-detects KRX/NXT based on time, with fallback)."""
        try:
            # Use NXT market during NXT-only hours (8:00-9:00, 15:40-20:00)
            # Falls back to KRX if NXT fails (some stocks don't support NXT)
            market_type = "NXT" if self.is_nxt_only_hours() else "KRX"
            return self.client.get_stock_price_with_fallback(symbol, market_type=market_type)
        except Exception as e:
            print(f"[{symbol}] Failed to get price: {e}")
            return None

    def get_unit_value(self, force_refresh: bool = False) -> int:
        """
        Get the value of 1 unit in KRW (cached for 60 seconds).
        1 unit = UNIT * 5% of net assets (default).

        Returns approximate unit value for position sizing.
        """
        import time as time_module

        # Use cached value if within 60 seconds
        if not force_refresh and self._unit_value_cache > 0:
            if time_module.time() - self._unit_value_time < 60:
                return self._unit_value_cache

        try:
            assets = self.client.get_net_assets()
            net_assets = assets.get("net_assets", 0)
            unit_pct = self.trading_settings.get_unit_percent()  # e.g., 5% if UNIT=1
            self._unit_value_cache = int(net_assets * unit_pct / 100)
            self._unit_value_time = time_module.time()
            return self._unit_value_cache
        except Exception as e:
            print(f"[WARNING] Could not get unit value: {e}")
            return self._unit_value_cache if self._unit_value_cache > 0 else 0

    def get_current_units(self, symbol: str) -> float:
        """
        Calculate current units for a stock based on holdings value.

        current_units = position_value / unit_value

        Returns float (can be 0.5, 1, 1.5, etc.)
        """
        unit_value = self.get_unit_value()
        if unit_value <= 0:
            return 0

        # Check positions
        pos = self.order_service.positions.get(symbol)
        if not pos:
            return 0

        entry_price = pos.get("entry_price", 0)
        quantity = pos.get("quantity", 0)

        if entry_price <= 0 or quantity <= 0:
            return 0

        position_value = entry_price * quantity
        return round(position_value / unit_value, 2)

    def can_buy_more_units(self, item: dict) -> bool:
        """
        Check if more units can be bought for a stock.

        Returns True if current_units < max_units.
        """
        symbol = item["ticker"]
        max_units = item.get("max_units", 1)
        current_units = self.get_current_units(symbol)

        return current_units < max_units

    def get_remaining_units(self, item: dict) -> float:
        """Get remaining units that can be bought."""
        max_units = item.get("max_units", 1)
        current_units = self.get_current_units(item["ticker"])
        return max(0, max_units - current_units)

    def get_watchlist_filtered(self) -> List[dict]:
        """
        Get watchlist filtered to only include items that haven't reached max_units.
        Used for display purposes to hide fully-allocated stocks.
        """
        return [item for item in self.watchlist if self.can_buy_more_units(item)]

    def is_sold_after_added(self, item: dict) -> bool:
        """
        Check if a watchlist item was sold after it was added.

        Returns True if:
        - Item has added_date AND
        - There's a sell record for this stock after added_date
        """
        symbol = item.get("ticker")
        added_date = item.get("added_date")

        if not symbol or not added_date:
            return False

        return self.was_sold_after_added(symbol, added_date)

    def has_today_position(self, symbol: str) -> bool:
        """
        Check if we already have a position purchased today.
        This is a safety check to prevent double-buying on bot restart.
        """
        pos = self.order_service.positions.get(symbol)
        if pos and pos.get('today_qty', 0) > 0:
            return True
        return False

    def passes_entry_gates(self, item: dict) -> bool:
        """
        Common gate conditions for all entry types (breakout, gap-up, etc.).
        New universal entry filters should be added here.
        """
        symbol = item["ticker"]

        # Skip if sold today (manual or stop loss)
        if self.is_sold_today(symbol):
            return False

        # Skip if sold after added to watchlist (permanent skip until re-added)
        if self.is_sold_after_added(item):
            return False

        # Check if we can buy more units (current_units < max_units)
        if not self.can_buy_more_units(item):
            return False

        # TODO: Industry Action 필터 (테마 분류기 완성 후 추가)
        # - watchlist 종목에 theme 컬럼 추가 (예: "2차전지", "반도체")
        # - 같은 테마 종목들(~5개)의 당일 평균 상승률 계산
        # - 시장(KOSPI/KOSDAQ) 당일 상승률과 비교
        # - 테마 평균 > 시장 평균이면 industry action 있음 → 매수 허용
        # - 테마 평균 <= 시장 평균이면 → 매수 차단
        # if not self.check_industry_action(item):
        #     return False

        # Re-sync holdings before checking (throttled to once per 30 seconds)
        # This prevents duplicate buys when holdings changed outside this bot
        now = datetime.now()
        if not hasattr(self, '_last_sync_time') or (now - self._last_sync_time).total_seconds() > 30:
            self.order_service.sync_positions_from_db()
            self._last_sync_time = now

        return True

    def check_breakout_entry(self, item: dict) -> bool:
        """
        Check if breakout entry condition is met.

        8:00~15:00에 돌파 매수 0.5 unit (하루 한 번만).
        피라미딩은 execute_close_logic (15:18)에서 별도 처리.
        """
        symbol = item["ticker"]
        target_price = item["target_price"]

        # Check if we're in valid breakout entry time window (8:00~15:00)
        if not self.is_breakout_entry_allowed():
            return False

        if not self.passes_entry_gates(item):
            return False

        # Already triggered today?
        if symbol in self.daily_triggers:
            return False

        # Safety check: already have today's position (prevents double-buy)
        if self.has_today_position(symbol):
            return False

        # Get current price
        price_data = self.get_price(symbol)
        if not price_data:
            return False

        current_price = price_data["last"]

        # Check breakout: 현재가 >= 기준가
        if current_price >= target_price:
            print(f"[{symbol}] BREAKOUT: {current_price:,}원 >= {target_price:,}원")
            return True

        return False

    def check_gap_up_entry(self, item: dict) -> bool:
        """
        Check if gap-up entry condition is met at market open.

        Returns True if:
        - It's market open time
        - Passes common entry gates
        - Open price > target price + tick buffer
        - Not already triggered in morning session
        """
        symbol = item["ticker"]
        target_price = item["target_price"]

        if not self.passes_entry_gates(item):
            return False

        # Gap-up is morning session only
        if symbol in self.daily_triggers:
            triggered_session = self.daily_triggers[symbol].get("session", "morning")
            if triggered_session == "morning":
                return False  # Already triggered in morning

        # Safety check: already have today's position (prevents double-buy on bot restart)
        if self.has_today_position(symbol):
            return False

        price_data = self.get_price(symbol)
        if not price_data:
            return False

        open_price = price_data["open"]
        tick_size = self.client.get_tick_size(target_price)
        trigger_price = target_price + (tick_size * self.trading_settings.TICK_BUFFER)

        if open_price >= trigger_price:
            print(f"[{symbol}] GAP UP: Open {open_price:,}원 >= {trigger_price:,}원")
            return True

        return False

    def execute_entry(self, item: dict, is_gap_up: bool = False) -> bool:
        """
        Execute breakout entry order (0.5 unit) with VI handling.

        VI 처리 로직:
        1. KRX에서 매수 주문
        2. 2초 대기 후 체결 확인
        3. 미체결 시: NXT 거래 가능하면 KRX 취소 → NXT 주문
        4. NXT 불가하면: pending_vi_orders에 등록 (3분 타임아웃)
        """
        import time as time_module

        symbol = item["ticker"]
        target_price = item["target_price"]
        stop_loss_pct = item.get("stop_loss_pct")

        # 주문 시도 전에 먼저 daily_triggers에 등록 (중복 주문 방지)
        self.daily_triggers[symbol] = {
            "entry_type": "gap_up" if is_gap_up else "breakout",
            "entry_time": datetime.now().isoformat(),
            "session": "morning",
            "status": "pending",
        }
        self._save_daily_triggers()  # Persist to file

        price_data = self.get_price(symbol)
        if not price_data:
            self.daily_triggers[symbol]["status"] = "price_failed"
            return False

        # Always use current price for entry (order_service will add tick buffer)
        current_price = price_data["last"]
        entry_price = current_price

        print(f"[{symbol}] Entry at current price: {current_price:,}원 (target was {target_price:,}원)")

        # Step 1: KRX 매수 주문
        result = self.order_service.execute_buy(
            symbol=symbol,
            target_price=entry_price,
            is_initial=True,
            stop_loss_pct=stop_loss_pct,
            market="KRX",
        )

        if not result:
            self.daily_triggers[symbol]["status"] = "order_failed"
            self._save_daily_triggers()
            return False

        order_no = result.get("order_no", "")

        # Step 2: 2초 대기 후 체결 확인
        time_module.sleep(2)

        filled = self._is_order_filled(symbol, order_no)

        if filled:
            # 즉시 체결됨 → 성공
            self.daily_triggers[symbol].update({
                "status": "success",
                "entry_price": entry_price,
            })
            self._save_daily_triggers()
            stock_name = item.get("name", "") or get_stock_name(symbol)
            self.mark_as_purchased(symbol, stock_name, entry_price)
            return True

        # Step 3: 미체결 → VI 가능성. NXT 거래 가능한지 확인
        print(f"[{symbol}] KRX 주문 미체결 (2초 경과). VI 의심 → NXT 확인...")

        nxt_tradable = self._check_nxt_tradable(symbol)

        if nxt_tradable:
            # NXT 가능: KRX 주문 취소 → NXT 재주문
            print(f"[{symbol}] NXT 거래 가능 → KRX 취소 후 NXT 주문")
            self.order_service.cancel_pending_orders_for_symbol(symbol)

            nxt_result = self.order_service.execute_buy(
                symbol=symbol,
                target_price=entry_price,
                is_initial=True,
                stop_loss_pct=stop_loss_pct,
                market="NXT",
            )

            if nxt_result:
                self.daily_triggers[symbol].update({
                    "status": "success",
                    "entry_price": entry_price,
                    "market": "NXT",
                })
                self._save_daily_triggers()
                stock_name = item.get("name", "") or get_stock_name(symbol)
                self.mark_as_purchased(symbol, stock_name, entry_price)
                return True
            else:
                self.daily_triggers[symbol]["status"] = "nxt_order_failed"
                self._save_daily_triggers()
                return False
        else:
            # NXT 불가: KRX 주문 유지, 3분 타임아웃으로 추적
            print(f"[{symbol}] NXT 불가 → KRX 주문 유지, 3분 타임아웃 추적 시작")
            self.pending_vi_orders[symbol] = {
                "order_no": order_no,
                "entry_price": entry_price,
                "ordered_at": time_module.time(),
                "timeout_seconds": 180,  # 3분
                "item": item,
            }
            self.daily_triggers[symbol].update({
                "status": "vi_pending",
                "entry_price": entry_price,
            })
            self._save_daily_triggers()
            return False  # 아직 체결 미확인이므로 False 반환

    def _is_order_filled(self, symbol: str, order_no: str) -> bool:
        """주문 체결 여부 확인 (미체결 목록에 없으면 체결된 것으로 판단)."""
        try:
            pending_orders = self.client.get_pending_orders()
            for order in pending_orders:
                order_symbol = order.get("stk_cd", "").replace("A", "")
                if order_symbol == symbol and order.get("ord_no", "") == order_no:
                    ncls_qty = int(order.get("ncls_qty", 0))
                    if ncls_qty > 0:
                        return False  # 미체결 수량 있음
            return True  # 미체결 목록에 없으면 체결 완료
        except Exception as e:
            print(f"[{symbol}] 체결 확인 실패: {e}")
            return False  # 확인 실패 시 미체결로 간주

    def _check_nxt_tradable(self, symbol: str) -> bool:
        """종목의 NXT 거래 가능 여부 확인 (NXT 가격 조회 후 price > 0이면 가능)."""
        try:
            result = self.client.get_stock_price(symbol, market_type="NXT")
            return result.get("last", 0) > 0
        except Exception:
            return False

    def check_pending_vi_orders(self):
        """
        VI 대기 주문 타임아웃 체크.
        3분 경과 시 미체결 주문 취소, 체결된 경우 성공 처리.
        """
        import time as time_module

        if not self.pending_vi_orders:
            return

        now = time_module.time()
        completed = []

        for symbol, vi_info in self.pending_vi_orders.items():
            order_no = vi_info["order_no"]
            ordered_at = vi_info["ordered_at"]
            timeout = vi_info["timeout_seconds"]
            elapsed = now - ordered_at

            # 먼저 체결 여부 확인
            filled = self._is_order_filled(symbol, order_no)

            if filled:
                # 체결 완료 → 성공 처리
                print(f"[{symbol}] VI 대기 주문 체결 완료! ({elapsed:.0f}초 경과)")
                entry_price = vi_info["entry_price"]
                item = vi_info["item"]

                self.daily_triggers[symbol].update({
                    "status": "success",
                    "entry_price": entry_price,
                    "vi_resolved": "filled",
                })
                self._save_daily_triggers()

                stock_name = item.get("name", "") or get_stock_name(symbol)
                self.mark_as_purchased(symbol, stock_name, entry_price)
                completed.append(symbol)

            elif elapsed >= timeout:
                # 3분 타임아웃 → 취소
                print(f"[{symbol}] VI 대기 3분 타임아웃 → 미체결 주문 취소")
                self.order_service.cancel_pending_orders_for_symbol(symbol)

                self.daily_triggers[symbol].update({
                    "status": "vi_timeout_cancelled",
                })
                self._save_daily_triggers()
                completed.append(symbol)

        for symbol in completed:
            del self.pending_vi_orders[symbol]

    def check_and_execute_stop_loss(self) -> List[dict]:
        """
        Check stop loss for all open positions.

        Logic:
        - Today's purchase: If -7% from today's entry → sell only today's qty (partial sell)
        - All positions: If -7% from total avg price → sell all
        - Runs 8:00~15:20 (KRX/NXT) and 15:40~20:00 (NXT)
        - Skips 15:20~15:40 (동시호가 + 시장 전환)

        Returns list of dicts with {symbol, type, qty} that were stopped out.
        """
        now_kst = self.get_current_time_kst()
        current_time = now_kst.time()

        # 15:20~15:40: 동시호가 + KRX/NXT 전환 구간 → 손절 안함
        if time(15, 20) <= current_time < time(15, 40):
            return []

        # 그 외 NXT 세션 (8:00~20:00) 중이어야 함
        if not self.is_nxt_session():
            return []

        stopped = []

        for pos in self.order_service.get_open_positions():
            symbol = pos["symbol"]

            price_data = self.get_price(symbol)
            if not price_data:
                continue

            current_price = price_data["last"]

            # check_stop_loss returns dict with triggered, type, qty
            stop_result = self.order_service.check_stop_loss(symbol, current_price)

            if stop_result.get("triggered"):
                stop_type = stop_result.get("type", "all")
                sell_qty = stop_result.get("qty", 0)
                change_pct = stop_result.get("change_pct", 0)
                lot_entry = stop_result.get("entry_price", 0)

                # 손절 시 현재가 - 3틱으로 주문 (체결 확보)
                tick_size = self.client.get_tick_size(current_price)
                sell_price = current_price - (tick_size * 3)

                if stop_type == "lot":
                    print(f"[{symbol}] STOP LOSS (LIFO lot): {change_pct:+.2f}% (진입가 {lot_entry:,}원) → sell {sell_qty}주 @ {sell_price:,}원")
                elif stop_type == "today":
                    print(f"[{symbol}] STOP LOSS (today's buy): {change_pct:+.2f}% → sell {sell_qty}주 @ {sell_price:,}원")
                else:
                    print(f"[{symbol}] STOP LOSS (total): {change_pct:+.2f}% → sell ALL @ {sell_price:,}원")

                result = self.order_service.execute_sell(
                    symbol=symbol,
                    price=sell_price,
                    reason=f"stop_loss_{stop_type}",
                    sell_qty=sell_qty,
                )
                if result:
                    stopped.append({
                        "symbol": symbol,
                        "type": stop_type,
                        "qty": sell_qty,
                        "lot_id": stop_result.get("lot_id"),
                    })

        return stopped

    def check_volume_condition(self, symbol: str, today_volume: int) -> bool | None:
        """
        Check if today's volume meets the threshold vs N-day average.
        Fetches historical volume via ka10086 API.

        Returns:
            True  - volume condition met (today >= avg * multiplier)
            False - volume condition NOT met
            None  - API error or no data
        """
        days = self.trading_settings.VOLUME_MA_DAYS
        multiplier = self.trading_settings.VOLUME_MULTIPLIER

        # ka10086 returns today + past days; we need past N days only
        daily_data = self.client.get_stock_daily_prices(symbol, days=days + 1)
        if not daily_data:
            return None

        # Skip today (first entry), take past N days
        past_data = [d for d in daily_data if d["volume"] > 0][1:days + 1]
        if len(past_data) < days:
            return None

        avg_volume = sum(d["volume"] for d in past_data) / len(past_data)
        if avg_volume <= 0:
            return None

        ratio = today_volume / avg_volume
        meets = today_volume >= avg_volume * multiplier
        print(f"[{symbol}] Volume: {today_volume:,} / Avg({days}d): {avg_volume:,.0f} = {ratio:.2f}x {'>=': if meets else '<'} {multiplier}x")
        return meets

    def _get_today_net_buys(self) -> Dict[str, dict]:
        """
        Get today's net buy positions from account_trade_history.

        For each stock, calculates:
        - net_qty: today_buy_qty - today_sell_qty (only if > 0)
        - avg_buy_price: weighted average of today's buy prices

        Returns dict of {symbol: {"net_qty": int, "avg_buy_price": int}}
        """
        today = date.today()
        result = {}

        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT stk_cd, io_tp_nm, cntr_qty, cntr_uv
                    FROM account_trade_history
                    WHERE trade_date = %s
                    ORDER BY stk_cd
                """, (today,))
                trades = cur.fetchall()
            conn.close()
        except Exception as e:
            print(f"[ERROR] Failed to get today's trades: {e}")
            return result

        # Group by stock
        from collections import defaultdict
        stock_trades = defaultdict(lambda: {"buy_qty": 0, "buy_value": 0, "sell_qty": 0})

        for stk_cd, io_tp_nm, cntr_qty, cntr_uv in trades:
            symbol = stk_cd.replace("A", "").zfill(6)
            tp = io_tp_nm or ""
            qty = cntr_qty or 0
            price = cntr_uv or 0

            is_buy = "매수" in tp and "매도" not in tp and "상환" not in tp
            is_sell = ("매도" in tp or "상환" in tp) and "매수" not in tp

            if is_buy:
                stock_trades[symbol]["buy_qty"] += qty
                stock_trades[symbol]["buy_value"] += qty * price
            elif is_sell:
                stock_trades[symbol]["sell_qty"] += qty

        for symbol, data in stock_trades.items():
            net_qty = data["buy_qty"] - data["sell_qty"]
            if net_qty > 0 and data["buy_qty"] > 0:
                avg_buy_price = int(data["buy_value"] / data["buy_qty"])
                result[symbol] = {"net_qty": net_qty, "avg_buy_price": avg_buy_price}

        return result

    def execute_close_logic(self) -> Dict[str, str]:
        """
        Execute end-of-day close logic for positions (15:18-15:28).

        1. ALL positions with lots: If -7% from LIFO lot entry → sell that lot
        2. TODAY's entries (today_qty > 0 from holdings tdy_buyq):
           - If current > today_entry_price: pyramid (0.5 unit)
           - If current <= today_entry_price: sell today_qty

        Uses today_entry_price from holdings (not daily_lots) since
        daily_lots are only constructed at 15:35 by daily_sync.

        Returns dict of {symbol: action_taken}
        """
        actions = {}
        stop_loss_pct = self.trading_settings.STOP_LOSS_PCT  # Default 7%

        # Get today's net buys from account_trade_history (accurate entry prices)
        today_net_buys = self._get_today_net_buys()
        if today_net_buys:
            items = [f"{s}({d['net_qty']}주@{d['avg_buy_price']:,})" for s, d in today_net_buys.items()]
            print(f"[CLOSE] Today's net buys: {', '.join(items)}")

        for pos in self.order_service.get_open_positions():
            symbol = pos["symbol"]

            # Skip symbols already processed by close logic today
            if symbol in self.close_actions_done:
                continue

            price_data = self.get_price(symbol)
            if not price_data:
                continue

            current_price = price_data["last"]
            if current_price <= 0:
                continue

            # 1. ALL positions: Check -7% stop loss (LIFO lot based, if lot exists)
            try:
                conn = get_connection()
                latest_lot = get_latest_lot(conn, symbol)
                conn.close()
            except Exception as e:
                print(f"[{symbol}] Failed to get latest lot: {e}")
                latest_lot = None

            if latest_lot:
                lot_entry_price = int(latest_lot["avg_purchase_price"])
                lot_qty = latest_lot["net_quantity"]

                if lot_entry_price > 0:
                    lot_change_pct = ((current_price / lot_entry_price) - 1) * 100

                    if lot_change_pct <= -stop_loss_pct:
                        tick_size = self.client.get_tick_size(current_price)
                        sell_price = current_price - (tick_size * 3)
                        print(f"[{symbol}] CLOSE STOP (lot): {lot_change_pct:+.2f}% <= -{stop_loss_pct}% - SELL {lot_qty}주 @ {sell_price:,}원")

                        result = self.order_service.execute_sell(
                            symbol=symbol,
                            price=sell_price,
                            reason="close_stop_loss_lot",
                            sell_qty=lot_qty,
                        )

                        if result:
                            actions[symbol] = "close_stop_loss"
                            self.close_actions_done.add(symbol)
                        else:
                            actions[symbol] = "close_stop_loss_failed"
                        continue  # Skip other logic for this symbol

            # 2. TODAY's entries: pyramid or cut loss
            # Use net buy data from account_trade_history (accurate avg buy price)
            today_data = today_net_buys.get(symbol)
            if not today_data:
                continue

            today_qty = today_data["net_qty"]
            today_entry_price = today_data["avg_buy_price"]

            if today_qty <= 0 or today_entry_price <= 0:
                continue

            change_pct = ((current_price / today_entry_price) - 1) * 100

            if current_price > today_entry_price:
                # Profitable (>0%) - check volume condition for pyramid
                today_volume = price_data.get("volume", 0)

                vol_ok = self.check_volume_condition(symbol, today_volume)

                if vol_ok is None or vol_ok:
                    # Volume condition met (or insufficient data) → pyramid
                    print(f"[{symbol}] Close {current_price:,}원 > Entry {today_entry_price:,}원 ({change_pct:+.2f}%) - PYRAMID")

                    watchlist_item = next(
                        (w for w in self.watchlist if w["ticker"] == symbol),
                        None
                    )
                    custom_stop_loss_pct = watchlist_item.get("stop_loss_pct") if watchlist_item else None

                    result = self.order_service.execute_buy(
                        symbol=symbol,
                        target_price=current_price,
                        is_initial=False,
                        stop_loss_pct=custom_stop_loss_pct,
                    )

                    if result:
                        actions[symbol] = "pyramid"
                        self.close_actions_done.add(symbol)
                    else:
                        actions[symbol] = "pyramid_failed"
                else:
                    # Volume insufficient → take profit
                    tick_size = self.client.get_tick_size(current_price)
                    sell_price = current_price - (tick_size * 3)
                    print(f"[{symbol}] Close {current_price:,}원 > Entry ({change_pct:+.2f}%) but LOW VOLUME - TAKE PROFIT {today_qty}주 @ {sell_price:,}원")

                    result = self.order_service.execute_sell(
                        symbol=symbol,
                        price=sell_price,
                        reason="close_take_profit_low_volume",
                        sell_qty=today_qty,
                    )

                    if result:
                        actions[symbol] = "take_profit"
                        self.close_actions_done.add(symbol)
                    else:
                        actions[symbol] = "take_profit_failed"

            else:
                # Loss (0% 이하) - sell today's quantity
                tick_size = self.client.get_tick_size(current_price)
                sell_price = current_price - (tick_size * 3)
                print(f"[{symbol}] Close {current_price:,}원 <= Entry {today_entry_price:,}원 ({change_pct:+.2f}%) - SELL {today_qty}주 @ {sell_price:,}원")

                result = self.order_service.execute_sell(
                    symbol=symbol,
                    price=sell_price,
                    reason="close_below_entry",
                    sell_qty=today_qty,  # Sell only today's buy quantity
                )

                if result:
                    actions[symbol] = "sold"
                    self.close_actions_done.add(symbol)
                else:
                    actions[symbol] = "sell_failed"

        return actions

    def reset_daily_triggers(self):
        """Reset daily triggers and sold_today (call at start of new trading day)."""
        self.daily_triggers = {}
        self._save_daily_triggers()  # Persist to file
        self.sold_today = {}
        self._save_sold_today()
        self.close_actions_done = set()
        self.pending_vi_orders = {}
        print("[INFO] Daily triggers, sold_today, and close_actions reset")

    def run_monitoring_cycle(self) -> dict:
        """
        Run one monitoring cycle.

        Returns dict with actions taken.
        """
        result = {
            "timestamp": datetime.now().isoformat(),
            "market_open": self.is_market_open(),
            "entries": [],
            "stop_losses": [],
            "close_actions": {},
            "reloaded": False,
        }

        # Check for file changes
        if self.reload_if_changed():
            result["reloaded"] = True

        # Pre-market reload (5 min before open)
        if self.check_pre_market_reload():
            result["reloaded"] = True

        # Check if any market is active (8:00~20:00)
        if not self.is_any_market_active():
            return result

        # 1. 손절 체크 (가장 높은 우선순위 - 다른 로직 에러에 영향받지 않도록)
        stopped = self.check_and_execute_stop_loss()
        result["stop_losses"] = stopped

        # 2. 종가 로직 (15:18-15:28): pyramid if >0%, cut loss if <=0%
        if self.is_krx_afternoon_close_session():
            # 종가 세션 첫 진입 시 trade history 강제 동기화
            if not self.close_actions_done:
                try:
                    from services.kiwoom_service import sync_trade_history_from_kiwoom
                    conn = get_connection()
                    today_str = date.today().strftime("%Y%m%d")
                    sync_trade_history_from_kiwoom(conn, start_date=today_str)
                    conn.close()
                    print("[CLOSE] Synced today's trade history for close logic")
                except Exception as e:
                    print(f"[CLOSE] Trade history sync failed: {e}")

            close_actions = self.execute_close_logic()
            result["close_actions"].update(close_actions)

        # 3. VI 대기 주문 타임아웃 체크
        try:
            self.check_pending_vi_orders()
        except Exception as e:
            print(f"[ERROR] VI order check failed: {e}")

        # 4. 매수 체크 (try/except로 감싸서 에러 시에도 위 로직에 영향 없음)
        try:
            # Gap-up entries at market open
            if self.is_market_open_time():
                for item in self.watchlist:
                    if self.check_gap_up_entry(item):
                        if self.execute_entry(item, is_gap_up=True):
                            result["entries"].append({
                                "symbol": item["ticker"],
                                "type": "gap_up",
                            })

            # Breakout entries
            for item in self.watchlist:
                if self.check_breakout_entry(item):
                    if self.execute_entry(item, is_gap_up=False):
                        result["entries"].append({
                            "symbol": item["ticker"],
                            "type": "breakout",
                        })
        except Exception as e:
            print(f"[ERROR] Entry check failed: {e}")

        return result

    def get_status(self) -> dict:
        """Get current monitoring status."""
        return {
            "current_time_kst": self.get_current_time_kst().isoformat(),
            "market_open": self.is_market_open(),
            "near_krx_close": self.is_near_market_close(5),
            "any_market_active": self.is_any_market_active(),
            "watchlist_count": len(self.watchlist),
            "open_positions": len(self.order_service.get_open_positions()),
            "daily_triggers": len(self.daily_triggers),
        }
