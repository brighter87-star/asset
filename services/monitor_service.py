"""
Monitor service for price monitoring and trading strategy execution.
"""

import json
import os
import pandas as pd
from datetime import datetime, time
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from services.kiwoom_service import KiwoomTradingClient, get_stock_code, get_stock_name
from services.order_service import OrderService
from services.trade_logger import trade_logger

# Watchlist file paths (CSV takes priority over xlsx)
WATCHLIST_DIR = Path(__file__).resolve().parent.parent
WATCHLIST_CSV = WATCHLIST_DIR / "watchlist.csv"
WATCHLIST_XLSX = WATCHLIST_DIR / "watchlist.xlsx"
SETTINGS_CSV = WATCHLIST_DIR / "settings.csv"
PURCHASED_STOCKS_FILE = WATCHLIST_DIR / "purchased_stocks.json"
DAILY_TRIGGERS_FILE = WATCHLIST_DIR / "daily_triggers.json"

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
        self._load_purchased_stocks()
        self._load_daily_triggers()

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
                  f"SL={self.trading_settings.STOP_LOSS_PCT}%")

            trade_logger.log_settings_change({
                "UNIT": self.trading_settings.UNIT,
                "TICK_BUFFER": self.trading_settings.TICK_BUFFER,
                "STOP_LOSS_PCT": self.trading_settings.STOP_LOSS_PCT,
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
        """Check if any trading is possible (KRX or NXT breakout windows)."""
        return self.is_market_open() or self.is_breakout_entry_allowed()

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

        In Korea, most stocks trade on both KRX and NXT markets:
        - KRX: 9:00 ~ 15:30 (15:20~15:30 is 동시호가, no execution)
        - NXT: 8:00 ~ 20:00

        Breakout windows:
        - 8:00 ~ 8:05 (NXT morning open) - 0.5 unit
        - 9:00 ~ 9:10 (KRX morning open) - 0.5 unit
        - 15:15 ~ 15:20 (KRX afternoon, right before 동시호가) - 0.5 unit
        - 19:30 ~ 20:00 (NXT evening):
          - 저녁에 첫 돌파: 1 unit (0.5 + 피라미딩 0.5)
          - 오전/오후에 이미 매수: 추가 0.5 unit

        Morning (8:00~9:10) and afternoon (15:15~15:20) are separate sessions.
        A stock can be bought in both sessions (0.5 + 0.5 = 1 unit).

        Outside these windows, watchlist is monitored but no buy execution.
        """
        now_kst = self.get_current_time_kst()

        if now_kst.weekday() >= 5:
            return False

        current_time = now_kst.time()

        # NXT morning open: 8:00 ~ 8:05
        nxt_morning_start = time(8, 0)
        nxt_morning_end = time(8, 5)

        # KRX morning open: 9:00 ~ 9:10
        krx_morning_start = time(9, 0)
        krx_morning_end = time(9, 10)

        # KRX afternoon: 15:15 ~ 15:20 (right before 동시호가 at 15:20)
        krx_afternoon_start = time(15, 15)
        krx_afternoon_end = time(15, 20)

        # NXT evening close: 19:30 ~ 20:00
        nxt_evening_start = time(19, 30)
        nxt_evening_end = time(20, 0)

        in_nxt_morning = nxt_morning_start <= current_time < nxt_morning_end
        in_krx_morning = krx_morning_start <= current_time < krx_morning_end
        in_krx_afternoon = krx_afternoon_start <= current_time < krx_afternoon_end
        in_nxt_evening = nxt_evening_start <= current_time < nxt_evening_end

        return in_nxt_morning or in_krx_morning or in_krx_afternoon or in_nxt_evening

    def get_current_session(self) -> Optional[str]:
        """
        Get current trading session name.

        Returns:
            "morning" for 8:00~9:10 (NXT + KRX open)
            "afternoon" for 15:15~15:20 (before 동시호가)
            "evening" for 19:30~20:00 (NXT close)
            None if not in any session
        """
        now_kst = self.get_current_time_kst()

        if now_kst.weekday() >= 5:
            return None

        current_time = now_kst.time()

        # Morning: 8:00 ~ 9:10 (NXT 8:00-8:05 + KRX 9:00-9:10)
        if time(8, 0) <= current_time < time(9, 10):
            return "morning"

        # Afternoon: 15:15 ~ 15:20 (before 동시호가)
        if time(15, 15) <= current_time < time(15, 20):
            return "afternoon"

        # Evening: 19:30 ~ 20:00 (NXT close)
        if time(19, 30) <= current_time < time(20, 0):
            return "evening"

        return None

    def is_nxt_evening_session(self) -> bool:
        """Check if we're in NXT evening session (19:30 ~ 20:00)."""
        now_kst = self.get_current_time_kst()

        if now_kst.weekday() >= 5:
            return False

        current_time = now_kst.time()
        return time(19, 30) <= current_time < time(20, 0)

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

    def has_today_position(self, symbol: str) -> bool:
        """
        Check if we already have a position purchased today.
        This is a safety check to prevent double-buying on bot restart.
        """
        pos = self.order_service.positions.get(symbol)
        if pos and pos.get('today_qty', 0) > 0:
            return True
        return False

    def check_breakout_entry(self, item: dict) -> bool:
        """
        Check if breakout entry condition is met.

        Returns True if:
        - Within valid breakout time window:
          8:00-9:10 (morning), 15:15-15:20 (afternoon), 19:30-20:00 (evening)
        - Current price >= target price
        - Not already triggered in THIS session (morning/afternoon/evening are separate)
        - current_units < max_units (can still buy more)
        """
        symbol = item["ticker"]
        target_price = item["target_price"]

        # Check if we're in valid breakout entry time window
        if not self.is_breakout_entry_allowed():
            return False

        # Check current session
        current_session = self.get_current_session()
        if not current_session:
            return False

        # Already triggered in THIS session?
        # Morning and afternoon are separate - can buy 0.5 unit in morning and 0.5 unit in afternoon
        if symbol in self.daily_triggers:
            triggered_session = self.daily_triggers[symbol].get("session", "morning")
            if triggered_session == current_session:
                return False  # Already triggered in this session

        # Safety check: already have today's position (prevents double-buy on bot restart)
        if self.has_today_position(symbol):
            return False

        # Check if we can buy more units (current_units < max_units)
        if not self.can_buy_more_units(item):
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
        - Open price > target price
        - Not already triggered in morning session
        - current_units < max_units (can still buy more)
        """
        symbol = item["ticker"]
        target_price = item["target_price"]

        # Gap-up is morning session only
        if symbol in self.daily_triggers:
            triggered_session = self.daily_triggers[symbol].get("session", "morning")
            if triggered_session == "morning":
                return False  # Already triggered in morning

        # Safety check: already have today's position (prevents double-buy on bot restart)
        if self.has_today_position(symbol):
            return False

        # Check if we can buy more units (current_units < max_units)
        if not self.can_buy_more_units(item):
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
        """Execute entry order."""
        symbol = item["ticker"]
        target_price = item["target_price"]
        stop_loss_pct = item.get("stop_loss_pct")

        # NXT 저녁 (19:30-20:00)에 "첫 진입"이면 full 1 unit 매수
        # 첫 진입 = 저녁 세션이고 오늘 이 종목을 아직 안 샀을 때
        is_nxt_evening_first_entry = self.is_nxt_evening_session() and not self.has_today_position(symbol)

        # Get current session for tracking
        current_session = self.get_current_session() or "morning"

        # 주문 시도 전에 먼저 daily_triggers에 등록 (중복 주문 방지)
        self.daily_triggers[symbol] = {
            "entry_type": "gap_up" if is_gap_up else "breakout",
            "entry_time": datetime.now().isoformat(),
            "session": current_session,  # Track which session triggered
            "status": "pending",
            "nxt_evening_entry": is_nxt_evening_first_entry,
        }
        self._save_daily_triggers()  # Persist to file

        price_data = self.get_price(symbol)
        if not price_data:
            self.daily_triggers[symbol]["status"] = "price_failed"
            return False

        # Use current price for gap up, target price for breakout
        if is_gap_up:
            entry_price = price_data["last"]
        else:
            entry_price = target_price

        # First buy (0.5 unit)
        result = self.order_service.execute_buy(
            symbol=symbol,
            target_price=entry_price,
            is_initial=True,
            stop_loss_pct=stop_loss_pct,
        )

        if result:
            self.daily_triggers[symbol].update({
                "status": "success",
                "entry_price": entry_price,
            })
            self._save_daily_triggers()  # Persist to file

            # NXT 저녁 첫 진입이면 바로 피라미딩 (full 1 unit)
            # 오전/오후에 이미 매수한 경우에는 피라미딩 안함 (0.5 unit만)
            if is_nxt_evening_first_entry:
                print(f"[{symbol}] NXT evening FIRST entry - adding pyramid for full 1 unit")
                self.order_service.execute_buy(
                    symbol=symbol,
                    target_price=entry_price,
                    is_initial=False,  # pyramid
                    stop_loss_pct=stop_loss_pct,
                )

            # Mark as purchased to prevent duplicate buys
            # User must remove from watchlist.csv to re-enable buying
            stock_name = item.get("name", "") or get_stock_name(symbol)
            self.mark_as_purchased(symbol, stock_name, entry_price)
            return True
        else:
            self.daily_triggers[symbol]["status"] = "order_failed"
            self._save_daily_triggers()  # Persist to file
            return False

    def check_and_execute_stop_loss(self) -> List[dict]:
        """
        Check stop loss for all open positions.

        Logic:
        - Today's purchase: If -7% from today's entry → sell only today's qty (partial sell)
        - All positions: If -7% from total avg price → sell all
        - Only runs before KRX 동시호가 (before 15:20) or during NXT evening

        Returns list of dicts with {symbol, type, qty} that were stopped out.
        """
        # KRX 동시호가 시간(15:20-15:30)에는 손절 안함
        if not self.is_before_krx_simultaneous_auction() and not self.is_nxt_evening_session():
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

    def execute_close_logic(self) -> Dict[str, str]:
        """
        Execute end-of-day close logic for ALL positions.

        Logic:
        1. ALL positions: If close price is -7% from entry → sell all (stop loss at close)
        2. TODAY's entries only (via daily_triggers):
           - If close > entry: Add 0.5 unit (pyramid)
           - If close < entry (0% 미만): Sell all (cut loss)

        Returns dict of {symbol: action_taken}
        """
        actions = {}
        stop_loss_pct = self.trading_settings.STOP_LOSS_PCT  # Default 7%

        for pos in self.order_service.get_open_positions():
            symbol = pos["symbol"]
            entry_price = pos.get("entry_price", 0)

            if entry_price <= 0:
                continue

            price_data = self.get_price(symbol)
            if not price_data:
                continue

            current_price = price_data["last"]
            change_pct = ((current_price / entry_price) - 1) * 100

            # 1. ALL positions: Check -7% stop loss at close
            if change_pct <= -stop_loss_pct:
                tick_size = self.client.get_tick_size(current_price)
                sell_price = current_price - (tick_size * 3)
                print(f"[{symbol}] CLOSE STOP: {change_pct:+.2f}% <= -{stop_loss_pct}% - SELL @ {sell_price:,}원")

                result = self.order_service.execute_sell(
                    symbol=symbol,
                    price=sell_price,
                    reason="close_stop_loss",
                )

                if result:
                    actions[symbol] = "close_stop_loss"
                else:
                    actions[symbol] = "close_stop_loss_failed"
                continue  # Skip other logic for this symbol

            # 2. TODAY's entries only: pyramid or cut loss
            if symbol not in self.daily_triggers:
                continue

            if current_price > entry_price:
                # Profitable - pyramid
                print(f"[{symbol}] Close {current_price:,}원 > Entry {entry_price:,}원 ({change_pct:+.2f}%) - PYRAMID")

                # Find watchlist item for stop_loss_pct
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
                else:
                    actions[symbol] = "pyramid_failed"

            else:
                # Loss (0% 미만) - sell all
                tick_size = self.client.get_tick_size(current_price)
                sell_price = current_price - (tick_size * 3)
                print(f"[{symbol}] Close {current_price:,}원 <= Entry {entry_price:,}원 ({change_pct:+.2f}%) - SELL @ {sell_price:,}원")

                result = self.order_service.execute_sell(
                    symbol=symbol,
                    price=sell_price,
                    reason="close_below_entry",
                )

                if result:
                    actions[symbol] = "sold"
                else:
                    actions[symbol] = "sell_failed"

        return actions

    def reset_daily_triggers(self):
        """Reset daily triggers (call at start of new trading day)."""
        self.daily_triggers = {}
        self._save_daily_triggers()  # Persist to file
        print("[INFO] Daily triggers reset")

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

        # Check if any market is active (KRX or NXT breakout windows)
        if not self.is_any_market_active():
            return result

        # Check market open gap-up entries
        if self.is_market_open_time():
            for item in self.watchlist:
                if self.check_gap_up_entry(item):
                    if self.execute_entry(item, is_gap_up=True):
                        result["entries"].append({
                            "symbol": item["ticker"],
                            "type": "gap_up",
                        })

        # Check breakout entries
        for item in self.watchlist:
            if self.check_breakout_entry(item):
                if self.execute_entry(item, is_gap_up=False):
                    result["entries"].append({
                        "symbol": item["ticker"],
                        "type": "breakout",
                    })

        # Check stop losses
        stopped = self.check_and_execute_stop_loss()
        result["stop_losses"] = stopped

        # Execute close logic near NXT close only (19:55-20:00)
        # KRX close (15:20-15:30) is 동시호가, skip pyramid there
        if self.is_near_nxt_close(5):
            result["close_actions"] = self.execute_close_logic()

        return result

    def get_status(self) -> dict:
        """Get current monitoring status."""
        return {
            "current_time_kst": self.get_current_time_kst().isoformat(),
            "market_open": self.is_market_open(),
            "nxt_session": self.is_nxt_session(),
            "near_krx_close": self.is_near_market_close(5),
            "near_nxt_close": self.is_near_nxt_close(5),
            "any_market_active": self.is_any_market_active(),
            "watchlist_count": len(self.watchlist),
            "open_positions": len(self.order_service.get_open_positions()),
            "daily_triggers": len(self.daily_triggers),
        }
