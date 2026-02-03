"""
Automated Trading System for Korean Stocks (Kiwoom)
Trend-following breakout strategy with pyramiding.

Usage:
    python auto_trade.py              # Run trading loop
    python auto_trade.py --status     # Show current status with live prices
    python auto_trade.py --test       # Test API connection
    python auto_trade.py --price-test # Test price API (ka10001)
"""

import sys
import time
from datetime import datetime

from db.connection import get_connection
from services.kiwoom_service import KiwoomTradingClient, get_stock_name, sync_holdings_from_kiwoom
from services.monitor_service import MonitorService
from services.trade_logger import trade_logger
from services.price_service import RestPricePoller, KiwoomWebSocketClient


def load_today_trades_from_db() -> list:
    """Load today's completed trades from account_trade_history table."""
    from datetime import date
    trades = []

    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    stk_cd, stk_nm, io_tp_nm, cntr_qty, cntr_uv, ord_tm, crd_class
                FROM account_trade_history
                WHERE trade_date = %s
                  AND cntr_qty > 0
                ORDER BY ord_tm ASC
            """, (date.today(),))

            rows = cur.fetchall()

        conn.close()

        for row in rows:
            stk_cd, stk_nm, io_tp_nm, cntr_qty, cntr_uv, ord_tm, crd_class = row

            # 매매구분 정리
            side = "매수"
            if io_tp_nm:
                if "매도" in io_tp_nm or "상환" in io_tp_nm:
                    side = "매도"
                elif "매수" in io_tp_nm:
                    side = "매수"

            # 종목코드에서 A 제거
            stock_code = stk_cd.replace('A', '') if stk_cd else ''

            # 주문시간 포맷 (HHMMSS -> HH:MM:SS)
            time_str = ord_tm[:2] + ":" + ord_tm[2:4] + ":" + ord_tm[4:6] if ord_tm and len(ord_tm) >= 6 else ord_tm or ""

            trades.append({
                "time": time_str,
                "symbol": stock_code,
                "name": stk_nm or "",
                "side": side,
                "quantity": cntr_qty or 0,
                "price": cntr_uv or 0,
                "status": "체결",
                "crd_class": crd_class or "",
            })

    except Exception as e:
        print(f"[WARN] Failed to load today's trades: {e}")

    return trades


def load_holdings_prices_from_db() -> dict:
    """Load current prices from holdings table for initial price cache."""
    from datetime import date
    prices = {}

    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT REPLACE(stk_cd, 'A', '') as stock_code, MAX(cur_prc) as cur_prc
                FROM holdings
                WHERE snapshot_date = %s AND cur_prc > 0
                GROUP BY stk_cd
            """, (date.today(),))

            rows = cur.fetchall()

        conn.close()

        for row in rows:
            stock_code, cur_prc = row
            if stock_code and cur_prc:
                prices[stock_code] = {"last": int(cur_prc)}

    except Exception as e:
        print(f"[WARN] Failed to load holdings prices: {e}")

    return prices


def print_banner():
    """Print startup banner."""
    print("=" * 70)
    print("  Korean Stock Auto Trading System (Kiwoom)")
    print("  신용매수 + 120% 레버리지 한도")
    print("=" * 70)


def print_settings(monitor: MonitorService = None):
    """Print current settings."""
    if monitor:
        s = monitor.trading_settings
        unit_pct = s.get_unit_percent()
        max_lev = getattr(s, 'MAX_LEVERAGE_PCT', 120.0)
    else:
        s = type('S', (), {'UNIT': 1, 'TICK_BUFFER': 3, 'STOP_LOSS_PCT': 7.0})()
        unit_pct = 5.0
        max_lev = 120.0

    print("\n[Settings]")
    print(f"  UNIT: {s.UNIT} ({unit_pct}% of assets)")
    print(f"  TICK_BUFFER: {s.TICK_BUFFER} ticks")
    print(f"  STOP_LOSS_PCT: {s.STOP_LOSS_PCT}%")
    print(f"  MAX_LEVERAGE: {max_lev}%")


def test_connection():
    """Test API connection."""
    print("\n[Testing API Connection]")

    client = KiwoomTradingClient()

    try:
        token = client.get_access_token()
        print(f"  Token: OK ({token[:20]}...)")
    except Exception as e:
        print(f"  Token: FAILED - {e}")
        return False

    try:
        power = client.get_buying_power()
        print(f"  매수가능금액: {power['available_amt']:,}원")
    except Exception as e:
        print(f"  매수가능금액: FAILED - {e}")
        return False

    try:
        assets = client.get_net_assets()
        print(f"  순자산: {assets['net_assets']:,}원")
        print(f"  주식평가: {assets['stock_assets']:,}원")
        print(f"  주식 비중: {assets['leverage_pct']:.1f}%")
    except Exception as e:
        print(f"  순자산: FAILED - {e}")
        return False

    # Price API는 보유종목만 조회 가능 (비보유 종목은 WebSocket 필요)
    try:
        holdings = client.get_holdings()
        holdings_list = holdings.get("stk_acnt_evlt_prst", [])
        if holdings_list:
            first_stock = holdings_list[0]
            stock_code = first_stock.get("stk_cd", "")
            stock_name = first_stock.get("stk_nm", "")
            cur_price = int(first_stock.get("cur_prc", 0) or 0)
            print(f"  보유종목: {stock_name} ({stock_code}) @ {cur_price:,}원")
        else:
            print(f"  보유종목: 없음 (가격조회는 WebSocket 필요)")
    except Exception as e:
        print(f"  보유종목: FAILED - {e}")
        return False

    print("\n  All tests passed!")
    return True


def test_price_api():
    """Test REST price API (ka10001)."""
    print("\n[Testing Price API]")

    client = KiwoomTradingClient()

    # Test individual stock price
    test_stocks = ["005930", "000660"]  # Samsung, SK Hynix

    for code in test_stocks:
        try:
            price = client.get_stock_price(code)
            name = price.get("name", code)
            last = price.get("last", 0)
            change = price.get("change", 0)
            change_pct = price.get("change_pct", 0)

            if last > 0:
                print(f"  {name} ({code}): {last:,}원 ({change:+,}원, {change_pct:+.2f}%)")
            else:
                print(f"  {code}: FAILED - no price data")
                return False
        except Exception as e:
            print(f"  {code}: FAILED - {e}")
            return False

        time.sleep(0.5)  # Rate limit

    # Test REST poller
    print("\n  Testing REST poller...")
    poller = RestPricePoller(interval=1.0)
    poller.subscribe(test_stocks)
    poller.start()

    time.sleep(3)

    prices = poller.get_prices()
    if prices:
        print(f"  Poller OK: {len(prices)} stocks")
        for code, data in prices.items():
            print(f"    {code}: {data.get('last', 0):,}원")
    else:
        print("  Poller FAILED: no prices")
        poller.stop()
        return False

    poller.stop()
    print("\n  All price tests passed!")
    return True


def show_status():
    """Show current monitoring status with live prices."""
    monitor = MonitorService()
    monitor.load_watchlist()

    status = monitor.get_status()

    print("\n" + "=" * 70)
    print("  AUTO TRADING STATUS")
    print("=" * 70)

    print(f"\n[System]")
    print(f"  Time (KST): {status['current_time_kst']}")
    print(f"  Market Open: {'Yes' if status['market_open'] else 'No'}")
    print(f"  Near Close: {'Yes' if status['near_close'] else 'No'}")

    print_settings(monitor)

    # Get current leverage
    try:
        client = KiwoomTradingClient()
        assets = client.get_net_assets()
        print(f"\n[Account]")
        print(f"  순자산: {assets['net_assets']:,}원")
        print(f"  주식평가: {assets['stock_assets']:,}원")
        print(f"  주식 비중: {assets['leverage_pct']:.1f}%")
    except Exception as e:
        print(f"\n[Account] Failed to load: {e}")

    # Watchlist (현재가는 WebSocket 필요하므로 생략)
    print(f"\n[Watchlist] ({status['watchlist_count']} items)")
    print("-" * 60)
    print(f"{'종목코드':<8} {'종목명':<16} {'매수기준가':>14} {'손절%':>8}")
    print("-" * 60)

    for item in monitor.watchlist:
        ticker = item['ticker']
        target = item['target_price']
        sl = item.get('stop_loss_pct') or monitor.trading_settings.STOP_LOSS_PCT

        # 종목명: Excel에서 가져오거나 API에서 조회
        name = item.get('name', '') or get_stock_name(ticker)
        if len(name) > 12:
            name = name[:11] + ".."

        print(f"{ticker:<8} {name:<16} {target:>14,}원 {sl:>7.1f}%")

    print("-" * 60)

    # Open positions - holdings DB에서 현재가 사용 (API 개별 호출 대신)
    print(f"\n[Open Positions] ({status['open_positions']})")
    positions = monitor.order_service.get_open_positions()

    # holdings에서 현재가 로드
    holdings_prices = load_holdings_prices_from_db()

    if positions:
        print("-" * 90)
        print(f"{'종목코드':<8} {'종목명':<14} {'수량':>8} {'진입가':>12} {'현재가':>12} {'손익률':>10}")
        print("-" * 90)

        for pos in positions:
            symbol = pos['symbol']
            qty = pos['quantity']
            entry = pos['entry_price']

            # 종목명 조회
            name = pos.get('name', '') or get_stock_name(symbol)
            name_display = pad_korean(name[:8] if len(name) > 8 else name, 14)

            # holdings에서 현재가 사용 (positions.current_price 또는 holdings_prices)
            current = pos.get('current_price', 0)
            if current <= 0:
                current = holdings_prices.get(symbol, {}).get('last', 0)

            if current > 0 and entry > 0:
                pnl_pct = ((current - entry) / entry) * 100
                pnl_str = f"{pnl_pct:+.2f}%"
                print(f"{symbol:<8} {name_display} {qty:>8,} {entry:>12,} {current:>12,} {pnl_str:>10}")
            else:
                print(f"{symbol:<8} {name_display} {qty:>8,} {entry:>12,} {'---':>12} {'---':>10}")

        print("-" * 90)
    else:
        print("  No open positions")

    # Today's triggers
    print(f"\n[Today's Triggers] ({status['daily_triggers']})")
    for symbol, trigger in monitor.daily_triggers.items():
        print(f"  {symbol}: {trigger['entry_type']} @ {trigger['entry_time']}")

    print()


def get_display_width(s: str) -> int:
    """Calculate display width (Korean chars = 2, others = 1)."""
    width = 0
    for c in s:
        if '\uac00' <= c <= '\ud7a3':  # Korean syllables
            width += 2
        elif '\u3131' <= c <= '\u318e':  # Korean jamo
            width += 2
        else:
            width += 1
    return width


def pad_korean(s: str, width: int, align: str = 'left') -> str:
    """Pad string for proper alignment with Korean characters."""
    display_width = get_display_width(s)
    padding = width - display_width
    if padding <= 0:
        return s
    if align == 'left':
        return s + ' ' * padding
    elif align == 'right':
        return ' ' * padding + s
    else:  # center
        left_pad = padding // 2
        right_pad = padding - left_pad
        return ' ' * left_pad + s + ' ' * right_pad


def show_live_status(monitor: MonitorService, prices: dict, today_trades: list = None, holdings_prices: dict = None, clear: bool = True):
    """Display live status with real-time prices (watchlist only)."""
    import os
    now = datetime.now()

    # holdings_prices를 fallback으로 사용
    if holdings_prices is None:
        holdings_prices = {}

    # Clear screen on Windows
    if clear:
        os.system('cls' if os.name == 'nt' else 'clear')

    # 보유 종목 정보 (평가손익 표시용)
    positions = {pos['symbol']: pos for pos in monitor.order_service.get_open_positions()}

    # Header with timestamp (shows it's updating)
    print(f"[{now.strftime('%H:%M:%S.%f')[:12]}] Live Monitoring")
    print("=" * 85)

    # Watchlist section (보유 종목은 평가손익 표시)
    print("[Watchlist]")
    print(f"{'코드':<8} {'종목명':<14} {'기준가':>12} {'현재가':>12} {'손익률':>10} {'상태':>8}")
    print("-" * 72)

    for item in monitor.watchlist:
        ticker = item['ticker']
        target = item['target_price']

        name = item.get('name', '') or get_stock_name(ticker)
        name_display = pad_korean(name[:8] if len(name) > 8 else name, 14)

        # poller에서 먼저, 없으면 holdings에서 fallback
        price_data = prices.get(ticker, {})
        current = price_data.get('last', 0)
        if current <= 0:
            current = holdings_prices.get(ticker, {}).get('last', 0)

        if current > 0:
            # 보유 종목이면 평가손익률 표시
            if ticker in positions:
                pos = positions[ticker]
                entry = pos.get('entry_price', 0)
                stop_loss = pos.get('stop_loss_price', 0)
                if entry > 0:
                    pnl_pct = ((current - entry) / entry) * 100
                    pnl_str = f"{pnl_pct:+.2f}%"
                    # 상태: 손절 경고 or 수익/손실
                    if current <= stop_loss:
                        status_str = "<<손절!"
                    elif pnl_pct <= -5:
                        status_str = "손절경고"
                    elif pnl_pct > 0:
                        status_str = "보유▲"
                    else:
                        status_str = "보유▼"
                else:
                    pnl_str = "---"
                    status_str = "보유"
            else:
                # 미보유: 기준가 대비 차이
                diff_pct = ((target - current) / current) * 100
                pnl_str = f"{diff_pct:+.2f}%"
                if diff_pct <= 0:
                    status_str = "돌파!"
                elif diff_pct <= 1:
                    status_str = "임박"
                else:
                    status_str = "대기"

            print(f"{ticker:<8} {name_display} {target:>10,}원 {current:>10,}원 {pnl_str:>10} {status_str:>8}")
        else:
            print(f"{ticker:<8} {name_display} {target:>10,}원 {'---':>10} {'---':>10} {'연결중':>8}")

    print("=" * 72)


def run_trading_loop():
    """Main trading loop with live price monitoring."""
    print_banner()

    if not test_connection():
        print("\nAPI connection failed. Exiting.")
        return

    monitor = MonitorService()
    monitor.load_watchlist()

    print_settings(monitor)

    # 보유종목 동기화: API → holdings 테이블 → positions
    print("\n[Holdings Sync] Syncing holdings from Kiwoom API...")
    try:
        conn = get_connection()
        holdings_count = sync_holdings_from_kiwoom(conn)
        conn.close()
        print(f"  Synced {holdings_count} holdings from API")
    except Exception as e:
        print(f"  [WARN] Holdings sync failed: {e}")

    print("[Holdings Sync] Loading positions from holdings DB...")
    synced = monitor.order_service.sync_positions_from_db(
        stop_loss_pct=monitor.trading_settings.STOP_LOSS_PCT
    )
    existing_positions = monitor.order_service.get_open_positions()
    if existing_positions:
        print(f"  Monitoring {len(existing_positions)} positions for stop loss")
        for pos in existing_positions:
            crd = f" [{pos.get('crd_class', '')}]" if pos.get('crd_class') else ""
            print(f"    - {pos['symbol']}: {pos['quantity']:,}주 @ {pos['entry_price']:,}원 (손절: {pos['stop_loss_price']:,}원){crd}")

    # 오늘 거래 내역 (DB에서 로드 + 실시간 WebSocket 체결 추가)
    print("\n[Today's Trades] Loading from DB...")
    today_trades = load_today_trades_from_db()
    print(f"  Loaded {len(today_trades)} trades from today")

    # holdings 현재가 캐시 (초기 표시용)
    print("\n[Price Cache] Loading current prices from holdings DB...")
    holdings_prices = load_holdings_prices_from_db()
    print(f"  Loaded {len(holdings_prices)} prices from holdings")

    # 체결 알림 콜백 (WebSocket type 00 수신 시 호출)
    def on_order_execution(execution_data: dict):
        """체결 알림 수신 시 positions 재동기화."""
        stock_code = execution_data.get("stock_code", "")
        order_status = execution_data.get("order_status", "")
        order_type = execution_data.get("order_type", "")
        exec_qty = execution_data.get("exec_qty", "")
        exec_price = execution_data.get("exec_price", "")
        buy_sell = execution_data.get("buy_sell", "")

        print(f"\n[EXECUTION] {stock_code} {order_type} 체결: {exec_qty}주")
        trade_logger.log_system_event("EXECUTION", f"{stock_code} {order_type} {exec_qty}주")

        # 오늘 거래 내역에 추가
        side = "매수" if buy_sell == "2" else "매도" if buy_sell == "1" else order_type
        stock_name = get_stock_name(stock_code)
        today_trades.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "symbol": stock_code,
            "name": stock_name,
            "side": side,
            "quantity": int(exec_qty) if exec_qty else 0,
            "price": int(exec_price) if exec_price else 0,
            "status": "체결",
        })

        # API → holdings 테이블 → positions 재동기화
        print("[EXECUTION] Re-syncing holdings from API...")
        try:
            conn = get_connection()
            sync_holdings_from_kiwoom(conn)
            conn.close()
        except Exception as e:
            print(f"[EXECUTION] Holdings sync failed: {e}")

        print("[EXECUTION] Re-syncing positions from DB...")
        monitor.order_service.sync_positions_from_db(
            stop_loss_pct=monitor.trading_settings.STOP_LOSS_PCT
        )

        # 새 포지션이 추가되었으면 poller에도 추가
        new_positions = monitor.order_service.get_open_positions()
        for pos in new_positions:
            symbol = pos['symbol']
            if symbol not in poller.subscribed_stocks:
                print(f"[EXECUTION] Adding {symbol} to price monitor")
                poller.subscribe([symbol])

    if not monitor.watchlist:
        print("\nNo items in watchlist. Please add stocks to watchlist.xlsx")
        return

    print(f"\n[Watchlist] {len(monitor.watchlist)} items loaded")
    for item in monitor.watchlist:
        name = item.get('name', '') or get_stock_name(item['ticker'])
        if name:
            print(f"  - {item['ticker']} ({name}): {item['target_price']:,}원")
        else:
            print(f"  - {item['ticker']}: {item['target_price']:,}원")

    # Initialize price streaming (REST API polling)
    # watchlist + 보유종목 + 오늘 거래 종목 모두 polling 대상
    tickers = [item['ticker'] for item in monitor.watchlist]
    for pos in existing_positions:
        if pos['symbol'] not in tickers:
            tickers.append(pos['symbol'])
    # 오늘 거래한 종목도 추가 (수익률 계산용)
    for trade in today_trades:
        symbol = trade.get('symbol', '')
        if symbol and symbol not in tickers:
            tickers.append(symbol)

    print("\n[Price Streaming] Initializing REST API polling...")

    # Use REST API polling (ka10001) for real-time prices
    # WebSocket 0A type only works for 주식기세 (rare events), not regular price updates
    poller = RestPricePoller(interval=1.0)
    poller.subscribe(tickers)
    poller.start()
    price_source = poller

    print(f"  Polling {len(tickers)} stocks every 1 second")

    # WebSocket for order execution notifications (type 00)
    # 체결 알림 수신 → positions 재동기화
    print("\n[Execution Monitor] Initializing WebSocket for order notifications...")
    ws_client = KiwoomWebSocketClient(
        on_order_execution=on_order_execution,
        subscribe_executions=True
    )
    ws_client.start()
    if ws_client.authenticated:
        print("  WebSocket connected - monitoring order executions")
    else:
        print("  WebSocket connection pending (will retry)")
        # 연결 실패해도 REST polling은 계속 동작

    print("\n" + "=" * 70)
    print("Starting trading loop... (Ctrl+C to stop)")
    print("=" * 70)

    trade_logger.log_system_event("START", f"watchlist={len(monitor.watchlist)} items")

    # Monitoring intervals
    STATUS_INTERVAL = 3  # Show status every 3 seconds (clear & refresh)
    CHECK_INTERVAL = 1   # Check prices every 1 second

    last_date = None
    last_status_time = 0

    try:
        while True:
            now = datetime.now()
            today = now.date()
            current_time = time.time()

            # Reset daily triggers on new day
            if last_date != today:
                monitor.reset_daily_triggers()
                monitor.load_watchlist()  # Reload watchlist
                last_date = today

            # Get current prices
            prices = price_source.get_prices()

            # Show live status periodically
            if current_time - last_status_time >= STATUS_INTERVAL:
                show_live_status(monitor, prices, today_trades, holdings_prices)
                last_status_time = current_time

            # Check market status
            status = monitor.get_status()

            if status["market_open"]:
                # Run monitoring cycle
                result = monitor.run_monitoring_cycle()

                # Log activity
                if result.get("reloaded"):
                    print(f"[{now.strftime('%H:%M:%S')}] RELOADED: watchlist & settings")
                    print_settings(monitor)

                if result["entries"]:
                    for entry in result["entries"]:
                        print(f"[{now.strftime('%H:%M:%S')}] ENTRY: {entry['symbol']} ({entry['type']})")
                        today_trades.append({
                            "time": now.strftime("%H:%M:%S"),
                            "symbol": entry['symbol'],
                            "name": get_stock_name(entry['symbol']),
                            "side": "매수",
                            "quantity": entry.get('quantity', 0),
                            "price": entry.get('price', 0),
                            "status": f"주문({entry['type']})",
                        })

                if result["stop_losses"]:
                    for symbol in result["stop_losses"]:
                        print(f"[{now.strftime('%H:%M:%S')}] STOP LOSS: {symbol}")
                        today_trades.append({
                            "time": now.strftime("%H:%M:%S"),
                            "symbol": symbol,
                            "name": get_stock_name(symbol),
                            "side": "매도",
                            "quantity": 0,
                            "price": 0,
                            "status": "손절주문",
                        })

                if result["close_actions"]:
                    for symbol, action in result["close_actions"].items():
                        print(f"[{now.strftime('%H:%M:%S')}] CLOSE: {symbol} -> {action}")
                        side = "매수" if action == "pyramid" else "매도"
                        today_trades.append({
                            "time": now.strftime("%H:%M:%S"),
                            "symbol": symbol,
                            "name": get_stock_name(symbol),
                            "side": side,
                            "quantity": 0,
                            "price": 0,
                            "status": f"종가({action})",
                        })

            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        print("\n\nTrading loop stopped by user.")
        trade_logger.log_system_event("STOP", "user interrupt")

    # Cleanup
    poller.stop()
    ws_client.stop()

    print("\n[Final Status]")
    show_status()


def main():
    """Main entry point."""
    if "--test" in sys.argv:
        test_connection()
    elif "--price-test" in sys.argv:
        test_price_api()
    elif "--status" in sys.argv:
        show_status()
    else:
        run_trading_loop()


if __name__ == "__main__":
    main()
