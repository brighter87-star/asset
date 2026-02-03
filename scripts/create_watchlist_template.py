"""
Create watchlist.xlsx template for auto trading.
"""

import pandas as pd
from pathlib import Path

# Output path
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "watchlist.xlsx"


def create_template():
    """Create watchlist.xlsx with settings and watchlist sheets."""

    # Settings sheet data
    settings_data = {
        "key": ["UNIT", "TICK_BUFFER", "STOP_LOSS_PCT", "MAX_LEVERAGE_PCT"],
        "value": [1, 3, 7.0, 120.0],
        "description": [
            "매수 유닛 수 (1 unit = 5% of assets)",
            "매수기준가 대비 틱 버퍼",
            "기본 손절률 (%)",
            "최대 주식비중 (순자산 대비 %)",
        ],
    }
    settings_df = pd.DataFrame(settings_data)

    # Watchlist sheet data (sample)
    # ticker 또는 name 중 하나만 있어도 됨 (없는 쪽은 API로 자동 조회)
    # target_price = 매수기준가 (이 가격 돌파시 매수)
    watchlist_data = {
        "name": ["삼성전자", "SK하이닉스"],  # 종목명 (또는 ticker 사용)
        "target_price": [80000, 200000],  # 매수기준가
        "stop_loss_pct": ["", 5.0],  # Empty means use default
    }
    watchlist_df = pd.DataFrame(watchlist_data)

    # Write to Excel with multiple sheets
    with pd.ExcelWriter(OUTPUT_PATH, engine="openpyxl") as writer:
        settings_df.to_excel(writer, sheet_name="settings", index=False)
        watchlist_df.to_excel(writer, sheet_name="watchlist", index=False)

    print(f"Created: {OUTPUT_PATH}")
    print("\n[settings sheet]")
    print(settings_df.to_string(index=False))
    print("\n[watchlist sheet]")
    print(watchlist_df.to_string(index=False))


if __name__ == "__main__":
    create_template()
