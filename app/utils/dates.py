import dateparser
from datetime import datetime, timedelta
import pytz
import re

def get_current_datetime(tz: str = "UTC") -> datetime:
    """Get current datetime with timezone (inspired by elysia approach)"""
    return datetime.now(pytz.timezone(tz))

def _parse_next_weekday(text: str, base_date: datetime = None, tz: str = "UTC") -> datetime:
    """Parse 'next Monday', 'next Friday', etc. using live current date"""
    if base_date is None:
        base_date = get_current_datetime(tz)

    weekdays = {
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
        'friday': 4, 'saturday': 5, 'sunday': 6
    }

    # Extract weekday from text
    text_lower = text.lower().strip()
    for day_name, day_num in weekdays.items():
        if day_name in text_lower:
            # Calculate days until this weekday
            current_weekday = base_date.weekday()
            days_until = (day_num - current_weekday) % 7

            # Handle "next" vs "this" logic
            if 'next' in text_lower:
                if days_until == 0:
                    # If today is Friday and we say "next Friday", mean next week
                    days_until = 7
                elif days_until <= 0:
                    days_until += 7
            elif 'this' in text_lower:
                if days_until == 0:
                    # "this Friday" when today is Friday means today
                    pass
                # For "this Friday" in the past, still get this week's Friday
            else:
                # Default: if just "Friday" without "next"/"this", assume next occurrence
                if days_until == 0:
                    days_until = 7

            return base_date + timedelta(days=days_until)
    return None

def to_iso_date(text: str, tz: str = "UTC") -> str:
    """Convert text to ISO date using live current time (inspired by elysia format_datetime)"""

    # Handle relative weekdays first with live current time
    if re.search(r'\b(next|this)?\s*(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', text, re.IGNORECASE):
        base_date = get_current_datetime(tz)
        dt = _parse_next_weekday(text, base_date, tz)
        if dt:
            return dt.date().isoformat()

    # Handle simple relative terms
    text_lower = text.lower().strip()
    base_date = get_current_datetime(tz)

    if text_lower == 'today':
        return base_date.date().isoformat()
    elif text_lower == 'tomorrow':
        return (base_date + timedelta(days=1)).date().isoformat()
    elif text_lower == 'yesterday':
        return (base_date - timedelta(days=1)).date().isoformat()

    # Fall back to dateparser for other formats (with current time as base)
    dt = dateparser.parse(text, settings={"RELATIVE_BASE": base_date})
    if dt:
        return dt.date().isoformat()

    return ""


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
