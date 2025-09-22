from app.session.merge import extract_codes, merge_message, is_ready_for_confirmation, is_ready_to_search


def test_extract_codes_dedup():
    assert extract_codes("JFK and AMS and JFK") == ["JFK", "AMS"]


def test_merge_assigns_pending_sides():
    state = {"intent": {}}
    out = merge_message(state, "JFK and AMS", ["JFK", "LGA", "EWR"], ["AMS", "RTM"])
    assert out.get("origin_code") == "JFK"
    assert out.get("destination_code") == "AMS"


def test_ready_for_confirmation_and_search():
    state = {"intent": {"departure_date": "2025-11-19"}, "origin_code": "JFK", "destination_code": "AMS"}
    assert is_ready_for_confirmation(state)
    state["confirmed"] = True
    assert is_ready_to_search(state)

