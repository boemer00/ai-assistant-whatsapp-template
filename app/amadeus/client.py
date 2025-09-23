import httpx
import time
from typing import Dict, Any, List
from app.config import settings

BASE = "https://test.api.amadeus.com" if settings.AMADEUS_ENV != "production" \
       else "https://api.amadeus.com"

class AmadeusClient:
    def __init__(self):
        self._token = None
        self._exp = 0
        # Persistent HTTP client with HTTP/2 and sensible timeouts
        self._http = httpx.Client(
            http2=True,
            timeout=httpx.Timeout(connect=3.0, read=12.0, write=12.0, pool=12.0),
        )

    def _get_token(self):
        if self._token and time.time() < self._exp - 60:
            return self._token
        data = {
            "grant_type": "client_credentials",
            "client_id": settings.AMADEUS_CLIENT_ID,
            "client_secret": settings.AMADEUS_CLIENT_SECRET,
        }
        r = self._http.post(
            f"{BASE}/v1/security/oauth2/token",
            data=data,
            headers={"Accept": "application/json"},
        )
        r.raise_for_status()
        j = r.json()
        self._token = j["access_token"]
        self._exp = time.time() + j.get("expires_in", 1799)
        return self._token

    def _build_travelers(self, adults: int) -> List[Dict[str, Any]]:
        """
        Build travelers array of ADULTs with sequential string ids starting at '1'.
        """
        count = max(1, int(adults) if adults is not None else 1)
        return [{"id": str(i + 1), "travelerType": "ADULT"} for i in range(count)]

    def _build_origin_destinations(self, origin: str, destination: str,
                                   dep_date: str, ret_date: str | None) -> List[Dict[str, Any]]:
        """
        Build originDestinations per latest schema. One-way uses a single leg; if
        ret_date is provided, add a reverse leg for the return trip.
        """
        legs: List[Dict[str, Any]] = [
            {
                "id": "1",
                "originLocationCode": origin,
                "destinationLocationCode": destination,
                "departureDateTimeRange": {"date": dep_date},
            }
        ]
        if ret_date:
            legs.append({
                "id": "2",
                "originLocationCode": destination,
                "destinationLocationCode": origin,
                "departureDateTimeRange": {"date": ret_date},
            })
        return legs

    def search_flights(self, origin: str, destination: str, dep_date: str,
                       ret_date: str | None, adults: int = 1) -> Dict[str, Any]:
        print(f"[DEBUG] Amadeus search_flights called with: origin={origin}, destination={destination}, dep_date={dep_date}, ret_date={ret_date}, adults={adults}")
        token = self._get_token()
        print(f"[DEBUG] Amadeus token obtained successfully")

        # Structured body per current Amadeus Flight Offers Search schema
        body = {
            "currencyCode": "USD",
            "originDestinations": self._build_origin_destinations(
                origin=origin,
                destination=destination,
                dep_date=dep_date,
                ret_date=ret_date,
            ),
            "travelers": self._build_travelers(adults),
            "sources": ["GDS"],
            "searchCriteria": {"maxFlightOffers": 3},
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        print(f"[DEBUG] Amadeus request body: {body}")
        print(f"[DEBUG] Amadeus request URL: {BASE}/v2/shopping/flight-offers")

        # Single retry with short backoff, and extended read-timeout for background flow
        attempt = 0
        last_err = None
        while attempt < 2:
            try:
                r = self._http.post(
                    f"{BASE}/v2/shopping/flight-offers",
                    json=body,
                    headers=headers,
                    timeout=httpx.Timeout(connect=3.0, read=45.0, write=45.0, pool=12.0),
                )
                print(f"[DEBUG] Amadeus response status: {r.status_code}")
                if r.status_code != 200:
                    print(f"[DEBUG] Amadeus error response: {r.text}")
                r.raise_for_status()
                response_data = r.json()
                print(f"[DEBUG] Amadeus successful response with {len(response_data.get('data', []))} offers")
                return response_data
            except httpx.HTTPStatusError as e:
                print(f"[ERROR] Amadeus HTTP error: {e.response.status_code} - {e.response.text}")
                # Retry once only for 5xx
                if 500 <= e.response.status_code < 600 and attempt == 0:
                    attempt += 1
                    time.sleep(1.5)
                    last_err = e
                    continue
                raise
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError) as e:
                print(f"[ERROR] Amadeus connection error: {type(e).__name__}: {str(e)}")
                if attempt == 0:
                    attempt += 1
                    time.sleep(1.5)
                    last_err = e
                    continue
                raise
        # If we somehow exit loop without returning, raise last error
        if last_err:
            raise last_err
        raise RuntimeError("Flight search failed without a specific error")
