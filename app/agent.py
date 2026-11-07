"""Conversation loop: Groq (OpenAI-compatible) chat completions + local tool calling."""
import json
import re
import time
from datetime import date

from openai import BadRequestError, OpenAI, RateLimitError

from . import config, tools

SYSTEM_PROMPT = """You are Magick AI, the friendly assistant for MagickWorld (magickworld.in), a guide for parents and families to kids' classes, play spaces, shops, celebrations, health & wellness and experiences. Currently live in {city}; a few vendors are in other cities or online.

How to help:
- Understand what the family needs (activity, child's age, locality, budget, online/offline, timings). Ask ONE short question at a time, and only what's needed to narrow results. Don't re-ask anything already said.
- Before naming vendors or saying what is offered, call search_vendors (or browse_catalog). Pass the activity plus close synonyms as keywords.
- When search results show real variety (e.g. different styles, online vs offline, price bands), offer those as choices. Only offer choices that actually appear in the results; never invent styles, vendors, prices, timings or locations.
- Ask for the user's locality when location matters (classes, play zones, venues) and pass it as `near`.
- Recommend at most 3 vendors at a time: name, one line on why it fits, price and ages. Mention distance only if the tool returned it. If price is "Price on request", say so.
- If budget is vague ("low", "high"), use the prices in the results to suggest a range, or ask for a number.
- If nothing matches, say so honestly, suggest the closest alternative (nearby category, online option, or another city) and suggest browsing magickworld.in.
- When the user wants to book or contact a vendor, share that vendor's listing link (contact options are on the listing page). Don't ask for phone numbers.
- Don't share vendor contact person names or emails; point to the listing page instead.
- Stays (hotels, resorts, homestays) are not listed on MagickWorld yet. If asked, say stays are coming soon, then offer related experiences (e.g. day trips, safaris, the overnight campout) using search_vendors with category 'Experiences'. Never present a class, shop or clinic as a place to stay.
- When sharing a link, write it as a markdown link, e.g. [View listing](https://magickworld.in/listing/...). Only use URLs that came from tool results.
- If asked your name, you are Magick AI.
- Stay on MagickWorld topics. Keep replies short, warm and conversational (2–5 sentences), in the user's language (English or Hinglish/Hindi is fine).
Today is {today}."""

_client = None


def client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.GROQ_API_KEY, base_url=config.LLM_BASE_URL, timeout=120, max_retries=0)  # wait up to 2 min for Groq before showing the error
    return _client


SESSIONS: dict[str, list] = {}


def _complete(llm, messages):
    """One Groq call. Retries once when Groq rejects a malformed tool call (a known, occasional model glitch)."""
    bad_requests = 0
    for attempt in range(4):
        try:
            return llm.chat.completions.create(model=config.LLM_MODEL, messages=messages, tools=tools.TOOL_SCHEMAS,
                                               tool_choice="auto", temperature=0.3)
        except RateLimitError as e:
            # free tier: tokens-per-minute limit. Groq says how long to wait ("try again in 7.08s"); wait and retry.
            m = re.search(r"try again in ([\d.]+)s", str(e))
            wait = min(float(m.group(1)) + 0.5 if m else 10, 30)
            print(f"groq rate limit, waiting {wait:.1f}s (attempt {attempt + 1})")
            if attempt == 3:
                raise
            time.sleep(wait)
        except BadRequestError as e:
            print(f"groq bad request (attempt {attempt + 1}):", str(e)[:300])
            bad_requests += 1
            if "tool" not in str(e).lower() or bad_requests == 2:
                raise


LLM_FIELDS = ("id", "name", "ages", "price", "mode", "city", "address", "distance_km", "about", "listing_url", "matched")


def _for_llm(result):
    """Smaller copy of a tool result for the model (saves tokens; cards keep the full data)."""
    if not isinstance(result, dict) or "results" not in result:
        return result
    slim = []
    for c in result["results"]:
        c = {k: c.get(k) for k in LLM_FIELDS if c.get(k) not in (None, [], "")}
        if c.get("address"):
            c["address"] = c["address"][:90]
        if c.get("about"):
            c["about"] = c["about"][:180]
        slim.append(c)
    return {"total_matches": result["total_matches"], "results": slim, "note": result.get("note")}


def _compact_old_turns(history):
    """Once a turn is answered, shrink its tool results to id/name/price/link so history stays small."""
    for m in history:
        if m["role"] == "tool" and not m.get("_compact"):
            try:
                data = json.loads(m["content"])
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and "results" in data:
                data = {"results": [{k: r.get(k) for k in ("id", "name", "price", "listing_url")} for r in data["results"]]}
            elif isinstance(data, dict) and "id" in data and "name" in data:  # vendor details
                data = {k: data.get(k) for k in ("id", "name", "price", "listing_url")}
            m["content"] = json.dumps(data, ensure_ascii=False)
            m["_compact"] = True


def _run_tool(name, args, session_id):
    fn = tools.FUNCTIONS.get(name)
    if not fn:
        return {"error": f"unknown tool {name}"}
    if name == "save_lead":
        args["session_id"] = session_id
    try:
        return fn(**args)
    except TypeError as e:
        return {"error": f"bad arguments: {e}"}


def chat(session_id: str, user_message: str, llm=None):
    """Returns {"reply": str, "cards": [vendor cards mentioned in the reply]}."""
    llm = llm or client()
    history = SESSIONS.setdefault(session_id, [])
    history.append({"role": "user", "content": user_message})

    system = {"role": "system", "content": SYSTEM_PROMPT.format(city=config.DEFAULT_CITY, today=date.today())}
    seen_cards = {}

    for _ in range(config.MAX_TOOL_ROUNDS):
        recent = history[-config.MAX_HISTORY_MESSAGES:]
        while recent and recent[0]["role"] == "tool":
            recent = recent[1:]  # a tool message can't start the context
        resp = _complete(llm, [system] + [{k: v for k, v in m.items() if k != "_compact"} for m in recent])
        msg = resp.choices[0].message
        if not msg.tool_calls:
            reply = (msg.content or "").strip()
            history.append({"role": "assistant", "content": reply})
            _compact_old_turns(history)
            cards = [c for c in seen_cards.values() if c["name"].lower() in reply.lower()]
            return {"reply": reply, "cards": cards[:3]}

        history.append({"role": "assistant", "content": msg.content or "",
                        "tool_calls": [{"id": tc.id, "type": "function",
                                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                                       for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _run_tool(tc.function.name, args, session_id)
            for c in (result.get("results") or [result] if isinstance(result, dict) else []):
                if isinstance(c, dict) and "id" in c and "name" in c:
                    seen_cards[c["id"]] = {k: c.get(k) for k in
                                           ("id", "name", "ages", "price", "address", "distance_km", "listing_url", "image")}
            history.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(_for_llm(result), ensure_ascii=False)})

    fallback = "Sorry, I got a bit stuck there. Could you rephrase that?"
    history.append({"role": "assistant", "content": fallback})
    return {"reply": fallback, "cards": []}
