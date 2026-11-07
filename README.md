# MagickWorld chatbot (v1)

Conversational assistant that recommends MagickWorld vendors (Learn, Play, Shop, Celebrate, Health & Wellness, Experiences) from the website's listings export. LLM: Groq (OpenAI-compatible API) with local tool calling.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env          # add your GROQ_API_KEY
uvicorn app.main:app --reload
```
Open http://localhost:8000 and chat.

## Update the data (whenever listings change)

```bash
python scripts/clean_listings.py <Magickguide-export.xlsx> data/vendors
python -m scripts.geocode_vendors      # optional: adds lat/lng for "nearest" sorting
curl -X POST localhost:8000/api/reload-data   # or just restart the server
```

## How it works

```
browser ──► POST /api/chat ──► agent.chat()  ──► Groq model (system prompt + tool schemas)
                                    │  ▲
                         tool calls ▼  │ results
                         app/tools.py  (search over data/vendors.json)
```

| File | What it does |
|---|---|
| `app/agent.py` | System prompt + tool-calling loop, per-session history (in memory) |
| `app/tools.py` | `browse_catalog`, `search_vendors`, `get_vendor_details`, `save_lead` |
| `app/geo.py` | Geocoding (Google if key set, else OpenStreetMap) with a cache, distance in km |
| `app/main.py` | FastAPI: `/api/chat`, `/api/reset`, `/api/reload-data`, `/api/health` |
| `app/static/index.html` | Test chat page with vendor cards |
| `scripts/clean_listings.py` | WordPress export → `data/vendors.json` |
| `data/leads.csv` | Leads saved by the bot (created on first lead) |
| `tests/test_bot.py` | Offline tests (no API key needed): `python tests/test_bot.py` |

**Search** matches keywords against subcategory tags (strongest), vendor names, then descriptions, using word-start matching so "dance" never matches "guidance". The model is told to pass synonyms (e.g. `["dance","kathak","hip hop"]`). Filters: city, category, child age, max budget, online/offline, locality.

**Switching models:** change `LLM_MODEL` in `.env`. Any OpenAI-compatible provider works by changing `LLM_BASE_URL` too.

## Known limits (v1)

- Sessions live in memory: restart = conversations reset. Use Redis/DB before production.
- "Nearest" needs geocoded vendor addresses; ~60 listings have only "Jaipur, India".
- 96 listings have no price → shown as "Price on request".
- Before putting this on magickworld.in: restrict CORS to the site's domain, add rate limiting, and move leads from CSV into Odoo.
