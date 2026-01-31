from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf


def is_korea_trading_day_by_samsung() -> bool:
    """
    삼성전자(005930.KS) 일봉의 마지막 날짜가 오늘이면 거래일로 본다.
    """
    kst = ZoneInfo("Asia/Seoul")
    today = datetime.now(kst).date()

    ticker = yf.Ticker("005930.KS")  # 삼성전자
    hist = ticker.history(period="7d")  # 최근 7거래일만 조회

    if hist.empty:
        # 데이터 못 가져오면 보수적으로 '거래일' 로 취급하거나, 반대로 '휴장' 처리할지 선택
        return True

    last_date = hist.index[-1].date()
    return last_date == today
