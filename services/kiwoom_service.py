"""
Kiwoom API service for fetching account trade history and holdings.
"""

from datetime import date, datetime
from typing import List, Dict, Any
import requests
import pymysql
from decimal import Decimal

from config.settings import Settings


class KiwoomAPIClient:
    """Client for Kiwoom eFriend Plus API."""

    # 토큰 유효기간: 24시간, 12시간마다 갱신
    TOKEN_REFRESH_HOURS = 12

    def __init__(self):
        self.settings = Settings()
        self.base_url = self.settings.BASE_URL
        self.app_key = self.settings.APP_KEY
        self.secret_key = self.settings.SECRET_KEY
        self.acnt_api_id = self.settings.ACNT_API_ID
        self.access_token = None
        self.token_issued_at = None  # 토큰 발급 시간

    def _is_token_expired(self) -> bool:
        """Check if token needs refresh (12 hours elapsed)."""
        if not self.token_issued_at:
            return True
        elapsed = datetime.now() - self.token_issued_at
        return elapsed.total_seconds() >= self.TOKEN_REFRESH_HOURS * 3600

    def get_access_token(self) -> str:
        """
        Get access token for API authentication.
        Automatically refreshes if 12 hours have passed.

        Returns:
            Access token string
        """
        if self.access_token and not self._is_token_expired():
            return self.access_token

        # 토큰 만료 또는 없음 - 새로 발급
        if self.access_token and self._is_token_expired():
            print(f"[TOKEN] Token expired (12h), refreshing...")

        url = f"{self.base_url}/oauth2/token"
        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.secret_key,
        }

        try:
            response = requests.post(url, json=data)
            response.raise_for_status()
            self.access_token = response.json()["token"]
            self.token_issued_at = datetime.now()
            print(f"[TOKEN] New access token acquired (valid for 24h, refresh in 12h)")
            return self.access_token
        except Exception as e:
            print(f"✗ Failed to get access token: {e}")
            raise

    def refresh_token(self) -> str:
        """
        Force refresh the access token.

        Returns:
            New access token string
        """
        self.access_token = None
        self.token_issued_at = None
        return self.get_access_token()

    def _api_request(self, method: str, url: str, headers: dict, json: dict = None, timeout: int = 10, retry_on_token_error: bool = True) -> requests.Response:
        """
        Make API request with automatic token refresh on expiry.

        Args:
            method: HTTP method (GET, POST)
            url: API URL
            headers: Request headers
            json: Request body
            timeout: Request timeout
            retry_on_token_error: Whether to retry on token error

        Returns:
            Response object
        """
        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers, timeout=timeout)
            else:
                response = requests.post(url, headers=headers, json=json, timeout=timeout)

            # Check for token expiry error in response
            if response.status_code == 200:
                result = response.json()
                return_code = result.get("return_code")
                return_msg = result.get("return_msg", "")

                # Token expired: [8005:Token이 유효하지 않습니다]
                if return_code == 8005 or "8005" in str(return_msg) or "Token" in return_msg and "유효" in return_msg:
                    if retry_on_token_error:
                        print(f"[TOKEN] Token expired, refreshing...")
                        new_token = self.refresh_token()
                        headers['Authorization'] = f'Bearer {new_token}'
                        return self._api_request(method, url, headers, json, timeout, retry_on_token_error=False)
                    else:
                        raise Exception(f"Token refresh failed: {return_msg}")

            response.raise_for_status()
            return response

        except requests.exceptions.RequestException as e:
            # Check if error message contains token expiry
            error_str = str(e)
            if retry_on_token_error and ("8005" in error_str or "Token" in error_str):
                print(f"[TOKEN] Token error detected, refreshing...")
                new_token = self.refresh_token()
                headers['Authorization'] = f'Bearer {new_token}'
                return self._api_request(method, url, headers, json, timeout, retry_on_token_error=False)
            raise

    def get_account_trade_history(self, start_date: str = None) -> List[Dict[str, Any]]:
        """
        Fetch account trade history from Kiwoom API.

        Args:
            start_date: Start date in YYYYMMDD format. If None, fetches recent trades.

        Returns:
            List of trade records
        """
        token = self.get_access_token()

        # API endpoint for account trade history (kt00007)
        url = f"{self.base_url}/api/dostk/acnt"

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'api-id': 'kt00007',
        }

        body = {
            "ord_dt": start_date,  # 주문일자 (YYYYMMDD)
            "qry_tp": "4",  # 조회구분
            "stk_bond_tp": "0",  # 주식채권구분
            "sell_tp": "0",  # 매도구분
            "stk_cd": "",  # 종목코드
            "fr_ord_no": "",
            "dmst_stex_tp": "%",  # 국내외구분
        }

        all_trades = []
        cont_yn = "N"
        next_key = ""

        try:
            while True:
                # 연속 조회 헤더 설정
                if cont_yn == "Y":
                    headers["cont-yn"] = "Y"
                    headers["next-key"] = next_key

                response = requests.post(url, headers=headers, json=body, timeout=10)
                response.raise_for_status()
                result = response.json()

                # Parse trade records
                trades = result.get("acnt_ord_cntr_prps_dtl", [])
                for item in trades:
                    # Use the query date (start_date) as trade_date
                    # API response may not have reliable date field
                    trade_date_str = start_date if start_date else date.today().strftime("%Y%m%d")

                    trade = {
                        "ord_no": item.get("ord_no"),
                        "stk_cd": item.get("stk_cd"),
                        "stk_nm": item.get("stk_nm", ""),
                        "io_tp_nm": item.get("io_tp_nm", ""),
                        "crd_class": "CREDIT" if item.get("loan_dt") else "CASH",
                        "trade_date": self._parse_date(trade_date_str),
                        "ord_tm": item.get("ord_tm", ""),
                        "cntr_qty": int(item.get("cntr_qty", 0)),
                        "cntr_uv": int(item.get("cntr_uv", 0)),
                        "loan_dt": item.get("loan_dt"),
                    }
                    all_trades.append(trade)

                # Check for continuation
                cont_yn = response.headers.get("cont-yn", "N")
                next_key = response.headers.get("next-key", "")

                if cont_yn != "Y":
                    break

            return all_trades

        except Exception as e:
            print(f"✗ Failed to fetch trade history: {e}")
            raise

    def _is_nxt_only_hours(self) -> bool:
        """
        Check if we're in NXT-only trading hours (KRX closed, NXT open).

        Returns True during:
        - 8:00 ~ 9:00 (NXT morning before KRX opens)
        - 15:40 ~ 20:00 (NXT afternoon/evening after KRX closes)
        """
        from datetime import time as dt_time
        from zoneinfo import ZoneInfo

        KST = ZoneInfo("Asia/Seoul")
        now_kst = datetime.now(KST)

        if now_kst.weekday() >= 5:
            return False

        current_time = now_kst.time()

        # NXT morning session (before KRX opens): 8:00 ~ 9:00
        nxt_morning = dt_time(8, 0) <= current_time < dt_time(9, 0)

        # NXT afternoon/evening session (after KRX closes): 15:40 ~ 20:00
        nxt_afternoon = dt_time(15, 40) <= current_time < dt_time(20, 0)

        return nxt_morning or nxt_afternoon

    def get_holdings(self, market_type: str = "AUTO") -> Dict[str, Any]:
        """
        Fetch current holdings from Kiwoom API with continuous query support.

        Args:
            market_type: "KRX", "NXT", or "AUTO" (auto-detect based on time)

        Returns:
            Full holdings data from API response (merged from all pages)
        """
        token = self.get_access_token()

        # Auto-detect market type based on current time
        if market_type == "AUTO":
            market_type = "NXT" if self._is_nxt_only_hours() else "KRX"

        # API endpoint for account status (kt00004)
        url = f"{self.base_url}/api/dostk/acnt"

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'api-id': 'kt00004',
        }

        body = {
            "qry_tp": "1",  # 조회구분
            "dmst_stex_tp": market_type,  # 국내외구분 (KRX or NXT)
        }

        try:
            all_holdings = []
            cont_yn = "N"
            next_key = ""
            result = None

            while True:
                # 연속 조회 헤더 설정
                if cont_yn == "Y":
                    headers["cont-yn"] = "Y"
                    headers["next-key"] = next_key

                response = requests.post(url, headers=headers, json=body, timeout=10)
                response.raise_for_status()
                result_page = response.json()

                # First page: save account summary data
                if not result:
                    result = result_page

                # Accumulate holdings from stk_acnt_evlt_prst
                holdings = result_page.get("stk_acnt_evlt_prst", [])
                all_holdings.extend(holdings)

                # Check for continuation
                cont_yn = response.headers.get("cont-yn", "N")
                next_key = response.headers.get("next-key", "")

                if cont_yn != "Y":
                    break

            # Update result with all accumulated holdings
            result["stk_acnt_evlt_prst"] = all_holdings
            return result

        except Exception as e:
            print(f"✗ Failed to fetch holdings: {e}")
            raise

    def get_account_summary(self) -> Dict[str, Any]:
        """
        Fetch account summary from Kiwoom API with continuous query support.

        Returns:
            Full account summary data including all fields
        """
        token = self.get_access_token()

        # API endpoint for account status (kt00004)
        url = f"{self.base_url}/api/dostk/acnt"

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'api-id': 'kt00004',
        }

        body = {
            "qry_tp": "1",  # 조회구분
            "dmst_stex_tp": "KRX",  # 국내외구분
        }

        try:
            all_holdings = []
            cont_yn = "N"
            next_key = ""
            result = None

            while True:
                # 연속 조회 헤더 설정
                if cont_yn == "Y":
                    headers["cont-yn"] = "Y"
                    headers["next-key"] = next_key

                response = requests.post(url, headers=headers, json=body, timeout=10)
                response.raise_for_status()
                result_page = response.json()

                # First page: save account summary data
                if not result:
                    result = result_page

                # Accumulate holdings from stk_acnt_evlt_prst
                holdings = result_page.get("stk_acnt_evlt_prst", [])
                all_holdings.extend(holdings)

                # Check for continuation
                cont_yn = response.headers.get("cont-yn", "N")
                next_key = response.headers.get("next-key", "")

                if cont_yn != "Y":
                    break

            # Update result with all accumulated holdings
            result["stk_acnt_evlt_prst"] = all_holdings
            return result

        except Exception as e:
            print(f"✗ Failed to fetch account summary: {e}")
            raise

    def get_daily_account_status(self) -> Dict[str, Any]:
        """
        Fetch daily account status including cash flows from Kiwoom API.
        Uses kt00017 API to get deposit/withdrawal info.

        Returns:
            Full daily account status including ina_amt (deposit) and outa (withdrawal)
        """
        token = self.get_access_token()

        # API endpoint for daily account status (kt00017)
        url = f"{self.base_url}/api/dostk/acnt"

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'api-id': 'kt00017',
        }

        body = {
            "qry_tp": "1",  # 조회구분
            "dmst_stex_tp": "KRX",  # 국내외구분
        }

        try:
            response = requests.post(url, headers=headers, json=body, timeout=10)
            response.raise_for_status()
            result = response.json()

            return result

        except Exception as e:
            print(f"✗ Failed to fetch daily account status: {e}")
            raise

    def get_daily_balance(self, target_date: date = None) -> Dict[str, Any]:
        """
        Fetch daily balance and return data for a specific date.
        Uses ka01690 API which supports historical queries via dt parameter.

        Args:
            target_date: Date to query (defaults to today)

        Returns:
            Full daily balance data including day_stk_asst (추정자산) and day_bal_rt array
        """
        token = self.get_access_token()

        # API endpoint for daily balance (ka01690)
        url = f"{self.base_url}/api/dostk/acnt"

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'api-id': 'ka01690',
        }

        if target_date is None:
            target_date = date.today()

        # Format date as YYYYMMDD
        dt_str = target_date.strftime("%Y%m%d")

        body = {
            "qry_dt": dt_str,  # 조회일자 (YYYYMMDD)
            "dmst_stex_tp": "KRX",  # 국내외구분
        }

        try:
            response = requests.post(url, headers=headers, json=body, timeout=10)
            response.raise_for_status()
            result = response.json()

            return result

        except Exception as e:
            print(f"✗ Failed to fetch daily balance for {target_date}: {e}")
            raise

    def get_daily_cash_flow(self, target_date: date = None) -> Dict[str, Any]:
        """
        Fetch daily cash flow (deposits/withdrawals) for a specific date.
        Uses kt00016 API (일별계좌수익률상세현황요청).

        Args:
            target_date: Date to query (defaults to today)

        Returns:
            Cash flow data including termin_tot_trns (입금) and termin_tot_pymn (출금)
        """
        token = self.get_access_token()

        # API endpoint for daily cash flow (kt00016)
        url = f"{self.base_url}/api/dostk/acnt"

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'api-id': 'kt00016',
        }

        if target_date is None:
            target_date = date.today()

        # Format date as YYYYMMDD
        dt_str = target_date.strftime("%Y%m%d")

        # Query single day by setting both fr_dt and to_dt to the same date
        body = {
            "fr_dt": dt_str,  # 평가시작일
            "to_dt": dt_str,  # 평가종료일
        }

        try:
            response = requests.post(url, headers=headers, json=body, timeout=10)
            response.raise_for_status()
            result = response.json()

            return result

        except Exception as e:
            print(f"✗ Failed to fetch daily cash flow for {target_date}: {e}")
            raise

    def get_market_index(self, market_type: str = "0", index_code: str = "001") -> Dict[str, Any]:
        """
        Fetch market index data (KOSPI/KOSDAQ) from Kiwoom API.
        Uses ka20009 API (업종현재가일별요청).

        Args:
            market_type: Market type ("0": KOSPI, "1": KOSDAQ, "2": KOSPI200)
            index_code: Index code ("001": KOSPI종합, "101": KOSDAQ종합)

        Returns:
            Dict containing current index value and daily history
        """
        token = self.get_access_token()

        # API endpoint for market index (ka20009) - 업종
        url = f"{self.base_url}/api/dostk/sect"

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'api-id': 'ka20009',
        }

        body = {
            "mrkt_tp": market_type,  # 시장구분 (0:코스피, 1:코스닥, 2:코스피200)
            "inds_cd": index_code,   # 업종코드 (001:종합(KOSPI), 101:종합(KOSDAQ))
        }

        all_daily_data = []
        cont_yn = "N"
        next_key = ""
        result = None
        max_pages = 50  # 무한루프 방지
        cutoff_date = date(2025, 12, 10)  # 이 날짜 이전 데이터가 나오면 종료

        try:
            for _ in range(max_pages):
                # 연속 조회 헤더 설정
                if cont_yn == "Y":
                    headers["cont-yn"] = "Y"
                    headers["next-key"] = next_key

                response = requests.post(url, headers=headers, json=body, timeout=30)
                response.raise_for_status()
                result_page = response.json()

                # Check for API error
                if result_page.get("return_code") != 0:
                    print(f"  API error: {result_page.get('return_msg', 'Unknown error')}")
                    break

                # First page: save base data
                if not result:
                    result = result_page

                # Accumulate daily data from inds_cur_prc_daly_rept
                daily_data = result_page.get("inds_cur_prc_daly_rept", [])

                # Check if we've reached data before cutoff date
                reached_cutoff = False
                for item in daily_data:
                    dt_str = item.get("dt_n")
                    if dt_str:
                        item_date = self._parse_date(dt_str)
                        if item_date < cutoff_date:
                            reached_cutoff = True
                            break
                        all_daily_data.append(item)

                if reached_cutoff:
                    break

                # Check for continuation
                cont_yn = response.headers.get("cont-yn", "N")
                next_key = response.headers.get("next-key", "")

                if cont_yn != "Y" or not next_key:
                    break

            # Update result with all accumulated daily data
            if result:
                result["inds_cur_prc_daly_rept"] = all_daily_data

            return result

        except Exception as e:
            print(f"✗ Failed to fetch market index: {e}")
            raise

    @staticmethod
    def _parse_price(price_str: str) -> float:
        """Parse price string with sign prefix to float (absolute value)."""
        if not price_str:
            return 0.0
        try:
            # Remove sign prefix (+/-) and convert to float
            return abs(float(price_str.replace('+', '').replace('-', '')))
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _parse_signed_value(value_str: str) -> float:
        """Parse signed value string to float (preserving sign)."""
        if not value_str:
            return 0.0
        try:
            return float(value_str)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _parse_date(date_str: str) -> date:
        """Parse date string in YYYYMMDD format to date object."""
        if not date_str or len(date_str) != 8:
            return date.today()
        try:
            return date(
                int(date_str[:4]),
                int(date_str[4:6]),
                int(date_str[6:8]),
            )
        except ValueError:
            return date.today()


def sync_trade_history_from_kiwoom(
    conn: pymysql.connections.Connection,
    start_date: str = "20251211",
) -> int:
    """
    Fetch trade history from Kiwoom API and save to asset database.

    Args:
        conn: Database connection
        start_date: Start date in YYYYMMDD format (default: 20251211)

    Returns:
        Number of records synced
    """
    print(f"Fetching trade history from Kiwoom API (from {start_date})...")

    try:
        from datetime import datetime, timedelta
        import time

        client = KiwoomAPIClient()

        # Parse start date
        start_dt = datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.today()

        # Fetch trades for each day from start_date to today
        all_trades = []
        current_dt = start_dt

        while current_dt <= end_dt:
            date_str = current_dt.strftime("%Y%m%d")
            print(f"  Fetching trades for {date_str}...")

            # Retry logic for rate limiting
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    daily_trades = client.get_account_trade_history(start_date=date_str)
                    if daily_trades:
                        all_trades.extend(daily_trades)
                        print(f"    [OK] Found {len(daily_trades)} trades")
                    break  # Success, exit retry loop
                except Exception as e:
                    if "429" in str(e):
                        wait_time = (attempt + 1) * 2  # 2, 4, 6 seconds
                        print(f"    [RATE LIMIT] Waiting {wait_time}s before retry...")
                        time.sleep(wait_time)
                        if attempt == max_retries - 1:
                            print(f"    [WARN] Failed after {max_retries} retries: {e}")
                    else:
                        print(f"    [WARN] Failed to fetch trades for {date_str}: {e}")
                        break  # Non-rate-limit error, don't retry

            current_dt += timedelta(days=1)
            time.sleep(0.5)  # Rate limit: 0.5s delay between requests

        if not all_trades:
            print("No trade history found from Kiwoom API")
            return 0

        # Insert new records (IGNORE duplicates - idempotent)
        insert_sql = """
            INSERT IGNORE INTO account_trade_history (
                ord_no, stk_cd, stk_nm, io_tp_nm, crd_class,
                trade_date, ord_tm, cntr_qty, cntr_uv, loan_dt
            )
            VALUES (
                %(ord_no)s, %(stk_cd)s, %(stk_nm)s, %(io_tp_nm)s, %(crd_class)s,
                %(trade_date)s, %(ord_tm)s, %(cntr_qty)s, %(cntr_uv)s, %(loan_dt)s
            )
        """

        inserted_count = 0
        with conn.cursor() as cur:
            for trade in all_trades:
                cur.execute(insert_sql, trade)
                inserted_count += cur.rowcount  # Only counts actually inserted rows

        conn.commit()
        print(f"[OK] Inserted {inserted_count} new trade records from Kiwoom API")
        return inserted_count

    except Exception as e:
        print(f"[ERROR] Failed to sync trade history: {e}")
        raise


def sync_holdings_from_kiwoom(
    conn: pymysql.connections.Connection,
) -> int:
    """
    Fetch holdings from Kiwoom API and save to asset database.

    Args:
        conn: Database connection

    Returns:
        Number of records synced
    """
    print("Fetching holdings from Kiwoom API...")

    try:
        import json
        client = KiwoomAPIClient()
        data = client.get_holdings()

        if not data:
            print("No holdings found from Kiwoom API")
            return 0

        snapshot_date = date.today()

        # Helper functions
        def to_int(val):
            if val is None or val == '':
                return None
            try:
                return int(val)
            except (ValueError, TypeError):
                return None

        def to_float(val):
            if val is None or val == '':
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        # Clear existing data for today
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM holdings WHERE snapshot_date = %s",
                (snapshot_date,),
            )
        conn.commit()
        print(f"✓ Cleared existing holdings for {snapshot_date}")

        # Parse holdings from stk_acnt_evlt_prst array
        holdings_data = data.get("stk_acnt_evlt_prst", [])

        if not holdings_data:
            print("No holdings data in API response")
            return 0

        # Insert new records with all fields
        insert_sql = """
            INSERT INTO holdings (
                snapshot_date,
                stk_cd, stk_nm, rmnd_qty,
                avg_prc, cur_prc, evlt_amt,
                pl_amt, pl_rt,
                loan_dt, crd_class,
                pur_amt, setl_remn,
                pred_buyq, pred_sellq,
                tdy_buyq, tdy_sellq,
                raw_json
            )
            VALUES (
                %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s
            )
        """

        with conn.cursor() as cur:
            for item in holdings_data:
                loan_dt = item.get("loan_dt") or None
                crd_class = "CREDIT" if loan_dt else "CASH"

                cur.execute(
                    insert_sql,
                    (
                        snapshot_date,
                        item.get("stk_cd"),
                        item.get("stk_nm", ""),
                        to_int(item.get("rmnd_qty")),
                        to_int(item.get("avg_prc")),
                        to_int(item.get("cur_prc")),
                        to_int(item.get("evlt_amt")),
                        to_int(item.get("pl_amt")),
                        to_float(item.get("pl_rt")),
                        loan_dt,
                        crd_class,
                        to_int(item.get("pur_amt")),
                        to_int(item.get("setl_remn")),
                        to_int(item.get("pred_buyq")),
                        to_int(item.get("pred_sellq")),
                        to_int(item.get("tdy_buyq")),
                        to_int(item.get("tdy_sellq")),
                        json.dumps(item, ensure_ascii=False),
                    ),
                )

        conn.commit()
        print(f"✓ Inserted {len(holdings_data)} holding records from Kiwoom API")
        return len(holdings_data)

    except Exception as e:
        print(f"✗ Failed to sync holdings: {e}")
        import traceback
        traceback.print_exc()
        raise


def sync_account_summary_from_kiwoom(
    conn: pymysql.connections.Connection,
) -> int:
    """
    Fetch account summary from Kiwoom API and save to asset database.

    Args:
        conn: Database connection

    Returns:
        Number of records synced (0 or 1)
    """
    print("Fetching account summary from Kiwoom API...")

    try:
        import json
        client = KiwoomAPIClient()
        data = client.get_account_summary()

        if not data:
            print("No account summary found from Kiwoom API")
            return 0

        snapshot_date = date.today()

        # Helper function to safely convert to int
        def to_int(val):
            if val is None or val == '':
                return None
            try:
                return int(val)
            except (ValueError, TypeError):
                return None

        # Helper function to safely convert to float
        def to_float(val):
            if val is None or val == '':
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        # Delete existing record for today
        with conn.cursor() as cur:
            cur.execute("DELETE FROM account_summary WHERE snapshot_date = %s", (snapshot_date,))

        # Insert full account summary with all fields
        insert_sql = """
            INSERT INTO account_summary (
                snapshot_date,
                acnt_nm, brch_nm,
                entr, d2_entra,
                tot_est_amt, aset_evlt_amt, tot_pur_amt,
                prsm_dpst_aset_amt, tot_grnt_sella,
                tdy_lspft_amt, invt_bsamt, lspft_amt,
                tdy_lspft, lspft2, lspft,
                tdy_lspft_rt, lspft_ratio, lspft_rt,
                return_code, return_msg,
                raw_json
            )
            VALUES (
                %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s
            )
        """

        with conn.cursor() as cur:
            cur.execute(
                insert_sql,
                (
                    snapshot_date,
                    data.get("acnt_nm"),
                    data.get("brch_nm"),
                    to_int(data.get("entr")),
                    to_int(data.get("d2_entra")),
                    to_int(data.get("tot_est_amt")),
                    to_int(data.get("aset_evlt_amt")),
                    to_int(data.get("tot_pur_amt")),
                    to_int(data.get("prsm_dpst_aset_amt")),
                    to_int(data.get("tot_grnt_sella")),
                    to_int(data.get("tdy_lspft_amt")),
                    to_int(data.get("invt_bsamt")),
                    to_int(data.get("lspft_amt")),
                    to_int(data.get("tdy_lspft")),
                    to_int(data.get("lspft2")),
                    to_int(data.get("lspft")),
                    to_float(data.get("tdy_lspft_rt")),
                    to_float(data.get("lspft_ratio")),
                    to_float(data.get("lspft_rt")),
                    to_int(data.get("return_code")),
                    data.get("return_msg"),
                    json.dumps(data, ensure_ascii=False),
                ),
            )

        conn.commit()
        print(f"✓ Synced account summary from Kiwoom API")
        return 1

    except Exception as e:
        print(f"✗ Failed to sync account summary: {e}")
        import traceback
        traceback.print_exc()
        raise


def is_trading_day(check_date: date) -> bool:
    """
    Check if a date is a Korean trading day using Samsung Electronics data.

    Args:
        check_date: Date to check

    Returns:
        True if trading day, False otherwise
    """
    from utils.krx_calendar import is_korea_trading_day_by_samsung

    return is_korea_trading_day_by_samsung(check_date)


def sync_daily_snapshot_from_kiwoom(
    conn: pymysql.connections.Connection,
    target_date: date = None,
    accumulated_deposit: int = 0,
    accumulated_withdrawal: int = 0,
) -> int:
    """
    Fetch daily balance data to create portfolio snapshot.
    Uses ka01690 API which supports historical queries via dt parameter.
    Only saves data if target_date is a trading day.

    Args:
        conn: Database connection
        target_date: Date to sync (defaults to today)
        accumulated_deposit: Accumulated deposits from previous non-trading days
        accumulated_withdrawal: Accumulated withdrawals from previous non-trading days

    Returns:
        Number of records synced (0 or 1)
    """
    if target_date is None:
        target_date = date.today()

    # Check if trading day
    if not is_trading_day(target_date):
        print(f"Skipping {target_date} - not a trading day (weekend)")
        return 0

    print(f"Creating daily portfolio snapshot for {target_date}...")

    try:
        client = KiwoomAPIClient()

        # Get daily balance data (ka01690) with historical support
        balance_data = client.get_daily_balance(target_date)

        # Get daily cash flow data (kt00016)
        cash_flow_data = client.get_daily_cash_flow(target_date)

        if not balance_data:
            print("No balance data found from Kiwoom API")
            return 0

        snapshot_date = target_date

        # Helper function to safely convert to int
        def to_int(val):
            if val is None or val == '':
                return None
            try:
                return int(val)
            except (ValueError, TypeError):
                return None

        # Delete existing record for this date
        with conn.cursor() as cur:
            cur.execute("DELETE FROM daily_portfolio_snapshot WHERE snapshot_date = %s", (snapshot_date,))

        # Insert daily snapshot combining ka01690 + kt00016 data
        insert_sql = """
            INSERT INTO daily_portfolio_snapshot (
                snapshot_date,
                day_stk_asst,
                tot_pur_amt, tot_evlt_amt,
                ina_amt, outa,
                buy_amt, sell_amt, cmsn, tax,
                unrealized_pl, lspft_amt
            )
            VALUES (
                %s,
                %s,
                %s, %s,
                %s, %s,
                %s, %s, %s, %s,
                %s, %s
            )
        """

        # Get day_stk_asst (추정자산) directly from ka01690 API
        day_stk_asst = to_int(balance_data.get("day_stk_asst")) or 0

        # Parse day_bal_rt array from ka01690 to calculate stock totals
        day_bal_rt = balance_data.get("day_bal_rt", [])

        tot_evlt_amt = 0  # 총평가금액
        tot_pur_amt = 0   # 총매입금액

        for stock in day_bal_rt:
            evlt_amt = to_int(stock.get("evlt_amt")) or 0
            rmnd_qty = to_int(stock.get("rmnd_qty")) or 0
            buy_uv = to_int(stock.get("buy_uv")) or 0

            tot_evlt_amt += evlt_amt
            tot_pur_amt += (buy_uv * rmnd_qty)

        # Extract cash flow data from kt00016 and add accumulated values
        daily_deposit = to_int(cash_flow_data.get("termin_tot_trns")) or 0
        daily_withdrawal = to_int(cash_flow_data.get("termin_tot_pymn")) or 0

        ina_amt = daily_deposit + accumulated_deposit  # 기간내총입금 + 비거래일 누적
        outa = daily_withdrawal + accumulated_withdrawal  # 기간내총출금 + 비거래일 누적

        # These fields are not available from either API
        buy_amt = 0  # 매수금액
        sell_amt = 0 # 매도금액
        cmsn = 0     # 수수료
        tax = 0      # 세금
        lspft_amt = 0  # 실현손익

        # Calculate unrealized P/L
        unrealized_pl = tot_evlt_amt - tot_pur_amt

        with conn.cursor() as cur:
            cur.execute(
                insert_sql,
                (
                    snapshot_date,
                    day_stk_asst,
                    tot_pur_amt, tot_evlt_amt,
                    ina_amt, outa,
                    buy_amt, sell_amt, cmsn, tax,
                    unrealized_pl, lspft_amt,
                ),
            )

        conn.commit()
        print(f"✓ Synced daily portfolio snapshot for {target_date}")
        print(f"  Estimated Asset: {day_stk_asst or 0:,} won")
        print(f"  Deposit: {ina_amt or 0:,} won, Withdrawal: {outa or 0:,} won")
        return 1

    except Exception as e:
        print(f"✗ Failed to sync daily snapshot for {target_date}: {e}")
        import traceback
        traceback.print_exc()
        raise


def backfill_daily_snapshots(
    conn: pymysql.connections.Connection,
    start_date: date,
    end_date: date = None,
) -> int:
    """
    Backfill daily snapshots for all trading days in a date range.

    Args:
        conn: Database connection
        start_date: Start date (inclusive)
        end_date: End date (inclusive, defaults to today)

    Returns:
        Number of records synced
    """
    if end_date is None:
        end_date = date.today()

    print(f"Backfilling daily snapshots from {start_date} to {end_date}")
    print("=" * 80)

    from datetime import timedelta

    current_date = start_date
    synced_count = 0

    # Accumulate deposits/withdrawals from non-trading days
    accumulated_deposits = 0
    accumulated_withdrawals = 0

    while current_date <= end_date:
        if is_trading_day(current_date):
            try:
                # For trading days: sync full snapshot with accumulated cash flows
                client = KiwoomAPIClient()

                if accumulated_deposits > 0 or accumulated_withdrawals > 0:
                    print(f"[{current_date}] Trading day - Including accumulated: Deposit +{accumulated_deposits:,}, Withdrawal +{accumulated_withdrawals:,}")
                else:
                    print(f"[{current_date}] Trading day")

                # Sync the full snapshot with accumulated cash flows
                result = sync_daily_snapshot_from_kiwoom(
                    conn,
                    current_date,
                    accumulated_deposit=accumulated_deposits,
                    accumulated_withdrawal=accumulated_withdrawals
                )
                if result > 0:
                    synced_count += 1

                # Reset accumulators after successful sync
                accumulated_deposits = 0
                accumulated_withdrawals = 0

            except Exception as e:
                print(f"[{current_date}] Failed: {e}")
        else:
            # For non-trading days: check for deposits/withdrawals and accumulate
            try:
                client = KiwoomAPIClient()
                cash_flow = client.get_daily_cash_flow(current_date)

                def to_int(val):
                    if val is None or val == '':
                        return 0
                    try:
                        return int(val)
                    except (ValueError, TypeError):
                        return 0

                deposit = to_int(cash_flow.get("termin_tot_trns"))
                withdrawal = to_int(cash_flow.get("termin_tot_pymn"))

                if deposit > 0 or withdrawal > 0:
                    accumulated_deposits += deposit
                    accumulated_withdrawals += withdrawal
                    print(f"[{current_date}] Non-trading day - Accumulated Deposit: +{deposit:,}, Withdrawal: +{withdrawal:,}")
                else:
                    print(f"[{current_date}] Non-trading day - No cash flow")

            except Exception as e:
                print(f"[{current_date}] Non-trading day - Failed to check cash flow: {e}")

        current_date += timedelta(days=1)

        # Rate limit: delay between API calls
        import time
        time.sleep(0.5)

    print("=" * 80)
    print(f"Backfill complete: {synced_count} synced")
    return synced_count


def sync_market_index_from_kiwoom(
    conn: pymysql.connections.Connection,
    start_date: date = None,
    end_date: date = None,
) -> int:
    """
    Fetch KOSPI and KOSDAQ index data from Kiwoom API and save to database.
    Uses ka20009 API which returns daily history.

    Args:
        conn: Database connection
        start_date: Start date to filter (inclusive). If None, saves all returned data.
        end_date: End date to filter (inclusive). If None, uses today.

    Returns:
        Number of records synced
    """
    if end_date is None:
        end_date = date.today()

    print(f"Fetching market index data from Kiwoom API...")

    try:
        client = KiwoomAPIClient()

        # Fetch KOSPI data (mrkt_tp="0", inds_cd="001")
        print("  Fetching KOSPI index...")
        kospi_data = client.get_market_index(market_type="0", index_code="001")

        # Fetch KOSDAQ data (mrkt_tp="1", inds_cd="101")
        print("  Fetching KOSDAQ index...")
        kosdaq_data = client.get_market_index(market_type="1", index_code="101")

        if not kospi_data and not kosdaq_data:
            print("No market index data found from Kiwoom API")
            return 0

        # Parse KOSPI daily data into dict by date
        kospi_by_date = {}
        if kospi_data:
            for item in kospi_data.get("inds_cur_prc_daly_rept", []):
                dt_str = item.get("dt_n")
                if dt_str:
                    idx_date = client._parse_date(dt_str)
                    kospi_by_date[idx_date] = {
                        "close": client._parse_price(item.get("cur_prc_n")),
                        "change": client._parse_signed_value(item.get("pred_pre_n")),
                        "change_pct": client._parse_signed_value(item.get("flu_rt_n")),
                    }

        # Parse KOSDAQ daily data into dict by date
        kosdaq_by_date = {}
        if kosdaq_data:
            for item in kosdaq_data.get("inds_cur_prc_daly_rept", []):
                dt_str = item.get("dt_n")
                if dt_str:
                    idx_date = client._parse_date(dt_str)
                    kosdaq_by_date[idx_date] = {
                        "close": client._parse_price(item.get("cur_prc_n")),
                        "change": client._parse_signed_value(item.get("pred_pre_n")),
                        "change_pct": client._parse_signed_value(item.get("flu_rt_n")),
                    }

        # Merge all dates
        all_dates = set(kospi_by_date.keys()) | set(kosdaq_by_date.keys())

        # Filter by date range
        if start_date:
            all_dates = {d for d in all_dates if d >= start_date}
        all_dates = {d for d in all_dates if d <= end_date}

        if not all_dates:
            print("No market index data within date range")
            return 0

        # Upsert records
        upsert_sql = """
            INSERT INTO market_index (
                index_date,
                kospi_close, kospi_change, kospi_change_pct,
                kosdaq_close, kosdaq_change, kosdaq_change_pct
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                kospi_close = VALUES(kospi_close),
                kospi_change = VALUES(kospi_change),
                kospi_change_pct = VALUES(kospi_change_pct),
                kosdaq_close = VALUES(kosdaq_close),
                kosdaq_change = VALUES(kosdaq_change),
                kosdaq_change_pct = VALUES(kosdaq_change_pct),
                updated_at = CURRENT_TIMESTAMP
        """

        synced_count = 0
        with conn.cursor() as cur:
            for idx_date in sorted(all_dates):
                kospi = kospi_by_date.get(idx_date, {})
                kosdaq = kosdaq_by_date.get(idx_date, {})

                cur.execute(
                    upsert_sql,
                    (
                        idx_date,
                        kospi.get("close"),
                        kospi.get("change"),
                        kospi.get("change_pct"),
                        kosdaq.get("close"),
                        kosdaq.get("change"),
                        kosdaq.get("change_pct"),
                    ),
                )
                synced_count += 1

        conn.commit()
        print(f"[OK] Synced {synced_count} market index records")
        return synced_count

    except Exception as e:
        print(f"[ERROR] Failed to sync market index: {e}")
        import traceback
        traceback.print_exc()
        raise


def backfill_market_index(
    conn: pymysql.connections.Connection,
    start_date: date = None,
    end_date: date = None,
) -> int:
    """
    Backfill market index data for a date range.
    This is a wrapper around sync_market_index_from_kiwoom with date filtering.

    Args:
        conn: Database connection
        start_date: Start date (inclusive)
        end_date: End date (inclusive, defaults to today)

    Returns:
        Number of records synced
    """
    print(f"Backfilling market index from {start_date} to {end_date or date.today()}")
    print("=" * 80)

    result = sync_market_index_from_kiwoom(conn, start_date, end_date)

    print("=" * 80)
    print(f"Backfill complete: {result} records")
    return result


# ============================================================================
# Auto Trading APIs (자동매매용 API)
# ============================================================================

class KiwoomTradingClient(KiwoomAPIClient):
    """
    Extended Kiwoom API client with trading capabilities.
    Inherits from KiwoomAPIClient and adds order/price APIs.
    """

    def __init__(self):
        super().__init__()
        self._last_request_time = 0
        self._rate_limit_interval = 0.5  # 0.5초 간격

    def _wait_for_rate_limit(self):
        """Wait to respect API rate limits."""
        import time
        elapsed = time.time() - self._last_request_time
        if elapsed < self._rate_limit_interval:
            time.sleep(self._rate_limit_interval - elapsed)
        self._last_request_time = time.time()

    def get_current_price(self, stock_code: str) -> Dict[str, Any]:
        """
        보유종목 현재가 조회 (kt00004 holdings에서 추출)
        주의: 보유하지 않은 종목은 조회 불가. WebSocket 사용 권장.

        Args:
            stock_code: 종목코드 (6자리)

        Returns:
            dict: 현재가 정보 (보유종목만)
        """
        # 보유종목에서 현재가 추출
        holdings = self.get_holdings()
        holdings_list = holdings.get("stk_acnt_evlt_prst", [])

        for item in holdings_list:
            if item.get("stk_cd") == stock_code:
                return {
                    "stock_code": stock_code,
                    "last": int(item.get("cur_prc", 0) or 0),
                    "avg_price": int(item.get("avg_prc", 0) or 0),
                    "quantity": int(item.get("rmnd_qty", 0) or 0),
                    "eval_amt": int(item.get("evlt_amt", 0) or 0),
                    "pl_amt": int(item.get("pl_amt", 0) or 0),
                    "pl_pct": float(item.get("pl_rt", 0) or 0),
                }

        raise Exception(f"Stock {stock_code} not found in holdings. Use WebSocket for non-held stocks.")

    def get_buying_power(self) -> Dict[str, Any]:
        """
        매수가능금액 조회 (kt00008 또는 kt00004에서 추출)

        Returns:
            dict: 매수가능금액 정보
        """
        token = self.get_access_token()

        # kt00004 (계좌잔고)에서 예수금 정보 추출
        url = f"{self.base_url}/api/dostk/acnt"

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'api-id': 'kt00004',
        }

        body = {
            "qry_tp": "1",
            "dmst_stex_tp": "KRX",
        }

        self._wait_for_rate_limit()

        try:
            response = requests.post(url, headers=headers, json=body, timeout=10)
            response.raise_for_status()
            result = response.json()

            if result.get("return_code") != 0:
                raise Exception(f"API error: {result.get('return_msg', 'Unknown error')}")

            # 예수금 관련 필드
            d2_entra = int(result.get("d2_entra", 0) or 0)  # D+2 예수금
            entr = int(result.get("entr", 0) or 0)  # 예수금

            return {
                "available_amt": d2_entra,  # 매수가능금액 (D+2 예수금)
                "deposit": entr,  # 예수금
                "currency": "KRW",
            }

        except Exception as e:
            print(f"Failed to get buying power: {e}")
            raise

    def buy_order(
        self,
        stock_code: str,
        quantity: int,
        price: int,
        order_type: str = "0",
        use_credit: bool = True,
    ) -> Dict[str, Any]:
        """
        매수 주문 (신용 또는 현금)

        Args:
            stock_code: 종목코드 (6자리)
            quantity: 주문수량
            price: 주문가격 (지정가)
            order_type: 매매구분 (0: 보통, 3: 시장가, 5: 조건부지정가 등)
            use_credit: True=신용주문, False=현금주문

        Returns:
            dict: 주문 결과 (주문번호 등)
        """
        token = self.get_access_token()

        # 신용주문: /api/dostk/crdordr, 현금주문: /api/dostk/ordr
        if use_credit:
            url = f"{self.base_url}/api/dostk/crdordr"
        else:
            url = f"{self.base_url}/api/dostk/ordr"

        # 둘 다 같은 Body 형식 사용
        body = {
            "dmst_stex_tp": "KRX",  # 국내거래소 (KRX/NXT/SOR)
            "stk_cd": stock_code,
            "ord_qty": str(quantity),
            "ord_uv": str(price),
            "trde_tp": order_type,  # 0:보통, 3:시장가, 5:조건부지정가 등
        }

        # API ID: kt10000=현금매수, kt10006=신용매수
        api_id = 'kt10006' if use_credit else 'kt10000'

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'api-id': api_id,
        }

        self._wait_for_rate_limit()

        try:
            response = requests.post(url, headers=headers, json=body, timeout=10)
            response.raise_for_status()
            result = response.json()

            if result.get("return_code") != 0:
                error_msg = result.get('return_msg', 'Unknown error')
                if self._is_credit_limit_error(error_msg):
                    raise CreditLimitError(error_msg)
                raise Exception(f"Order error: {error_msg}")

            return {
                "order_no": result.get("ord_no", ""),
                "order_time": result.get("ord_tm", ""),
                "message": result.get("return_msg", ""),
                "exchange": result.get("dmst_stex_tp", ""),
                "order_type": "CREDIT" if use_credit else "CASH",
            }

        except CreditLimitError:
            raise
        except Exception as e:
            print(f"[{stock_code}] Buy order failed: {e}")
            raise

    @staticmethod
    def _is_credit_limit_error(error_msg: str) -> bool:
        """신용한도 초과 오류인지 확인."""
        credit_limit_keywords = [
            "신용한도",
            "용자한도",
            "한도초과",
            "한도 초과",
        ]
        return any(keyword in error_msg for keyword in credit_limit_keywords)

    def sell_order(
        self,
        stock_code: str,
        quantity: int,
        price: int,
        order_type: str = "0",
    ) -> Dict[str, Any]:
        """
        현금 매도 주문 (kt10001 - 주식매도주문)

        Args:
            stock_code: 종목코드 (6자리)
            quantity: 주문수량
            price: 주문가격 (지정가)
            order_type: 매매구분 (0: 보통, 3: 시장가, 62: 시간외단일가)

        Returns:
            dict: 주문 결과
        """
        token = self.get_access_token()

        url = f"{self.base_url}/api/dostk/ordr"

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'api-id': 'kt10001',
        }

        body = {
            "dmst_stex_tp": "KRX",  # 국내거래소 (KRX/NXT/SOR)
            "stk_cd": stock_code,
            "ord_qty": str(quantity),
            "ord_uv": str(price),
            "trde_tp": order_type,  # 0:보통, 3:시장가, 62:시간외단일가
        }

        self._wait_for_rate_limit()

        try:
            response = requests.post(url, headers=headers, json=body, timeout=10)
            response.raise_for_status()
            result = response.json()

            if result.get("return_code") != 0:
                raise Exception(f"Order error: {result.get('return_msg', 'Unknown error')}")

            return {
                "order_no": result.get("ord_no", ""),
                "order_time": result.get("ord_tm", ""),
                "message": result.get("return_msg", ""),
            }

        except Exception as e:
            print(f"[{stock_code}] Sell order failed: {e}")
            raise

    def sell_credit_order(
        self,
        stock_code: str,
        quantity: int,
        price: int,
        loan_dt: str = "",
        order_type: str = "0",
    ) -> Dict[str, Any]:
        """
        신용 매도 주문 (kt10007 - 신용매도주문)

        Args:
            stock_code: 종목코드 (6자리)
            quantity: 주문수량
            price: 주문가격 (지정가)
            loan_dt: 대출일자 (YYYYMMDD, 빈값이면 자동)
            order_type: 매매구분 (0: 보통, 3: 시장가, 62: 시간외단일가)

        Returns:
            dict: 주문 결과
        """
        token = self.get_access_token()

        url = f"{self.base_url}/api/dostk/crdordr"

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'api-id': 'kt10007',
        }

        body = {
            "dmst_stex_tp": "KRX",  # 국내거래소 (KRX/NXT/SOR)
            "stk_cd": stock_code,
            "ord_qty": str(quantity),
            "ord_uv": str(price),
            "trde_tp": order_type,  # 0:보통, 3:시장가, 62:시간외단일가
            "loan_dt": loan_dt,  # 대출일자 (빈값이면 자동)
        }

        self._wait_for_rate_limit()

        try:
            response = requests.post(url, headers=headers, json=body, timeout=10)
            response.raise_for_status()
            result = response.json()

            if result.get("return_code") != 0:
                raise Exception(f"Credit sell error: {result.get('return_msg', 'Unknown error')}")

            return {
                "order_no": result.get("ord_no", ""),
                "order_time": result.get("ord_tm", ""),
                "message": result.get("return_msg", ""),
            }

        except Exception as e:
            print(f"[{stock_code}] Credit sell order failed: {e}")
            raise

    def get_pending_orders(self) -> List[Dict[str, Any]]:
        """
        미체결 주문 조회 (kt00005 - 미체결조회)

        Returns:
            list: 미체결 주문 리스트
        """
        token = self.get_access_token()

        url = f"{self.base_url}/api/dostk/acnt"

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'api-id': 'kt00005',
        }

        body = {
            "qry_tp": "0",  # 전체
        }

        self._wait_for_rate_limit()

        try:
            response = requests.post(url, headers=headers, json=body, timeout=10)
            response.raise_for_status()
            result = response.json()

            if result.get("return_code") != 0:
                raise Exception(f"API error: {result.get('return_msg', 'Unknown error')}")

            return result.get("ncls_ord_list", [])

        except Exception as e:
            print(f"Failed to get pending orders: {e}")
            raise

    def get_net_assets(self) -> Dict[str, Any]:
        """
        순자산 및 주식자산 조회 (레버리지 계산용)

        Returns:
            dict: 순자산, 주식평가금액, 레버리지 비율
        """
        token = self.get_access_token()

        url = f"{self.base_url}/api/dostk/acnt"

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'api-id': 'kt00004',
        }

        body = {
            "qry_tp": "1",
            "dmst_stex_tp": "KRX",
        }

        self._wait_for_rate_limit()

        try:
            response = requests.post(url, headers=headers, json=body, timeout=10)
            response.raise_for_status()
            result = response.json()

            if result.get("return_code") != 0:
                raise Exception(f"API error: {result.get('return_msg', 'Unknown error')}")

            # prsm_dpst_aset_amt: 추정예탁자산 (순자산)
            # tot_est_amt: 유가잔고평가액 (주식평가금액)
            net_assets = int(result.get("prsm_dpst_aset_amt", 0) or 0)
            stock_assets = int(result.get("tot_est_amt", 0) or 0)

            # 주식 비중 계산 (주식자산 / 순자산 * 100)
            leverage_pct = (stock_assets / net_assets * 100) if net_assets > 0 else 0

            return {
                "net_assets": net_assets,  # 순자산 (추정예탁자산)
                "stock_assets": stock_assets,  # 주식평가금액 (유가잔고평가액)
                "leverage_pct": leverage_pct,  # 현재 주식 비중 (%)
            }

        except Exception as e:
            print(f"Failed to get net assets: {e}")
            raise

    @staticmethod
    def get_tick_size(price: int) -> int:
        """
        국내주식 호가단위 계산

        Args:
            price: 현재가

        Returns:
            호가단위
        """
        if price < 2000:
            return 1
        elif price < 5000:
            return 5
        elif price < 20000:
            return 10
        elif price < 50000:
            return 50
        elif price < 200000:
            return 100
        elif price < 500000:
            return 500
        else:
            return 1000

    def get_after_hours_price(self, stock_code: str, _retry: bool = True) -> Dict[str, Any]:
        """
        시간외단일가 시세 조회 (REST API - ka10087)

        시간외단일가 시간대(15:40~16:00, 17:30~18:00)에 사용.

        Args:
            stock_code: 종목코드 (6자리)
            _retry: 토큰 만료 시 재시도 여부 (내부용)

        Returns:
            dict: {
                "stock_code": "005930",
                "last": 164300,           # 시간외단일가 현재가
                "change": 13900,          # 전일대비
                "change_pct": 9.24,       # 등락률
                "volume": 25211212,       # 누적거래량
                "bid_price": 164200,      # 매수호가1
                "ask_price": 164400,      # 매도호가1
                "bid_qty": 1000,          # 매수호가잔량
                "ask_qty": 500,           # 매도호가잔량
                "market": "AFTER_HOURS",
            }
        """
        token = self.get_access_token()

        url = f"{self.base_url}/api/dostk/stkinfo"

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json; charset=UTF-8',
            'api-id': 'ka10087',  # 시간외단일가요청
        }

        body = {
            "stk_cd": stock_code,
        }

        try:
            self._wait_for_rate_limit()
            response = requests.post(url, headers=headers, json=body, timeout=10)
            response.raise_for_status()
            result = response.json()

            return_code = result.get("return_code")
            return_msg = result.get("return_msg", "")

            # Token expired error: retry with new token
            if return_code == 8005 or "8005" in str(return_msg) or ("Token" in return_msg and "유효" in return_msg):
                if _retry:
                    print(f"[TOKEN] Token expired, refreshing and retrying...")
                    self.refresh_token()
                    return self.get_after_hours_price(stock_code, _retry=False)
                else:
                    raise Exception(f"API error: {return_msg}")

            if return_code not in (0, None):
                raise Exception(f"API error: {return_msg}")

            def parse_price(val):
                """가격 문자열 파싱 (+/-부호 제거)"""
                if not val:
                    return 0
                val_str = str(val).replace("+", "").replace("-", "")
                try:
                    return int(val_str)
                except ValueError:
                    return 0

            def parse_float(val):
                """실수 문자열 파싱"""
                if not val:
                    return 0.0
                val_str = str(val).replace("+", "").replace("-", "")
                try:
                    return float(val_str)
                except ValueError:
                    return 0.0

            # 부호 판단 (2: 상승, 5: 하락)
            pre_sig = result.get("ovt_sigpric_pred_pre_sig", "")
            change = parse_price(result.get("ovt_sigpric_pred_pre", "0"))
            if pre_sig == "5":
                change = -change

            return {
                "stock_code": stock_code,
                "last": parse_price(result.get("ovt_sigpric_cur_prc")),
                "change": change,
                "change_pct": parse_float(result.get("ovt_sigpric_flu_rt")),
                "volume": parse_price(result.get("ovt_sigpric_acc_trde_qty")),
                "bid_price": parse_price(result.get("ovt_sigpric_buy_bid_1")),
                "ask_price": parse_price(result.get("ovt_sigpric_sel_bid_1")),
                "bid_qty": parse_price(result.get("ovt_sigpric_buy_bid_qty_1")),
                "ask_qty": parse_price(result.get("ovt_sigpric_sel_bid_qty_1")),
                "total_bid_qty": parse_price(result.get("ovt_sigpric_buy_bid_tot_req")),
                "total_ask_qty": parse_price(result.get("ovt_sigpric_sel_bid_tot_req")),
                "market": "AFTER_HOURS",
            }

        except Exception as e:
            print(f"[ERROR] Failed to get after-hours price for {stock_code}: {e}")
            return {
                "stock_code": stock_code,
                "last": 0,
                "change": 0,
                "change_pct": 0.0,
                "volume": 0,
                "bid_price": 0,
                "ask_price": 0,
                "bid_qty": 0,
                "ask_qty": 0,
                "total_bid_qty": 0,
                "total_ask_qty": 0,
                "market": "AFTER_HOURS",
            }

    def get_stock_price(self, stock_code: str, market_type: str = "KRX", _retry: bool = True) -> Dict[str, Any]:
        """
        개별 종목 현재가 조회 (REST API)

        Args:
            stock_code: 종목코드 (6자리)
            market_type: 시장구분 (KRX: 정규장, NXT: 대체거래소)
            _retry: 토큰 만료 시 재시도 여부 (내부용)

        Returns:
            dict: {
                "stock_code": "005930",
                "name": "삼성전자",
                "last": 164300,        # 현재가
                "open": 157900,        # 시가
                "high": 165100,        # 고가
                "low": 157200,         # 저가
                "volume": 25211212,    # 거래량
                "change": 13900,       # 전일대비
                "change_pct": 9.24,    # 등락률
                "market": "KRX",       # 조회 시장
            }
        """
        token = self.get_access_token()

        url = f"{self.base_url}/api/dostk/stkinfo"

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json; charset=UTF-8',
            'api-id': 'ka10001',  # 개별종목 시세
        }

        # NXT 조회 시 종목코드에 _NX 붙여야 함 (API 스펙)
        # KRX: 039490, NXT: 039490_NX, SOR: 039490_AL
        if market_type == "NXT":
            query_code = f"{stock_code}_NX"
        else:
            query_code = stock_code

        body = {
            "stk_cd": query_code,
            "dmst_stex_tp": market_type,  # KRX: 정규장, NXT: 대체거래소
        }

        try:
            self._wait_for_rate_limit()
            response = requests.post(url, headers=headers, json=body, timeout=10)
            response.raise_for_status()
            result = response.json()

            return_code = result.get("return_code")
            return_msg = result.get("return_msg", "")

            # Token expired error: retry with new token
            if return_code == 8005 or "8005" in str(return_msg) or ("Token" in return_msg and "유효" in return_msg):
                if _retry:
                    print(f"[TOKEN] Token expired, refreshing and retrying...")
                    self.refresh_token()
                    return self.get_stock_price(stock_code, market_type=market_type, _retry=False)
                else:
                    raise Exception(f"API error: {return_msg}")

            if return_code not in (0, None):
                raise Exception(f"API error: {return_msg}")

            def parse_price(val):
                """가격 문자열 파싱 (+/-부호 제거)"""
                if not val:
                    return 0
                val_str = str(val).replace("+", "").replace("-", "")
                try:
                    return int(val_str)
                except ValueError:
                    return 0

            def parse_float(val):
                """실수 문자열 파싱"""
                if not val:
                    return 0.0
                val_str = str(val).replace("+", "").replace("-", "")
                try:
                    return float(val_str)
                except ValueError:
                    return 0.0

            # 부호 판단 (2: 상승, 5: 하락)
            pre_sig = result.get("pre_sig", "")
            change = parse_price(result.get("pred_pre", "0"))
            if pre_sig == "5":
                change = -change

            return {
                "stock_code": stock_code,
                "name": result.get("stk_nm", ""),
                "last": parse_price(result.get("cur_prc")),
                "open": parse_price(result.get("open_pric")),
                "high": parse_price(result.get("high_pric")),
                "low": parse_price(result.get("low_pric")),
                "volume": parse_price(result.get("trde_qty")),
                "change": change,
                "change_pct": parse_float(result.get("flu_rt")),
                "market": market_type,
            }

        except Exception as e:
            print(f"[ERROR] Failed to get stock price for {stock_code} ({market_type}): {e}")
            return {
                "stock_code": stock_code,
                "name": "",
                "last": 0,
                "open": 0,
                "high": 0,
                "low": 0,
                "volume": 0,
                "change": 0,
                "change_pct": 0.0,
                "market": market_type,
            }

    def get_stock_price_with_fallback(self, stock_code: str, market_type: str = "KRX") -> Dict[str, Any]:
        """
        종목 현재가 조회 (NXT 실패 시 KRX로 폴백, 둘 다 실패 시 holdings DB 캐시 사용)

        일부 종목은 NXT를 지원하지 않아 에러가 발생할 수 있음.
        NXT 조회 실패 또는 가격이 0인 경우 KRX로 재시도.
        KRX도 0인 경우 (장 시작 전) holdings DB에서 캐시된 가격 사용.

        Args:
            stock_code: 종목코드 (6자리)
            market_type: 시장구분 (KRX: 정규장, NXT: 대체거래소)

        Returns:
            dict: 현재가 정보 (market 필드에 실제 조회된 시장 표시)
        """
        result = self.get_stock_price(stock_code, market_type=market_type)

        # NXT 조회 실패 또는 가격이 0인 경우 KRX로 폴백 (silent)
        if market_type == "NXT" and result.get("last", 0) == 0:
            result = self.get_stock_price(stock_code, market_type="KRX")

        # KRX도 0인 경우 (장 시작 전) holdings DB에서 캐시된 가격 사용 (silent)
        if result.get("last", 0) == 0:
            try:
                from db.connection import get_connection
                conn = get_connection()
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT cur_prc FROM holdings
                        WHERE REPLACE(stk_cd, 'A', '') = %s
                        ORDER BY snapshot_date DESC LIMIT 1
                    """, (stock_code,))
                    row = cur.fetchone()
                    if row and row[0]:
                        result["last"] = int(row[0])
                        result["market"] = "CACHE"
                conn.close()
            except Exception:
                pass

        return result

    def get_stock_list(self, market_type: str = "0") -> List[Dict[str, Any]]:
        """
        종목정보 리스트 조회 (종목코드 → 종목명 매핑용)

        Args:
            market_type: 시장구분 (0: 코스피, 10: 코스닥)

        Returns:
            list: 종목 리스트 [{"code": "005930", "name": "삼성전자", ...}, ...]
        """
        token = self.get_access_token()

        url = f"{self.base_url}/api/dostk/stkinfo"

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json; charset=UTF-8',
            'api-id': 'ka10099',  # 종목정보 리스트 API
        }

        body = {
            "mrkt_tp": market_type,
        }

        all_stocks = []
        cont_yn = "N"
        next_key = ""

        try:
            while True:
                if cont_yn == "Y":
                    headers["cont-yn"] = "Y"
                    headers["next-key"] = next_key

                self._wait_for_rate_limit()
                response = requests.post(url, headers=headers, json=body, timeout=30)
                response.raise_for_status()
                result = response.json()

                if result.get("return_code") != 0:
                    raise Exception(f"API error: {result.get('return_msg', 'Unknown error')}")

                stocks = result.get("list", [])
                all_stocks.extend(stocks)

                cont_yn = response.headers.get("cont-yn", "N")
                next_key = response.headers.get("next-key", "")

                if cont_yn != "Y":
                    break

            return all_stocks

        except Exception as e:
            print(f"Failed to get stock list: {e}")
            return []  # 실패시 빈 리스트 반환 (정적 매핑으로 폴백)


# 종목명 캐시 (싱글톤)
_stock_name_cache: Dict[str, str] = {}  # code → name
_stock_code_cache: Dict[str, str] = {}  # name → code (역방향)
_stock_cache_loaded = False

# 자주 사용하는 종목 정적 매핑 (API 의존성 없이 안정적)
_COMMON_STOCKS = {
    # KOSPI 대형주
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "005935": "삼성전자우",
    "005380": "현대차",
    "000270": "기아",
    "005490": "POSCO홀딩스",
    "035420": "NAVER",
    "035720": "카카오",
    "051910": "LG화학",
    "006400": "삼성SDI",
    "003670": "포스코퓨처엠",
    "207940": "삼성바이오로직스",
    "005387": "현대차2우B",
    "005389": "현대차3우B",
    "068270": "셀트리온",
    "028260": "삼성물산",
    "012330": "현대모비스",
    "066570": "LG전자",
    "055550": "신한지주",
    "105560": "KB금융",
    "086790": "하나금융지주",
    "316140": "우리금융지주",
    "003550": "LG",
    "017670": "SK텔레콤",
    "034730": "SK",
    "096770": "SK이노베이션",
    "032830": "삼성생명",
    "030200": "KT",
    "010130": "고려아연",
    "009150": "삼성전기",
    "011200": "HMM",
    "010950": "S-Oil",
    "018260": "삼성에스디에스",
    "033780": "KT&G",
    "373220": "LG에너지솔루션",
    "000810": "삼성화재",
    "009540": "HD한국조선해양",
    "329180": "HD현대중공업",
    "042700": "한미반도체",
    # KOSDAQ 대형주
    "247540": "에코프로비엠",
    "086520": "에코프로",
    "041510": "에스엠",
    "263750": "펄어비스",
    "293490": "카카오게임즈",
    "112040": "위메이드",
    "196170": "알테오젠",
    "357780": "솔브레인",
    "039030": "이오테크닉스",
    "403870": "HPSP",
    "067310": "하나마이크론",
    "095340": "ISC",
    "060310": "3S",
    "058470": "리노공업",
    "352820": "하이브",
    "145020": "휴젤",
    "064350": "현대로템",
}


def get_stock_name(stock_code: str) -> str:
    """
    종목코드로 종목명 조회 (캐시 사용)

    Args:
        stock_code: 종목코드 (6자리)

    Returns:
        종목명 (없으면 빈 문자열)
    """
    global _stock_cache_loaded

    if not _stock_cache_loaded:
        load_stock_cache()

    return _stock_name_cache.get(stock_code, "")


def get_stock_code(stock_name: str) -> str:
    """
    종목명으로 종목코드 조회 (캐시 사용)

    Args:
        stock_name: 종목명 (예: "삼성전자", "SK하이닉스")

    Returns:
        종목코드 (없으면 빈 문자열)
    """
    global _stock_cache_loaded

    if not _stock_cache_loaded:
        load_stock_cache()

    # 공백 제거 및 정규화
    normalized_name = stock_name.strip().replace(" ", "")

    # 정확히 일치하는 경우
    if normalized_name in _stock_code_cache:
        return _stock_code_cache[normalized_name]

    # 부분 일치 (입력값이 실제 종목명에 포함된 경우)
    for name, code in _stock_code_cache.items():
        name_normalized = name.replace(" ", "")
        if normalized_name in name_normalized or name_normalized in normalized_name:
            return code

    return ""


def load_stock_cache():
    """종목명 캐시 로드 (API → 정적 매핑 폴백)."""
    global _stock_name_cache, _stock_code_cache, _stock_cache_loaded

    print("[INFO] Loading stock cache...")

    try:
        client = KiwoomTradingClient()

        # 1. API에서 코스피 종목 로드
        print("[INFO] Fetching KOSPI stocks...")
        kospi_stocks = client.get_stock_list("0")
        for stock in kospi_stocks:
            code = stock.get("code", "")
            name = stock.get("name", "")
            if code and name:
                _stock_name_cache[code] = name
                _stock_code_cache[name] = code
                _stock_code_cache[name.replace(" ", "")] = code

        print(f"[INFO] Loaded {len(kospi_stocks)} KOSPI stocks")

        # 2. API에서 코스닥 종목 로드
        print("[INFO] Fetching KOSDAQ stocks...")
        kosdaq_stocks = client.get_stock_list("10")
        for stock in kosdaq_stocks:
            code = stock.get("code", "")
            name = stock.get("name", "")
            if code and name:
                _stock_name_cache[code] = name
                _stock_code_cache[name] = code
                _stock_code_cache[name.replace(" ", "")] = code

        print(f"[INFO] Loaded {len(kosdaq_stocks)} KOSDAQ stocks")

    except Exception as e:
        print(f"[WARNING] Failed to load from API: {e}")
        print("[INFO] Using static mapping as fallback...")

        # 정적 매핑 폴백
        for code, name in _COMMON_STOCKS.items():
            _stock_name_cache[code] = name
            _stock_code_cache[name] = code
            _stock_code_cache[name.replace(" ", "")] = code

    _stock_cache_loaded = True
    print(f"[INFO] Total stocks in cache: {len(_stock_name_cache)}")


class CreditLimitError(Exception):
    """회사 신용한도 초과 종목 에러."""
    pass
