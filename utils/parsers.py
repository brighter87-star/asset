from datetime import datetime
from typing import Any


def to_int(value: str) -> int:
    if value is None or value == "":
        return 0
    return int(float(value))


def to_float(value: str) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def to_decimal_str(v: Any) -> str | None:
    """DECIMAL 컬럼용. 빈 값이면 None."""
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.upper() == "NULL":
        return None
    return s


def to_date_yyyy_mm_dd(trade_date: str) -> str:
    """'YYYYMMDD' or 'YYYY-MM-DD' -> 'YYYY-MM-DD'"""
    td = trade_date.strip()
    if len(td) == 8 and td.isdigit():
        return datetime.strptime(td, "%Y%m%d").strftime("%Y-%m-%d")
    # 이미 YYYY-MM-DD 라고 가정
    return td
