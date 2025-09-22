from app.types import RankedResults
from app.utils.dates import format_duration_minutes

def format_reply(intent, ranked: RankedResults) -> str:
    missing = []
    if not intent.origin: missing.append("origin city/airport")
    if not intent.destination: missing.append("destination city/airport")
    if not intent.departure_date: missing.append("departure date")

    if missing:
        return ("Got it. To search flights I still need: " +
                ", ".join(missing) +
                ". Example:\n“London to Sao Paulo next Friday, 2 adults”")

    if not ranked.fastest and not ranked.cheapest:
        return "Sorry, I couldn't find matching flights. Try different dates or airports?"

    def line(x):
        dur = format_duration_minutes(x.total_duration_minutes)
        return (f"• {x.carrier} | {x.segment_summary} | {dur} | "
                f"{x.currency} {x.price_total:.2f}")

    parts = [
        "Here are your top options:",
        "",
        f"FASTEST\n{line(ranked.fastest)}" if ranked.fastest else "FASTEST\n(none)",
        "",
        "CHEAPEST",
    ]
    if ranked.cheapest:
        parts += [line(c) for c in ranked.cheapest]
    else:
        parts.append("(none)")

    parts += ["", "Reply with “book”, “another date”, or change details."]
    return "\n".join(parts)


def format_ambiguity(origin_query: str | None, origin_codes: list[str],
                     dest_query: str | None, dest_codes: list[str]) -> str:
    """Friendly ambiguity prompt with metro-aware suggestions.

    Limits displayed codes to at most 5 per side and prefers well-known metro
    groups when the query matches (e.g., NYC → JFK/LGA/EWR).
    """
    def group_for(query: str | None) -> list[str]:
        if not query:
            return []
        q = query.strip().lower()
        groups: dict[str, list[str]] = {
            "nyc": ["JFK", "LGA", "EWR"],
            "new york": ["JFK", "LGA", "EWR"],
            "london": ["LHR", "LGW", "LCY", "LTN", "STN"],
            "paris": ["CDG", "ORY", "BVA"],
            "tokyo": ["HND", "NRT"],
            "sao paulo": ["GRU", "CGH", "VCP"],
            "milan": ["MXP", "LIN", "BGY"],
        }
        for k, v in groups.items():
            if q == k or k in q:
                return v
        return []

    def shortlist(query: str | None, codes: list[str]) -> list[str]:
        if codes:
            return list(dict.fromkeys(codes))[:5]
        g = group_for(query)
        return g[:5]

    def join_codes(c: list[str]) -> str:
        if not c:
            return "?"
        if len(c) == 1:
            return c[0]
        if len(c) == 2:
            return f"{c[0]} or {c[1]}"
        return ", ".join(c[:-1]) + f" or {c[-1]}"

    o = shortlist(origin_query, origin_codes)
    d = shortlist(dest_query, dest_codes)

    messages = []
    if origin_query is None or len(origin_codes) != 1:
        oq = origin_query or "origin"
        messages.append(f"Which {oq} airport should I use: {join_codes(o)}?")
    if dest_query is None or len(dest_codes) != 1:
        dq = dest_query or "destination"
        messages.append(f"And for {dq}: {join_codes(d)}?")
    messages.append("Reply with the 3-letter code.")
    return "\n".join(messages)


def format_missing_date(intent) -> str:
    return ("I still need the departure date. Example: “2025-11-19” or “next Friday”.")


def format_missing_passengers(intent) -> str:
    return ("How many travellers? Example: “2 adults”.")


def format_confirmation(intent, origin_code: str, dest_code: str) -> str:
    dep = intent.departure_date if hasattr(intent, "departure_date") else getattr(intent, "departure_date", None)
    pax = getattr(intent, "passengers", 1)
    return ("Thanks. So, just to confirm you want a flight from "
            f"{intent.origin or ''} to {intent.destination or ''} ({dest_code}) "
            f"on {dep} for {pax} people. Is this correct?")
