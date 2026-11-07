"""Tools the LLM can call. Each returns JSON-serialisable data built only from the listings file."""
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime

from . import config, geo

VENDORS: list[dict] = []
BY_ID: dict[int, dict] = {}


def load_vendors():
    global VENDORS, BY_ID
    VENDORS = json.loads(config.VENDORS_FILE.read_text())
    BY_ID = {v["id"]: v for v in VENDORS}
    return len(VENDORS)


load_vendors()


# ---------- helpers ----------

def _norm(s):
    return (s or "").lower().replace("-", " ").replace("&", "and")


def _kw_pattern(kw):
    # match at word start so "dance" finds "dance"/"dancing" (via stem) but never "guidance"
    stem = kw.lower().strip()
    if len(stem) > 4 and stem.endswith("e"):
        stem = stem[:-1]
    return re.compile(r"\b" + re.escape(stem), re.I)


def _price_text(v):
    lo, hi, unit = v.get("price_min"), v.get("price_max"), v.get("pricing_type")
    unit = {"per-month": "/month", "per-session": "/session", "starting-from": " onwards",
            "fixed-price": " (fixed)"}.get(unit, "")
    if lo is None and hi is None:
        return "Price on request"
    if lo == 0 and hi == 0:
        return "Free"
    if unit == " onwards" or lo == hi or hi is None:
        return f"₹{lo:,.0f}{unit}"
    return f"₹{lo:,.0f}–{hi:,.0f}{unit}"


def _age_text(v):
    lo, hi = v.get("age_min"), v.get("age_max")
    if lo is None or (lo == 0 and hi >= 18):
        return "All ages"
    if hi >= 18:
        return f"{int(lo)}+ yrs"
    return f"{int(lo)}–{int(hi)} yrs"


def _in_city(v, city, include_online):
    if not city:
        return True
    if (v.get("city") or "").lower() == city.lower():
        return True
    if v.get("city") is None and city.lower() == config.DEFAULT_CITY.lower():
        return True  # address doesn't name a city; most such listings are local, so keep them
    if include_online and (v.get("city") == "Online" or v.get("mode") == "online"):
        return True
    return False


def _coords(v):
    if v.get("lat") is not None:
        return (v["lat"], v["lng"])
    return None


def card(v, distance_km=None, snippet_len=280):
    d = v.get("description") or ""
    return {
        "id": v["id"],
        "name": v["name"],
        "categories": v["categories"],
        "subcategories": v["subcategories"],
        "ages": _age_text(v),
        "price": _price_text(v),
        "mode": v.get("mode"),
        "city": v.get("city"),
        "address": v.get("address"),
        "distance_km": round(distance_km, 1) if distance_km is not None else None,
        "about": d[:snippet_len] + ("…" if len(d) > snippet_len else ""),
        "listing_url": v.get("listing_url"),
        "image": v.get("image"),
    }


# ---------- tools ----------

def browse_catalog(city: str | None = None, category: str | None = None):
    """Category -> subcategory counts for a city, so the bot knows what exists."""
    city = city or config.DEFAULT_CITY
    tree = defaultdict(Counter)
    for v in VENDORS:
        if not _in_city(v, city, include_online=False):
            continue
        for c in v["categories"]:
            if category and c.lower() != category.lower():
                continue
            for s in v["subcategories"] or ["other"]:
                tree[c][s.replace("-", " ")] += 1
    return {"city": city, "catalog": {c: dict(s.most_common()) for c, s in tree.items()}}


def search_vendors(keywords: list[str] | None = None, category: str | None = None, city: str | None = None,
                   child_age: float | None = None, budget_max: float | None = None, mode: str | None = None,
                   near: str | None = None, include_online: bool = False, limit: int = 5):
    city = city or config.DEFAULT_CITY
    pats = [(k, _kw_pattern(k)) for k in (keywords or []) if k and k.strip()]
    user_loc = geo.geocode(near, city) if near else None

    results = []
    for v in VENDORS:
        if not _in_city(v, city, include_online):
            continue
        if category and category.lower() not in [c.lower() for c in v["categories"]]:
            continue
        if mode and mode != "any" and v.get("mode") not in (mode, "both", None):
            continue
        if child_age is not None and v.get("age_min") is not None:
            if not (v["age_min"] <= child_age <= v["age_max"]):
                continue
        price_unknown = v.get("price_min") is None
        if budget_max is not None and not price_unknown and v["price_min"] > budget_max:
            continue

        score, matched = 0.0, []
        if pats:
            tags = _norm(" ".join(v["subcategories"] + v["business_types"]))
            name, desc = v["name"], v.get("description") or ""
            for k, p in pats:
                s = 3 if p.search(tags) else 2 if p.search(name) else 1 if p.search(desc) else 0
                if s:
                    score += s
                    matched.append(k)
            if not matched:
                continue

        dist = None
        if user_loc and _coords(v):
            dist = geo.km(user_loc, _coords(v))
        elif near and near.lower() in (v.get("address") or "").lower():
            score += 1  # same locality mentioned in address
        if budget_max is not None and price_unknown:
            score -= 0.5  # keep, but rank below vendors known to fit the budget

        c = card(v, dist)
        c["matched"] = matched
        results.append((score, dist, c))

    # best keyword match first, then nearest (unknown distance last)
    results.sort(key=lambda r: (-r[0], r[1] if r[1] is not None else 1e9))
    out = [r[2] for r in results[:max(1, min(limit, 10))]]
    note = None
    if near and not user_loc:
        note = "Could not locate that place; results are not sorted by distance."
    elif near and not any(r["distance_km"] is not None for r in out):
        note = "Exact locations for these vendors aren't available yet, so distance can't be shown."
    return {"total_matches": len(results), "results": out, "note": note,
            "filters": {"city": city, "keywords": keywords, "category": category, "child_age": child_age,
                        "budget_max": budget_max, "mode": mode, "near": near}}


def get_vendor_details(vendor_id: int):
    v = BY_ID.get(int(vendor_id))
    if not v:
        return {"error": "No vendor with that id."}
    c = card(v, snippet_len=2000)
    c.update({k: v.get(k) for k in ("frequency", "languages", "directions_url", "instagram", "website", "one_liner")})
    return c


def save_lead(name: str, phone: str, interest: str, vendor_ids: list[int] | None = None, notes: str | None = None,
              session_id: str | None = None):
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 10:
        return {"ok": False, "error": "Phone number looks incomplete; ask the user to re-check it."}
    new = not config.LEADS_FILE.exists()
    with config.LEADS_FILE.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "session_id", "name", "phone", "interest", "vendors", "notes"])
        vendors = "; ".join(BY_ID[i]["name"] for i in (vendor_ids or []) if i in BY_ID)
        w.writerow([datetime.now().isoformat(timespec="seconds"), session_id, name, digits[-10:], interest, vendors, notes])
    return {"ok": True}


# ---------- schemas for the LLM ----------

CATEGORIES = ["Learn", "Play", "Shop", "Celebrate", "Health & Wellness", "Experiences", "Community"]

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "browse_catalog",
        "description": "See which categories and subcategories of vendors exist in a city, with counts. Use when the user is browsing or asks what's available.",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string", "description": "City, default Jaipur"},
            "category": {"type": "string", "enum": CATEGORIES}}}}},
    {"type": "function", "function": {
        "name": "search_vendors",
        "description": "Search vendor listings. Matches keywords against subcategory tags, names and descriptions, so pass the activity plus close synonyms (e.g. ['dance','kathak','hip hop']). Call it before naming any vendor or claiming what's offered.",
        "parameters": {"type": "object", "properties": {
            "keywords": {"type": "array", "items": {"type": "string"}, "description": "Activity/product words and synonyms"},
            "category": {"type": "string", "enum": CATEGORIES},
            "city": {"type": "string", "description": "City, default Jaipur"},
            "child_age": {"type": "number", "description": "Child's age in years, if known"},
            "budget_max": {"type": "number", "description": "Max price in INR, if user gave a budget"},
            "mode": {"type": "string", "enum": ["online", "offline", "any"]},
            "near": {"type": "string", "description": "User's locality/landmark, e.g. 'Mansarovar'"},
            "include_online": {"type": "boolean", "description": "Also include online-only vendors"},
            "limit": {"type": "integer", "description": "Max results (default 5)"}}}}},
    {"type": "function", "function": {
        "name": "get_vendor_details",
        "description": "Full details for one vendor (description, contact links, frequency, languages, directions).",
        "parameters": {"type": "object", "properties": {"vendor_id": {"type": "integer"}}, "required": ["vendor_id"]}}},
    {"type": "function", "function": {
        "name": "save_lead",
        "description": "Save the user's contact details so the MagickWorld team can call them back. Only call after the user has given their name and phone number and agreed to be contacted.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "phone": {"type": "string"},
            "interest": {"type": "string", "description": "What they're looking for, incl. child age, locality, budget"},
            "vendor_ids": {"type": "array", "items": {"type": "integer"}},
            "notes": {"type": "string"}}, "required": ["name", "phone", "interest"]}}},
]

# Demo build: lead capture switched off (remove this line to re-enable save_lead)
TOOL_SCHEMAS = [t for t in TOOL_SCHEMAS if t["function"]["name"] != "save_lead"]

FUNCTIONS = {"browse_catalog": browse_catalog, "search_vendors": search_vendors,
             "get_vendor_details": get_vendor_details, "save_lead": save_lead}
