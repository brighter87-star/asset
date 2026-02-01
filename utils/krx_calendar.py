"""
Korean stock market trading day checker.
"""

from datetime import date


# Korean public holidays (fixed dates)
# Updated annually as needed
KOREAN_HOLIDAYS_2025 = {
    date(2025, 1, 1),   # New Year's Day
    date(2025, 1, 28),  # Seollal (Lunar New Year)
    date(2025, 1, 29),  # Seollal
    date(2025, 1, 30),  # Seollal
    date(2025, 3, 1),   # Independence Movement Day
    date(2025, 5, 5),   # Children's Day
    date(2025, 5, 6),   # Buddha's Birthday (substitute)
    date(2025, 6, 6),   # Memorial Day
    date(2025, 8, 15),  # Liberation Day
    date(2025, 10, 3),  # National Foundation Day
    date(2025, 10, 6),  # Chuseok
    date(2025, 10, 7),  # Chuseok
    date(2025, 10, 8),  # Chuseok
    date(2025, 10, 9),  # Hangul Day
    date(2025, 12, 25), # Christmas
    date(2025, 12, 31), # Year-end closing
}

KOREAN_HOLIDAYS_2026 = {
    date(2026, 1, 1),   # New Year's Day
    date(2026, 2, 16),  # Seollal (Lunar New Year)
    date(2026, 2, 17),  # Seollal
    date(2026, 2, 18),  # Seollal
    date(2026, 3, 1),   # Independence Movement Day (Sunday, substitute on 3/2)
    date(2026, 3, 2),   # Substitute holiday
    date(2026, 5, 5),   # Children's Day
    date(2026, 5, 24),  # Buddha's Birthday
    date(2026, 6, 6),   # Memorial Day
    date(2026, 8, 15),  # Liberation Day
    date(2026, 9, 24),  # Chuseok
    date(2026, 9, 25),  # Chuseok
    date(2026, 9, 26),  # Chuseok
    date(2026, 10, 3),  # National Foundation Day
    date(2026, 10, 9),  # Hangul Day
    date(2026, 12, 25), # Christmas
    date(2026, 12, 31), # Year-end closing
}

KOREAN_HOLIDAYS = KOREAN_HOLIDAYS_2025 | KOREAN_HOLIDAYS_2026


def is_korea_trading_day_by_samsung(check_date: date = None) -> bool:
    """
    Check if a date is a Korean stock market trading day.

    Trading days are weekdays (Mon-Fri) excluding Korean public holidays.

    Args:
        check_date: Date to check (None = today)

    Returns:
        True if trading day, False otherwise
    """
    if check_date is None:
        check_date = date.today()

    # Weekend check (Saturday=5, Sunday=6)
    if check_date.weekday() >= 5:
        return False

    # Holiday check
    if check_date in KOREAN_HOLIDAYS:
        return False

    return True
