import dateparser
from datetime import datetime
import pytz

def to_iso_date(text: str, tz: str = "Europe/London") -> str:
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
