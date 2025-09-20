from app.parse.fast_intent import fast_parse


def test_fast_parse_round_trip_with_pax():
    r = fast_parse("LHR to GRU on 2025-11-19 returning 2025-12-10, 2 adults")
    assert r is not None
    assert r.origin.lower().startswith("lhr")
    assert r.destination.lower().startswith("gru")
    assert r.departure_date == "2025-11-19"
    assert r.return_date == "2025-12-10"
    assert r.passengers == 2


def test_fast_parse_one_way():
    r = fast_parse("MAD to BCN on 2025-11-15, 1 adult")
    assert r is not None
    assert r.origin.lower().startswith("mad")
    assert r.destination.lower().startswith("bcn")
    assert r.departure_date == "2025-11-15"
    assert r.return_date in (None, "")
    assert r.passengers == 1


def test_fast_parse_from_to():
    r = fast_parse("from London to Sao Paulo on 2025-11-19 returning 2025-12-10")
    assert r is not None
    assert r.origin.lower().startswith("london")
    assert r.destination.lower().startswith("sao paulo")
    assert r.departure_date == "2025-11-19"
    assert r.return_date == "2025-12-10"
    assert r.passengers == 1
