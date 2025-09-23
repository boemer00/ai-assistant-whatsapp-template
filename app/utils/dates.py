import dateparser
from datetime import datetime, timedelta
import pytz
import re

def _parse_next_weekday(text: str, base_date: datetime = None) -> datetime:
    """Parse 'next Monday', 'next Friday', etc."""
    if base_date is None:
        base_date = datetime.now()

    weekdays = {
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
        'friday': 4, 'saturday': 5, 'sunday': 6
    }

    # Extract weekday from text
    text_lower = text.lower()
    for day_name, day_num in weekdays.items():
        if day_name in text_lower:
            # Calculate days until this weekday
            days_until = (day_num - base_date.weekday()) % 7
            # If it's 0 (today) or in the past this week, add 7 days for "next"
            if 'next' in text_lower:
                if days_until <= 0:
                    days_until += 7
            elif days_until == 0:
                # "this Friday" when today is Friday means today
                pass
            return base_date + timedelta(days=days_until)
    return None

def to_iso_date(text: str, tz: str = "Europe/London") -> str:
    # First try custom parsing for relative dates like "next Friday"
    if re.search(r'\b(next|this)\s+\w+day\b', text, re.IGNORECASE):
        base_date = datetime.now(pytz.timezone(tz))
        dt = _parse_next_weekday(text, base_date)
        if dt:
            return dt.date().isoformat()

    # Fall back to dateparser for other formats
    dt = dateparser.parse(text, settings={"RELATIVE_BASE": datetime.now(pytz.timezone(tz))})
    if not dt:
        return ""
    return dt.date().isoformat()


def format_duration_minutes(total_minutes: int) -> str:
    """
    Convert duration in minutes to a compact human string, e.g. 85 -> "1h 25min".
    """
    if total_minutes is None or total_minutes < 0:
        return ""
    h = total_minutes // 60
    m = total_minutes % 60
    if h and m:
        return f"{h}h {m}min"
    if h:
        return f"{h}h"
    return f"{m}min"
