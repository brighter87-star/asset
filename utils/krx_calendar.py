from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import yfinance as yf


def is_korea_trading_day_by_samsung(check_date: date = None) -> bool:
    """
    삼성전자(005930.KS) 일봉 데이터로 특정 날짜가 거래일인지 확인.

    Args:
        check_date: 확인할 날짜 (None이면 오늘)

    Returns:
        거래일이면 True, 아니면 False
    """
    kst = ZoneInfo("Asia/Seoul")

    if check_date is None:
        check_date = datetime.now(kst).date()

    # Convert date to datetime for yfinance
    if isinstance(check_date, date) and not isinstance(check_date, datetime):
        check_dt = datetime.combine(check_date, datetime.min.time())
    else:
        check_dt = check_date

    ticker = yf.Ticker("005930.KS")  # 삼성전자

    # Fetch data around the check date
    # Get 10 days before and after to ensure we have enough data
    start_date = check_dt - timedelta(days=10)
    end_date = check_dt + timedelta(days=2)

    hist = ticker.history(start=start_date, end=end_date)

    if hist.empty:
        # 데이터 못 가져오면 보수적으로 주말만 제외
        return check_date.weekday() < 5

    # Check if check_date exists in the trading data
    trading_dates = [d.date() for d in hist.index]
    return check_date in trading_dates
