"""Add lat/lng to data/vendors.json from each vendor's address (cached in data/geocodes.json).

Run after clean_listings.py:  python -m scripts.geocode_vendors
Skips vague addresses ("Jaipur, India", "Online", ...). Set GOOGLE_MAPS_API_KEY in .env for better accuracy.
"""
import json
import re

from app import config, geo

VAGUE = re.compile(r"^(jaipur|delhi|delhi ncr|india|online.*|rajasthan|[^,]{0,3})(,\s*(rajasthan|india))*$", re.I)


def main():
    vendors = json.loads(config.VENDORS_FILE.read_text())
    done = skipped = failed = 0
    for v in vendors:
        addr = (v.get("address") or "").strip()
        if not addr or VAGUE.match(addr) or addr.startswith("http") or v.get("city") in (None, "Online"):
            skipped += 1
            continue
        loc = geo.geocode(addr, v.get("city"))
        if loc:
            v["lat"], v["lng"] = loc
            done += 1
        else:
            failed += 1
    config.VENDORS_FILE.write_text(json.dumps(vendors, indent=2, ensure_ascii=False))
    print(f"geocoded {done}, skipped {skipped} (vague/online), failed {failed}")


if __name__ == "__main__":
    main()
