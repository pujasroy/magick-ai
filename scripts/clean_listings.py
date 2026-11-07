"""Clean the MagickWorld WordPress (Listeo) listings export into a bot-ready vendor table.

Usage: python clean_listings.py <export.xlsx> [out_prefix]
Outputs: <out_prefix>.csv and <out_prefix>.json
"""
import html
import json
import re
import sys

import pandas as pd

AGE_BUCKETS = {"03-years": (0, 3), "36-years": (3, 6), "710-years": (7, 10), "11-years": (11, 18)}
CITIES = ["Jaipur", "Delhi", "Gurgaon", "Gurugram", "Noida", "Mumbai", "Bangalore", "Bengaluru", "Pune", "Udaipur", "Bhopal", "Goa", "Jodhpur", "Kolkata", "Hyderabad", "Chennai"]


def tags(val, prefix):
    """'_sub_category_art|_sub_category_music' -> ['art', 'music']"""
    if pd.isna(val):
        return []
    return [p.replace(prefix, "").strip() for p in str(val).split("|") if p.strip()]


def money(val):
    """'Rs. 500' -> 500, '5000+' -> 5000, 'na' -> None"""
    if pd.isna(val):
        return None
    m = re.search(r"\d[\d,]*", str(val))
    return int(m.group().replace(",", "")) if m else None


def text(val):
    if pd.isna(val):
        return ""
    s = re.sub(r"<[^>]+>", " ", str(val))
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def city_of(address):
    a = str(address or "")
    if a.strip().lower() == "online":
        return "Online"
    for c in CITIES:
        if c.lower() in a.lower():
            return {"Gurugram": "Gurgaon", "Bengaluru": "Bangalore"}.get(c, c)
    return None


def url(val):
    v = str(val).strip() if not pd.isna(val) else ""
    return v if v.startswith("http") else None


def main(path, out="vendors_clean"):
    d = pd.read_excel(path)
    rows = []
    for _, r in d.iterrows():
        cats = tags(r["MagickGuides Categories"], "") or ["Experiences"]  # uncategorised rows are the experiences
        ages = [AGE_BUCKETS[a] for a in tags(r["_age_groups_served"], "_age_groups_served_") if a in AGE_BUCKETS]
        pmin, pmax = money(r["_price_min"]), money(r["_price_max"])
        address = text(r["_address"])
        address = "" if address in ("#", "India") else address
        rows.append({
            "id": int(r["id"]),
            "name": text(r["Title"]),
            "categories": cats,
            "subcategories": tags(r["_sub_category"], "_sub_category_"),
            "business_types": tags(r["_business_type"], "_business_type_"),
            "age_min": min(a[0] for a in ages) if ages else None,
            "age_max": max(a[1] for a in ages) if ages else None,
            "mode": tags(r["_mode_of_operation"], "_mode_of_operation_")[:1] or [None],
            "price_min": pmin if pmin is not None else pmax,
            "price_max": pmax if pmax is not None else pmin,
            "pricing_type": (tags(r["_pricing_type"], "_pricing_type_") or [None])[0],
            "frequency": (tags(r["_frequency"], "_frequency_") or [None])[0],
            "audience": None if pd.isna(r["_mw_audience"]) else r["_mw_audience"],
            "languages": tags(r["_languages_supported"], "_languages_supported_"),
            "address": address or None,
            "city": city_of(address),
            "directions_url": url(r["_directions_url"]),
            "lat": None, "lng": None,  # fill via geocoding step
            "description": text(r["Content"]) or text(r["_one_line_description"]),
            "one_liner": text(r["_one_line_description"]) or None,
            "contact_name": text(r["_contact_person_name"]) or None,
            "contact_email": text(r["_contact_person_email"]) or None,
            "instagram": url(r["_instagram"]),
            "website": url(r["_website"]),
            "listing_url": r["Permalink"],
            "image": url(r["Image Featured"]),
        })
    for row in rows:
        row["mode"] = row["mode"][0]
    df = pd.DataFrame(rows)
    df.to_json(f"{out}.json", orient="records", indent=2, force_ascii=False)
    flat = df.copy()
    for c in ["categories", "subcategories", "business_types", "languages"]:
        flat[c] = flat[c].apply(lambda x: "|".join(x))
    flat.to_csv(f"{out}.csv", index=False)
    return df


if __name__ == "__main__":
    main(*sys.argv[1:])
