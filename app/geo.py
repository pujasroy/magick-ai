"""Geocoding with a JSON cache. Uses Google Geocoding if GOOGLE_MAPS_API_KEY is set, else OpenStreetMap Nominatim."""
import json
import math
import time

import httpx

from . import config

_cache = None


def _load():
    global _cache
    if _cache is None:
        _cache = json.loads(config.GEOCODE_CACHE.read_text()) if config.GEOCODE_CACHE.exists() else {}
    return _cache


def _save():
    config.GEOCODE_CACHE.write_text(json.dumps(_load(), indent=1, ensure_ascii=False))


def geocode(query: str, city: str | None = None):
    """Return (lat, lng) or None. Results (including misses) are cached."""
    q = query.strip()
    if city and city.lower() not in q.lower():
        q = f"{q}, {city}"
    q = f"{q}, India" if "india" not in q.lower() else q
    cache = _load()
    if q in cache:
        return tuple(cache[q]) if cache[q] else None
    result = None
    try:
        if config.GOOGLE_MAPS_API_KEY:
            r = httpx.get("https://maps.googleapis.com/maps/api/geocode/json",
                          params={"address": q, "key": config.GOOGLE_MAPS_API_KEY, "region": "in"}, timeout=10)
            res = r.json().get("results") or []
            if res:
                loc = res[0]["geometry"]["location"]
                result = (loc["lat"], loc["lng"])
        else:
            r = httpx.get("https://nominatim.openstreetmap.org/search",
                          params={"q": q, "format": "json", "limit": 1, "countrycodes": "in"},
                          headers={"User-Agent": "magickworld-chatbot/0.1"}, timeout=10)
            res = r.json()
            if res:
                result = (float(res[0]["lat"]), float(res[0]["lon"]))
            time.sleep(1)  # Nominatim usage policy: max 1 request/second
    except Exception:
        return None  # network error: don't cache, try again next time
    cache[q] = list(result) if result else None
    _save()
    return result


def km(a, b):
    """Haversine distance in km between (lat, lng) pairs."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))
