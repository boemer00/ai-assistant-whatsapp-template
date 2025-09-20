import pandas as pd
from typing import List, Dict

class IATADb:
    def __init__(self, csv_path: str):
        df = pd.read_csv(csv_path)
        # normalise - handle NaN values
        df["city_lower"] = df["city"].fillna("").str.lower().str.strip()
        self.by_city: Dict[str, List[str]] = {}
        for _, r in df.iterrows():
            # Skip empty or NaN city values
            if r["city_lower"] and isinstance(r["city_lower"], str):
                self.by_city.setdefault(r["city_lower"], []).append(r["iata_code"])
        self.codes = set(df["iata_code"].astype(str))

    def resolve(self, text: str) -> List[str]:
        t = text.lower().strip()
        # Exact match first
        if t in self.by_city:
            return list(set(self.by_city[t]))
        # Check if it's a 3-letter IATA code
        if len(text) == 3 and text.upper() in self.codes:
            return [text.upper()]

        # Partial match: find cities that contain the search text
        matches = []
        for city_key in self.by_city:
            # Check if search text is contained in city name
            # or if city name starts with search text
            if isinstance(city_key, str) and (t in city_key or city_key.startswith(t)):
                matches.extend(self.by_city[city_key])

        # Remove duplicates and return
        return list(set(matches)) if matches else []
