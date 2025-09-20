from typing import List
from app.types import FlightOption
from datetime import datetime

def iso_to_minutes(dur: str) -> int:
    # naive 'PT#H#M'
    h, m = 0, 0
    try:
        t = dur.replace("PT","").lower()
        if "h" in t:
            h = int(t.split("h")[0])
            t = t.split("h")[1]
        if "m" in t:
            m = int(t.replace("m",""))
    except:
        pass
    return h*60 + m

def summarize_segments(itin) -> tuple[str, str, str]:
    # returns (summary, dep_iso, arr_iso)
    segs = []
    dep_iso, arr_iso = None, None
    for s in itin["segments"]:
        if dep_iso is None:
            dep_iso = s["departure"]["at"]
        arr_iso = s["arrival"]["at"]
        segs.append(f'{s["departure"]["iataCode"]}→{s["arrival"]["iataCode"]}')
    stops = len(itin["segments"]) - 1
    return f'{" / ".join(segs)} ({stops} stop{"s" if stops!=1 else ""})', dep_iso, arr_iso

def from_amadeus(json_obj) -> List[FlightOption]:
    items = []
    for o in json_obj.get("data", []):
        price_total = float(o["price"]["grandTotal"])
        currency = o["price"]["currency"]
        dur = o["itineraries"][0]["duration"]
        total_min = iso_to_minutes(dur)
        seg_summary, dep_iso, arr_iso = summarize_segments(o["itineraries"][0])
        carrier = o["validatingAirlineCodes"][0] if o.get("validatingAirlineCodes") else "N/A"
        items.append(FlightOption(
            id=o.get("id", ""),
            price_total=price_total,
            currency=currency,
            duration_iso=dur,
            total_duration_minutes=total_min,
            carrier=carrier,
            segment_summary=seg_summary,
            departure_iso=dep_iso,
            arrival_iso=arr_iso,
        ))
    return items
