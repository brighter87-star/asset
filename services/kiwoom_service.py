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
        Fetch current holdings from Kiwoom API.

        Returns:
            Full holdings data from API response
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
            response = requests.post(url, headers=headers, json=body, timeout=10)
            response.raise_for_status()
            result = response.json()

            # Return full response for detailed processing
            return result

        except Exception as e:
            print(f"✗ Failed to fetch holdings: {e}")
            raise

    def get_account_summary(self) -> Dict[str, Any]:
        """
        Fetch account summary from Kiwoom API.

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
            response = requests.post(url, headers=headers, json=body, timeout=10)
            response.raise_for_status()
            result = response.json()

            # Return full response for detailed processing
            return result

        except Exception as e:
            print(f"✗ Failed to fetch account summary: {e}")
            raise

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

        client = KiwoomAPIClient()

        # Parse start date
        start_dt = datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.today()

        # Clear existing data
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE account_trade_history")
        conn.commit()
        print(f"✓ Cleared existing trade history")

        # Fetch trades for each day from start_date to today
        all_trades = []
        current_dt = start_dt

        while current_dt <= end_dt:
            date_str = current_dt.strftime("%Y%m%d")
            print(f"  Fetching trades for {date_str}...")

            try:
                daily_trades = client.get_account_trade_history(start_date=date_str)
                if daily_trades:
                    all_trades.extend(daily_trades)
                    print(f"    ✓ Found {len(daily_trades)} trades")
            except Exception as e:
                print(f"    ⚠ Failed to fetch trades for {date_str}: {e}")
                # Continue with next date even if one day fails

            current_dt += timedelta(days=1)

        if not all_trades:
            print("No trade history found from Kiwoom API")
            return 0

        # Insert new records
        insert_sql = """
            INSERT INTO account_trade_history (
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
                try:
                    cur.execute(insert_sql, trade)
                    inserted_count += 1
                except pymysql.err.IntegrityError:
                    # Skip duplicate entries
                    continue

        conn.commit()
        print(f"✓ Inserted {inserted_count} trade records from Kiwoom API")
        return inserted_count

    except Exception as e:
        print(f"✗ Failed to sync trade history: {e}")
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
