import dateparser
from datetime import datetime
import pytz

def to_iso_date(text: str, tz: str = "Europe/London") -> str:
    dt = dateparser.parse(text, settings={"RELATIVE_BASE": datetime.now(pytz.timezone(tz))})
    if not dt:
        return ""
    return dt.date().isoformat()
