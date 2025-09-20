import json
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from app.amadeus.client import AmadeusClient


class DummyResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {"data": []}

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


def test_builds_expected_json_body_and_headers():
    client = AmadeusClient()

    with (
        patch.object(AmadeusClient, "_get_token", return_value="TEST_TOKEN") as _tok,
        patch("app.amadeus.client.httpx.Client.post") as mock_post,
    ):
        mock_post.return_value = DummyResponse(200, {"data": ["ok"]})

        client.search_flights(
            origin="LHR",
            destination="MAD",
            dep_date="2025-10-15",
            ret_date=None,
            adults=2,
        )

        assert mock_post.called
        url = mock_post.call_args.kwargs.get("url") or mock_post.call_args.args[0]
        assert url.endswith("/v2/shopping/flight-offers")

        headers = mock_post.call_args.kwargs.get("headers")
        assert headers["Authorization"] == "Bearer TEST_TOKEN"
        assert headers["Content-Type"] == "application/json"

        body = mock_post.call_args.kwargs.get("json")
        assert body["currencyCode"] == "USD"
        assert body["sources"] == ["GDS"]
        assert body["searchCriteria"]["maxFlightOffers"] in (3, 5)
        # originDestinations one-way
        legs = body["originDestinations"]
        assert len(legs) == 1
        assert legs[0]["originLocationCode"] == "LHR"
        assert legs[0]["destinationLocationCode"] == "MAD"
        assert legs[0]["departureDateTimeRange"]["date"] == "2025-10-15"
        # travelers two adults
        trav = body["travelers"]
        assert len(trav) == 2
        assert trav[0] == {"id": "1", "travelerType": "ADULT"}
        assert trav[1] == {"id": "2", "travelerType": "ADULT"}


def test_includes_return_date_when_provided():
    client = AmadeusClient()

    with (
        patch.object(AmadeusClient, "_get_token", return_value="TEST_TOKEN") as _tok,
        patch("app.amadeus.client.httpx.Client.post") as mock_post,
    ):
        mock_post.return_value = DummyResponse(200, {"data": ["ok"]})

        client.search_flights(
            origin="LHR",
            destination="MAD",
            dep_date="2025-10-15",
            ret_date="2025-10-22",
            adults=1,
        )

        body = mock_post.call_args.kwargs.get("json")
        legs = body["originDestinations"]
        assert len(legs) == 2
        assert legs[0]["originLocationCode"] == "LHR"
        assert legs[0]["destinationLocationCode"] == "MAD"
        assert legs[0]["departureDateTimeRange"]["date"] == "2025-10-15"
        assert legs[1]["originLocationCode"] == "MAD"
        assert legs[1]["destinationLocationCode"] == "LHR"
        assert legs[1]["departureDateTimeRange"]["date"] == "2025-10-22"
