"""
Price service for real-time price monitoring from Kiwoom API.

Uses REST API polling (ka10001) for current prices.
- WebSocket 0A type (주식기세) only works for rare events (price changes without execution)
- REST API polling is more reliable for regular price monitoring

Usage:
    poller = RestPricePoller(interval=1.0)
    poller.subscribe(["005930", "000660"])
    poller.start()

    # Get prices
    prices = poller.get_prices()
    # {"005930": {"last": 164300, ...}, "000660": {"last": 899000, ...}}

    poller.stop()
"""

import json
import threading
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

import websocket

from config.settings import Settings
from services.kiwoom_service import KiwoomTradingClient

KST = ZoneInfo("Asia/Seoul")

# 0A (주식기세) 필드 코드 매핑
FIELD_CODES = {
    "10": "last",       # 현재가
    "27": "ask",        # (최우선)매도호가
    "28": "bid",        # (최우선)매수호가
    "9001": "stock_code",  # 종목코드
    "302": "name",      # 종목명
}


class KiwoomWebSocketClient:
    """
    WebSocket client for real-time price streaming and order execution notifications.

    Usage:
        client = KiwoomWebSocketClient()
        client.subscribe(["005930", "000660"])
        client.start()

        # Get current prices
        prices = client.get_prices()

        # Stop
        client.stop()
    """

    def __init__(
        self,
        on_price_update: Optional[Callable] = None,
        on_order_execution: Optional[Callable] = None,
        subscribe_executions: bool = False
    ):
        self.settings = Settings()
        self.ws_url = self.settings.SOCKET_URL
        self.api_client = KiwoomTradingClient()

        self.ws: Optional[websocket.WebSocketApp] = None
        self.ws_thread: Optional[threading.Thread] = None
        self.running = False
        self.connected = False
        self.authenticated = False  # 인증 완료 여부

        # Subscribed stock codes
        self.subscribed_stocks: List[str] = []

        # Real-time prices: {stock_code: {price_data}}
        self.prices: Dict[str, dict] = {}
        self.prices_lock = threading.Lock()

        # Callback for price updates
        self.on_price_update = on_price_update

        # Callback for order executions (type 00)
        self.on_order_execution = on_order_execution
        self.subscribe_executions = subscribe_executions

        # Last update times
        self.last_update: Dict[str, datetime] = {}

        # Group number for subscriptions
        self.grp_no = "1"

    def _get_auth_token(self) -> str:
        """Get authentication token."""
        return self.api_client.get_access_token()

    def _on_open(self, ws):
        """WebSocket connection opened."""
        print(f"[WS] Connected to {self.ws_url}")
        self.connected = True
        self.authenticated = False

        # 연결 후 LOGIN 메시지 전송
        self._send_login()

    def _send_login(self):
        """Send LOGIN message for authentication."""
        if not self.ws or not self.connected:
            return

        token = self._get_auth_token()
        login_msg = {
            "trnm": "LOGIN",
            "token": token
        }

        try:
            self.ws.send(json.dumps(login_msg))
            print("[WS] LOGIN message sent")
        except Exception as e:
            print(f"[WS] LOGIN send error: {e}")

    def _on_login_success(self):
        """Called after successful LOGIN authentication."""
        self.authenticated = True
        print("[WS] Authentication successful")

        # 체결 알림(00) 구독 - item을 빈 문자열로 하면 모든 체결 알림 수신
        if self.subscribe_executions:
            print("[WS] Subscribing to order execution notifications (type 00)...")
            self._send_execution_subscribe()

        # 인증 완료 후 가격 구독 전송
        if self.subscribed_stocks:
            print(f"[WS] Subscribing to {len(self.subscribed_stocks)} stocks...")
            self._send_subscribe_batch(self.subscribed_stocks)

    def _on_message(self, ws, message):
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)

            trnm = data.get("trnm", "")
            return_code = data.get("return_code")

            # 디버그: 모든 메시지 출력
            if trnm not in ("PING",):  # PING 제외
                print(f"[WS DEBUG] trnm={trnm}, data={str(data)[:200]}")

            # LOGIN 응답 처리
            if trnm == "LOGIN":
                if return_code == 0:
                    self._on_login_success()
                else:
                    print(f"[WS] LOGIN error: {data.get('return_msg', 'Unknown')}")
                return

            # PING 메시지 처리 - 그대로 echo back
            if trnm == "PING":
                try:
                    self.ws.send(json.dumps(data))
                except Exception as e:
                    print(f"[WS] PING echo error: {e}")
                return

            # 구독(REG) 응답 처리
            if trnm == "REG" and return_code is not None:
                if return_code == 0:
                    print(f"[WS] Registration successful")
                else:
                    print(f"[WS] Registration error: {data.get('return_msg', 'Unknown')}")
                return

            # Real-time data (실시간 데이터)
            if trnm == "REAL":
                print(f"[WS] REAL data received: {str(data)[:300]}")
                self._handle_realtime_data(data)

        except json.JSONDecodeError:
            print(f"[WS] Invalid JSON: {message[:100]}")
        except Exception as e:
            print(f"[WS] Message handling error: {e}")

    def _handle_realtime_data(self, data: dict):
        """Handle real-time data from WebSocket."""
        data_list = data.get("data", [])

        for item in data_list:
            item_type = item.get("type", "")
            stock_code = item.get("item", "")
            values = item.get("values", {})

            if item_type == "0A" and stock_code:
                self._handle_price_update(stock_code, values)
            elif item_type == "00":
                self._handle_order_execution(stock_code, values)

    def _handle_price_update(self, stock_code: str, values: dict):
        """Handle Type 0A price update."""
        def parse_price(val):
            if not val:
                return 0
            val_str = str(val).replace("+", "").replace("-", "")
            try:
                return int(val_str)
            except ValueError:
                return 0

        price_data = {
            "stock_code": stock_code,
            "last": parse_price(values.get("10")),      # 현재가
            "ask": parse_price(values.get("27")),       # 매도호가
            "bid": parse_price(values.get("28")),       # 매수호가
            "name": values.get("302", ""),              # 종목명
            "updated_at": datetime.now(KST).isoformat(),
        }

        with self.prices_lock:
            # 기존 데이터가 있으면 업데이트만
            if stock_code in self.prices:
                self.prices[stock_code].update(price_data)
            else:
                self.prices[stock_code] = price_data
            self.last_update[stock_code] = datetime.now(KST)

        # Callback
        if self.on_price_update:
            self.on_price_update(stock_code, price_data)

    def _handle_order_execution(self, stock_code: str, values: dict):
        """Handle Type 00 order execution notification."""
        # 주문체결 알림 처리
        order_no = values.get("9203", "")
        order_status = values.get("913", "")  # 접수, 체결, 확인, 취소, 거부
        exec_price = values.get("910", "")
        exec_qty = values.get("911", "")
        order_type = values.get("905", "")  # 매도, 매수, 매도정정 등
        buy_sell = values.get("907", "")  # 1:매도, 2:매수
        stock_name = values.get("302", "")

        # 상태별 로그 메시지 구분
        status_label = {
            "접수": "주문접수",
            "체결": "주문체결",
            "확인": "주문확인",
            "취소": "주문취소",
            "거부": "주문거부",
        }.get(order_status, f"주문{order_status}")

        print(f"[WS] {status_label}: {stock_code} ({stock_name}) | {order_type} | "
              f"price={exec_price} qty={exec_qty} order_no={order_no}")

        # 체결 완료 시 콜백 호출 (재동기화 트리거)
        if order_status == "체결" and self.on_order_execution:
            execution_data = {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "order_no": order_no,
                "order_status": order_status,
                "order_type": order_type,
                "buy_sell": buy_sell,  # 1:매도, 2:매수
                "exec_price": exec_price,
                "exec_qty": exec_qty,
                "timestamp": datetime.now(KST).isoformat(),
            }
            try:
                self.on_order_execution(execution_data)
            except Exception as e:
                print(f"[WS] Order execution callback error: {e}")

    def _on_error(self, ws, error):
        """WebSocket error handler."""
        print(f"[WS] Error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        """WebSocket connection closed."""
        print(f"[WS] Connection closed: {close_status_code} - {close_msg}")
        self.connected = False

        # Auto-reconnect if still running
        if self.running:
            print("[WS] Reconnecting in 5 seconds...")
            time.sleep(5)
            self._connect()

    def _send_execution_subscribe(self):
        """Subscribe to order execution notifications (type 00)."""
        if not self.ws or not self.connected:
            return

        # type 00 (주문체결) - item을 빈 문자열로 하면 모든 체결 알림 수신
        request = {
            "trnm": "REG",
            "grp_no": self.grp_no,
            "refresh": "1",
            "data": [
                {
                    "item": [""],  # 빈 문자열 = 모든 주문 체결 알림
                    "type": ["00"],  # 주문체결
                }
            ]
        }

        try:
            msg = json.dumps(request)
            print(f"[WS] Sending execution REG: {msg}")
            self.ws.send(msg)
            print("[WS] Subscribed to order execution notifications")
        except Exception as e:
            print(f"[WS] Execution subscribe error: {e}")

    def _send_subscribe_batch(self, stock_codes: List[str]):
        """Send batch subscription request for multiple stocks."""
        if not self.ws or not self.connected:
            return

        # Kiwoom WebSocket 등록 요청 형식
        request = {
            "trnm": "REG",
            "grp_no": self.grp_no,
            "refresh": "1",  # 기존 등록 유지
            "data": [
                {
                    "item": stock_codes,
                    "type": ["0A"],  # 주식기세
                }
            ]
        }

        try:
            msg = json.dumps(request)
            print(f"[WS] Sending REG: {msg}")
            self.ws.send(msg)
            print(f"[WS] Subscribed to {len(stock_codes)} stocks: {stock_codes}")
        except Exception as e:
            print(f"[WS] Subscribe error: {e}")

    def _send_unsubscribe_batch(self, stock_codes: List[str]):
        """Send batch unsubscription request."""
        if not self.ws or not self.connected:
            return

        request = {
            "trnm": "REMOVE",
            "grp_no": self.grp_no,
            "data": [
                {
                    "item": stock_codes,
                    "type": ["0A"],
                }
            ]
        }

        try:
            self.ws.send(json.dumps(request))
            print(f"[WS] Unsubscribed from {len(stock_codes)} stocks")
        except Exception as e:
            print(f"[WS] Unsubscribe error: {e}")

    def _connect(self):
        """Establish WebSocket connection."""
        self.authenticated = False

        # WebSocket 연결 (인증은 LOGIN 메시지로 처리)
        self.ws = websocket.WebSocketApp(
            self.ws_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        self.ws.run_forever()

    def subscribe(self, stock_codes: List[str]):
        """Add stocks to subscription list."""
        for code in stock_codes:
            if code not in self.subscribed_stocks:
                self.subscribed_stocks.append(code)

        # If already authenticated, subscribe immediately
        if self.authenticated:
            self._send_subscribe_batch(stock_codes)

    def unsubscribe(self, stock_codes: List[str]):
        """Remove stocks from subscription list."""
        codes_to_remove = []
        for code in stock_codes:
            if code in self.subscribed_stocks:
                self.subscribed_stocks.remove(code)
                codes_to_remove.append(code)

        # If connected, unsubscribe
        if self.connected and codes_to_remove:
            self._send_unsubscribe_batch(codes_to_remove)

        # Remove from prices
        with self.prices_lock:
            for code in codes_to_remove:
                self.prices.pop(code, None)

    def start(self):
        """Start WebSocket connection in background thread."""
        if self.running:
            return

        self.running = True
        self.authenticated = False
        self.ws_thread = threading.Thread(target=self._connect, daemon=True)
        self.ws_thread.start()

        # Wait for connection and authentication
        timeout = 10
        start_time = time.time()
        while not self.authenticated and time.time() - start_time < timeout:
            time.sleep(0.1)

        if self.authenticated:
            print("[WS] Started successfully (authenticated)")
        elif self.connected:
            print("[WS] Connected but authentication pending")
        else:
            print("[WS] Connection timeout")

    def stop(self):
        """Stop WebSocket connection."""
        self.running = False

        if self.ws:
            self.ws.close()

        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=5)

        self.connected = False
        print("[WS] Stopped")

    def get_price(self, stock_code: str) -> Optional[dict]:
        """Get current price for a stock."""
        with self.prices_lock:
            return self.prices.get(stock_code)

    def get_prices(self) -> Dict[str, dict]:
        """Get all current prices."""
        with self.prices_lock:
            return self.prices.copy()

    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self.connected


# REST API polling for real-time prices
class RestPricePoller:
    """
    Price poller using REST API (ka10001).
    Polls individual stock prices via get_stock_price().
    """

    def __init__(self, interval: float = 1.0):
        self.client = KiwoomTradingClient()
        self.interval = interval
        self.running = False
        self.poll_thread: Optional[threading.Thread] = None

        self.subscribed_stocks: List[str] = []
        self.prices: Dict[str, dict] = {}
        self.prices_lock = threading.Lock()

        self.on_price_update: Optional[Callable] = None

    def _poll_prices(self):
        """Poll prices for subscribed stocks."""
        while self.running:
            try:
                for stock_code in self.subscribed_stocks:
                    if not self.running:
                        break

                    # REST API로 개별 종목 시세 조회
                    price_data = self.client.get_stock_price(stock_code)
                    price_data["updated_at"] = datetime.now(KST).isoformat()

                    with self.prices_lock:
                        self.prices[stock_code] = price_data

                    if self.on_price_update and price_data.get("last", 0) > 0:
                        self.on_price_update(stock_code, price_data)

            except Exception as e:
                print(f"[POLL] Error fetching prices: {e}")

            time.sleep(self.interval)

    def subscribe(self, stock_codes: List[str]):
        """Add stocks to poll list."""
        for code in stock_codes:
            if code not in self.subscribed_stocks:
                self.subscribed_stocks.append(code)

    def start(self):
        """Start polling."""
        if self.running:
            return

        self.running = True
        self.poll_thread = threading.Thread(target=self._poll_prices, daemon=True)
        self.poll_thread.start()
        print("[POLL] Started REST API price polling (holdings only)")

    def stop(self):
        """Stop polling."""
        self.running = False
        if self.poll_thread and self.poll_thread.is_alive():
            self.poll_thread.join(timeout=5)
        print("[POLL] Stopped")

    def get_price(self, stock_code: str) -> Optional[dict]:
        """Get current price for a stock."""
        with self.prices_lock:
            return self.prices.get(stock_code)

    def get_prices(self) -> Dict[str, dict]:
        """Get all current prices."""
        with self.prices_lock:
            return self.prices.copy()

    def is_connected(self) -> bool:
        """Always returns True for REST poller."""
        return self.running
