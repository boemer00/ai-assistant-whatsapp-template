from typing import List
from app.types import FlightOption, RankedResults

def rank_top(options: List[FlightOption]) -> RankedResults:
    if not options:
        return RankedResults(fastest=None, cheapest=[])
    # fastest by total_duration_minutes
    sorted_by_dur = sorted(options, key=lambda x: x.total_duration_minutes)
    fastest = sorted_by_dur[0]

    # cheapest by price, excluding the exact same ID as fastest (if same)
    sorted_by_price = sorted(options, key=lambda x: x.price_total)
    cheapest = []
    for op in sorted_by_price:
        if op.id != fastest.id:
            cheapest.append(op)
        if len(cheapest) == 2:
            break
    return RankedResults(fastest=fastest, cheapest=cheapest)
