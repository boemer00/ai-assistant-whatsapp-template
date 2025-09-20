from pydantic import BaseModel, Field
from typing import Optional, List

class Intent(BaseModel):
    origin: Optional[str] = Field(None, description="City or airport name/code")
    destination: Optional[str] = None
    departure_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    return_date: Optional[str] = None
    passengers: int = 1
    trip_type: str = "one_way"  # or "round_trip"
    cabin: Optional[str] = None # economy, business, first
    non_stop: bool = False
    # You can add hotel preference later

class FlightOption(BaseModel):
    id: str
    price_total: float
    currency: str
    duration_iso: str      # e.g., 'PT11H30M'
    total_duration_minutes: int
    carrier: str
    segment_summary: str   # compact "LHR→GRU (1 stop, 11h30)"
    departure_iso: str
    arrival_iso: str
    booking_code: Optional[str] = None
    deep_link: Optional[str] = None  # add later if you create links

class RankedResults(BaseModel):
    fastest: Optional[FlightOption]
    cheapest: List[FlightOption]     # top 2 cheapest (excluding fastest if dup)
