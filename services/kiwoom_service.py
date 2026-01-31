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

        url = f"{self.base_url}/oauth2/tokenP"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.secret_key,
        }

        try:
            response = requests.post(url, headers=headers, data=data, timeout=10)
            response.raise_for_status()
            result = response.json()
            self.access_token = result.get("access_token")
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

        # API endpoint for account trade history
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"

        headers = {
            "Authorization": f"Bearer {token}",
            "appKey": self.app_key,
            "appSecret": self.secret_key,
            "tr_id": "TTTC8434R",
            "Content-Type": "application/json",
        }

        params = {
            "CANO": self.acnt_api_id,
            "ACNT_PRDT_CD": "01",
            "INQR_DVSN_CD": "00",
            "INQR_DVSN_CD2": "00",
            "CTX_AREA_FK": "",
            "CTX_AREA_NK": "",
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            result = response.json()

            if result.get("rt_cd") != "0":
                print(f"API Error: {result.get('msg1')}")
                return []

            # Parse trade records
            trades = []
            if "output1" in result:
                for item in result["output1"]:
                    trade = {
                        "ord_no": item.get("ODNO"),
                        "stk_cd": item.get("SLN_ORD_1"),
                        "stk_nm": item.get("SLN_ORD_2", ""),
                        "io_tp_nm": item.get("SL_TP_NM", ""),  # 매도/매수
                        "crd_class": item.get("LOAN_DT") and "CREDIT" or "CASH",
                        "trade_date": self._parse_date(item.get("ORD_DT")),
                        "ord_tm": item.get("ORD_TM", ""),
                        "cntr_qty": int(item.get("SL_ORD_QTY", 0)),
                        "cntr_uv": int(item.get("SL_ORD_UNPR", 0)),
                        "loan_dt": item.get("LOAN_DT"),
                    }
                    trades.append(trade)

            return trades

        except Exception as e:
            print(f"✗ Failed to fetch trade history: {e}")
            raise

    def get_holdings(self) -> List[Dict[str, Any]]:
        """
        Fetch current holdings from Kiwoom API.

        Returns:
            List of holding records for today
        """
        token = self.get_access_token()

        # API endpoint for holdings
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"

        headers = {
            "Authorization": f"Bearer {token}",
            "appKey": self.app_key,
            "appSecret": self.secret_key,
            "tr_id": "TTTC8434R",
            "Content-Type": "application/json",
        }

        params = {
            "CANO": self.acnt_api_id,
            "ACNT_PRDT_CD": "01",
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            result = response.json()

            if result.get("rt_cd") != "0":
                print(f"API Error: {result.get('msg1')}")
                return []

            # Parse holdings
            holdings = []
            snapshot_date = date.today()

            if "output1" in result:
                for item in result["output1"]:
                    holding = {
                        "snapshot_date": snapshot_date,
                        "stk_cd": item.get("PDNO"),
                        "stk_nm": item.get("PRDT_NAME", ""),
                        "rmnd_qty": int(item.get("HLDG_QTY", 0)),
                        "avg_prc": int(item.get("PCHS_AVG_PRIC", 0)),
                        "cur_prc": int(item.get("PRPR", 0)),
                        "loan_dt": item.get("LOAN_DT"),
                        "crd_class": item.get("LOAN_DT") and "CREDIT" or "CASH",
                    }
                    holdings.append(holding)

            return holdings

        except Exception as e:
            print(f"✗ Failed to fetch holdings: {e}")
            raise

    def get_account_summary(self) -> Dict[str, Any]:
        """
        Fetch account summary from Kiwoom API.

        Returns:
            Account summary with portfolio value and invested amount
        """
        token = self.get_access_token()

        # API endpoint for account summary
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"

        headers = {
            "Authorization": f"Bearer {token}",
            "appKey": self.app_key,
            "appSecret": self.secret_key,
            "tr_id": "TTTC8434R",
            "Content-Type": "application/json",
        }

        params = {
            "CANO": self.acnt_api_id,
            "ACNT_PRDT_CD": "01",
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            result = response.json()

            if result.get("rt_cd") != "0":
                print(f"API Error: {result.get('msg1')}")
                return {}

            # Parse account summary from output2
            if "output2" in result:
                summary = result["output2"][0] if result["output2"] else {}
                return {
                    "snapshot_date": date.today(),
                    "aset_evlt_amt": int(summary.get("TOTA_ASST_EVLU_AMNT", 0)),
                    "tot_est_amt": int(summary.get("TOTA_ASST_EVLU_AMNT", 0)),
                    "invt_bsamt": int(summary.get("PCHS_SMAMT", 0)),
                }

            return {}

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
) -> int:
    """
    Fetch trade history from Kiwoom API and save to asset database.

    Args:
        conn: Database connection

    Returns:
        Number of records synced
    """
    print("Fetching trade history from Kiwoom API...")

    try:
        client = KiwoomAPIClient()
        trades = client.get_account_trade_history()

        if not trades:
            print("No trade history found from Kiwoom API")
            return 0

        # Clear existing data
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE account_trade_history")
        conn.commit()
        print(f"✓ Cleared existing trade history")

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

        with conn.cursor() as cur:
            for trade in trades:
                try:
                    cur.execute(insert_sql, trade)
                except pymysql.err.IntegrityError:
                    # Skip duplicate entries
                    continue

        conn.commit()
        print(f"✓ Inserted {len(trades)} trade records from Kiwoom API")
        return len(trades)

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
        client = KiwoomAPIClient()
        holdings = client.get_holdings()

        if not holdings:
            print("No holdings found from Kiwoom API")
            return 0

        snapshot_date = date.today()

        # Clear existing data for today
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM holdings WHERE snapshot_date = %s",
                (snapshot_date,),
            )
        conn.commit()
        print(f"✓ Cleared existing holdings for {snapshot_date}")

        # Insert new records
        insert_sql = """
            INSERT INTO holdings (
                snapshot_date, stk_cd, stk_nm, rmnd_qty,
                avg_prc, cur_prc, loan_dt, crd_class
            )
            VALUES (
                %(snapshot_date)s, %(stk_cd)s, %(stk_nm)s, %(rmnd_qty)s,
                %(avg_prc)s, %(cur_prc)s, %(loan_dt)s, %(crd_class)s
            )
        """

        with conn.cursor() as cur:
            for holding in holdings:
                try:
                    cur.execute(insert_sql, holding)
                except pymysql.err.IntegrityError:
                    # Update if exists
                    update_sql = """
                        UPDATE holdings
                        SET stk_nm = %(stk_nm)s, rmnd_qty = %(rmnd_qty)s,
                            avg_prc = %(avg_prc)s, cur_prc = %(cur_prc)s, crd_class = %(crd_class)s
                        WHERE snapshot_date = %(snapshot_date)s AND stk_cd = %(stk_cd)s AND loan_dt <=> %(loan_dt)s
                    """
                    cur.execute(update_sql, holding)

        conn.commit()
        print(f"✓ Inserted/Updated {len(holdings)} holding records from Kiwoom API")
        return len(holdings)

    except Exception as e:
        print(f"✗ Failed to sync holdings: {e}")
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
        client = KiwoomAPIClient()
        summary = client.get_account_summary()

        if not summary:
            print("No account summary found from Kiwoom API")
            return 0

        # Insert or update account summary
        insert_sql = """
            INSERT INTO account_summary (
                snapshot_date, aset_evlt_amt, tot_est_amt, invt_bsamt
            )
            VALUES (
                %(snapshot_date)s, %(aset_evlt_amt)s, %(tot_est_amt)s, %(invt_bsamt)s
            )
            ON DUPLICATE KEY UPDATE
                aset_evlt_amt = VALUES(aset_evlt_amt),
                tot_est_amt = VALUES(tot_est_amt),
                invt_bsamt = VALUES(invt_bsamt)
        """

        with conn.cursor() as cur:
            cur.execute(insert_sql, summary)

        conn.commit()
        print(f"✓ Synced account summary from Kiwoom API")
        return 1

    except Exception as e:
        print(f"✗ Failed to sync account summary: {e}")
        raise
