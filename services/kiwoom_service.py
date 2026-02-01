"""
Kiwoom API service for fetching account trade history and holdings.
"""

from datetime import date
from typing import List, Dict, Any
import requests
import pymysql
from decimal import Decimal

from config.settings import Settings


class KiwoomAPIClient:
    """Client for Kiwoom eFriend Plus API."""

    def __init__(self):
        self.settings = Settings()
        self.base_url = self.settings.BASE_URL
        self.app_key = self.settings.APP_KEY
        self.secret_key = self.settings.SECRET_KEY
        self.acnt_api_id = self.settings.ACNT_API_ID
        self.access_token = None

    def get_access_token(self) -> str:
        """
        Get access token for API authentication.
        
        Returns:
            Access token string
        """
        if self.access_token:
            return self.access_token

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
            return self.access_token
        except Exception as e:
            print(f"✗ Failed to get access token: {e}")
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

    def get_holdings(self) -> Dict[str, Any]:
        """
        Fetch current holdings from Kiwoom API with continuous query support.

        Returns:
            Full holdings data from API response (merged from all pages)
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
