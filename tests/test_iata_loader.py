from app.iata.lookup import IATADb


def test_code_direct():
    db = IATADb(csv_path="data/iata/iata_codes_19_sep.csv")
    assert db.resolve("GRU") == ["GRU"]


def test_city_exact_london():
    db = IATADb(csv_path="data/iata/iata_codes_19_sep.csv")
    codes = db.resolve("London")
    # Expect several London airports
    assert any(c in codes for c in ("LHR", "LGW", "LCY"))


def test_country_exact_japan():
    db = IATADb(csv_path="data/iata/iata_codes_19_sep.csv")
    codes = db.resolve("Japan")
    assert any(c in codes for c in ("HND", "NRT"))


def test_city_country_combo():
    db = IATADb(csv_path="data/iata/iata_codes_19_sep.csv")
    codes = db.resolve("Sao Paulo, Brazil")
    # Expect GRU/CGH among results
    assert any(c in codes for c in ("GRU", "CGH"))


def test_partial_city():
    db = IATADb(csv_path="data/iata/iata_codes_19_sep.csv")
    codes = db.resolve("Lon")
    assert any(c in codes for c in ("LHR", "LGW", "LCY"))
    assert len(codes) <= 5


def test_country_alias_holland():
    db = IATADb(csv_path="data/iata/iata_codes_19_sep.csv")
    codes = db.resolve("Holland")
    # Expect Netherlands codes like AMS
    assert any(c in codes for c in ("AMS",))
