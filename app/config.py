import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Jaipur")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")  # optional, better geocoding for Indian addresses

DATA_DIR = ROOT / "data"
VENDORS_FILE = DATA_DIR / "vendors.json"
GEOCODE_CACHE = DATA_DIR / "geocodes.json"
LEADS_FILE = DATA_DIR / "leads.csv"

MAX_TOOL_ROUNDS = 6
MAX_HISTORY_MESSAGES = 40
