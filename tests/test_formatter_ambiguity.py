from app.formatters.whatsapp import format_ambiguity


def test_format_ambiguity_city_groups():
    msg = format_ambiguity("NYC", [], "Holland", ["AMS", "RTM", "EIN"])  # NYC group + dest list
    assert "JFK" in msg and "LGA" in msg and "EWR" in msg
    assert "AMS" in msg and "RTM" in msg
    assert "3-letter code" in msg
