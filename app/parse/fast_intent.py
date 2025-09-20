import re
from typing import Optional
from app.llm.extract_intent import IntentSchema
from app.utils.dates import to_iso_date


PATTERNS = [
    # e.g., LHR to GRU on 2025-11-19 returning 2025-12-10, 2 adults
    re.compile(
        r"^\s*(?:from\s+)?(?P<orig>[A-Za-z\s]{2,}|[A-Za-z]{3})\s+to\s+(?P<dest>[A-Za-z\s]{2,}|[A-Za-z]{3})\s+on\s+(?P<dep>\d{4}-\d{2}-\d{2})(?:\s*(?:return|returning)\s+(?P<ret>\d{4}-\d{2}-\d{2}))?(?:\s*,?\s*(?P<pax>\d+)\s+adult(?:s)?)?\s*$",
        re.IGNORECASE,
    ),
    # e.g., MAD to BCN one-way on 2025-11-19, 1 adult
    re.compile(
        r"^\s*(?P<orig>[A-Za-z\s]{2,}|[A-Za-z]{3})\s+to\s+(?P<dest>[A-Za-z\s]{2,}|[A-Za-z]{3})\s+(?:one\-?way\s+)?on\s+(?P<dep>\d{4}-\d{2}-\d{2})(?:\s*,?\s*(?P<pax>\d+)\s+adult(?:s)?)?\s*$",
        re.IGNORECASE,
    ),
]


def _norm_place(s: str) -> str:
    return s.strip()


def fast_parse(text: str) -> Optional[IntentSchema]:
    for rx in PATTERNS:
        m = rx.match(text)
        if not m:
            continue
        orig = _norm_place(m.group("orig"))
        dest = _norm_place(m.group("dest"))
        dep = to_iso_date(m.group("dep")) if m.group("dep") else None
        ret = to_iso_date(m.group("ret")) if m.groupdict().get("ret") else None
        pax = int(m.group("pax")) if m.groupdict().get("pax") else 1
        return IntentSchema(
            origin=orig,
            destination=dest,
            departure_date=dep,
            return_date=ret,
            passengers=pax,
        )
    return None
