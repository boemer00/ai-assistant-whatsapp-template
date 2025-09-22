from typing import List, Dict, Set
import os
import json
import csv


class IATADb:
    """Lightweight IATA database loader without pandas.

    Prefers a prebuilt JSON index if available, with CSV fallback. Provides
    O(1) exact lookups for city, country, and IATA code; partial matches fall
    back to scanning keys when needed.
    """

    def __init__(self, csv_path: str):
        self.by_city: Dict[str, List[str]] = {}
        self.by_country: Dict[str, List[str]] = {}
        self.codes: Set[str] = set()
        self.aliases: Dict[str, str] = {}
        self.country_aliases: Dict[str, str] = {
            "uk": "united kingdom",
            "gb": "united kingdom",
            "great britain": "united kingdom",
            "usa": "united states",
            "us": "united states",
            "u.s.": "united states",
            "united states of america": "united states",
            "uae": "united arab emirates",
        }

        json_path = os.path.splitext(csv_path)[0] + ".json"
        if os.path.exists(json_path):
            self._load_from_json(json_path)
        else:
            self._load_from_csv(csv_path)

        # Deduplicate lists while preserving order
        for k, lst in list(self.by_city.items()):
            seen = set()
            deduped = []
            for code in lst:
                if code not in seen:
                    seen.add(code)
                    deduped.append(code)
            self.by_city[k] = deduped
        for k, lst in list(self.by_country.items()):
            seen = set()
            deduped = []
            for code in lst:
                if code not in seen:
                    seen.add(code)
                    deduped.append(code)
            self.by_country[k] = deduped

        # Extend with pragmatic English aliases for common user phrasing
        extra_city_aliases = {
            "ny": "new york",
            "new york city": "new york",
            "sfo": "san francisco",
            "vegas": "las vegas",
            "dc": "washington",
            "washington dc": "washington",
            "heathrow": "london",
            "gatwick": "london",
            "stansted": "london",
            "luton": "london",
            "são paulo": "sao paulo",
            "rio": "rio de janeiro",
            "lisboa": "lisbon",
            "saigon": "ho chi minh city",
            "bombay": "mumbai",
            "peking": "beijing",
            "new delhi": "delhi",
            "st. petersburg": "st petersburg",
            "st. louis": "st louis",
        }
        self.aliases.update({k: v for k, v in extra_city_aliases.items()})

        extra_country_aliases = {
            "u.k.": "united kingdom",
            "england": "united kingdom",
            "scotland": "united kingdom",
            "wales": "united kingdom",
            "northern ireland": "united kingdom",
            "holland": "netherlands",
            "the netherlands": "netherlands",
            "brasil": "brazil",
            "viet nam": "vietnam",
            "turkiye": "turkey",
            "ivory coast": "cote d'ivoire",
        }
        self.country_aliases.update({k: v for k, v in extra_country_aliases.items()})

    def _load_from_json(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Aliases (city synonyms) are optional
        self.aliases = {k.strip().lower(): v.strip().lower() for k, v in data.get("aliases", {}).items()}

        # Build by_city as city_lower -> [codes]
        by_city_raw = data.get("by_city", {})
        for city_lower, entries in by_city_raw.items():
            if not city_lower:
                continue
            codes = []
            for e in entries or []:
                code = str(e.get("iata_code", "")).upper()
                if len(code) == 3:
                    codes.append(code)
                    self.codes.add(code)
            if codes:
                self.by_city[city_lower.strip()] = codes

        # Build by_country from by_code
        by_code = data.get("by_code", {})
        for code, meta in by_code.items():
            up = str(code).upper()
            if len(up) != 3:
                continue
            self.codes.add(up)
            country = str(meta.get("country", "")).strip().lower()
            if country:
                self.by_country.setdefault(country, []).append(up)

    def _load_from_csv(self, path: str) -> None:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                country = (row.get("country") or "").strip()
                city = (row.get("city") or "").strip()
                code = (row.get("iata_code") or "").strip().upper()
                if not code or len(code) != 3:
                    continue
                self.codes.add(code)
                city_lower = city.lower()
                country_lower = country.lower()
                if city_lower:
                    self.by_city.setdefault(city_lower, []).append(code)
                if country_lower:
                    self.by_country.setdefault(country_lower, []).append(code)

    def _normalise_city(self, text_lower: str) -> str:
        # apply alias if any
        return self.aliases.get(text_lower, text_lower)

    def _normalise_country(self, text_lower: str) -> str:
        return self.country_aliases.get(text_lower, text_lower)

    def resolve(self, text: str) -> List[str]:
        """Resolve a free-text input to a list of IATA airport codes.

        Resolution order: direct code -> city (alias/exact) -> country (alias/exact)
        -> city,country intersection -> partial city -> partial country.
        """
        if text is None:
            return []
        raw = text.strip()
        if not raw:
            return []
        t = raw.lower()

        # Direct IATA code
        if len(raw) == 3:
            up = raw.upper()
            if up in self.codes:
                return [up]

        # Try city,country pair if comma present
        if "," in t:
            city_part, country_part = t.split(",", 1)
            city_key = self._normalise_city(city_part.strip())
            country_key = self._normalise_country(country_part.strip())
            city_list = self.by_city.get(city_key, [])
            country_list = self.by_country.get(country_key, [])
            if city_list and country_list:
                inter = [c for c in city_list if c in set(country_list)]
                if inter:
                    return list(dict.fromkeys(inter))

        # Exact city
        city_key = self._normalise_city(t)
        if city_key in self.by_city:
            return list(self.by_city[city_key])

        # Exact country
        country_key = self._normalise_country(t)
        if country_key in self.by_country:
            return list(self.by_country[country_key])

        # Partial city match (cap to top 5 unique codes)
        matches: List[str] = []
        for city_name, codes in self.by_city.items():
            if t in city_name or city_name.startswith(t):
                matches.extend(codes)
        if matches:
            uniq = list(dict.fromkeys(matches))
            return uniq[:5]

        # Partial country match (cap to top 5 unique codes)
        matches = []
        for country_name, codes in self.by_country.items():
            if t in country_name or country_name.startswith(t):
                matches.extend(codes)
        if matches:
            uniq = list(dict.fromkeys(matches))
            return uniq[:5]

        return []
