from app.types import RankedResults

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
        return (f"• {x.segment_summary} | {x.duration_iso} | "
                f"{x.currency} {x.price_total:.2f} | {x.carrier}")

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
