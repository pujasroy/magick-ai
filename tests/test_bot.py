"""Offline tests: tools on real data + the agent loop with a scripted fake LLM (no API key needed).
Run: python -m pytest -q   (or: python tests/test_bot.py)
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import agent, geo, tools  # noqa: E402

geo.geocode = lambda q, c=None: None  # no network in tests


def test_dance_finds_description_matches_not_guidance():
    r = tools.search_vendors(["dance"], child_age=6)
    names = [c["name"] for c in r["results"]]
    assert "Creative Minds academy" in names
    assert not any("Nutrition" in n for n in names)  # 'guidance' must not match 'dance'


def test_age_and_budget_filters():
    for c in tools.search_vendors(["cake"], budget_max=500, limit=10)["results"]:
        p = tools.BY_ID[c["id"]]["price_min"]
        assert p is None or p <= 500
    for c in tools.search_vendors(["art"], child_age=2, limit=10)["results"]:
        v = tools.BY_ID[c["id"]]
        assert v["age_min"] is None or v["age_min"] <= 2 <= v["age_max"]


def test_unknown_city_vendors_included_for_default_city():
    assert any(c["name"] == "Jaipur Chess Academy" for c in tools.search_vendors(["chess"])["results"])


class FakeLLM:
    """Replays: 1) a search_vendors tool call, 2) a final text answer naming a vendor."""

    def __init__(self):
        self.calls = []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            tc = NS(id="c1", function=NS(name="search_vendors",
                                         arguments=json.dumps({"keywords": ["dance"], "child_age": 6})))
            return NS(choices=[NS(message=NS(content="", tool_calls=[tc]))])
        tool_msg = kw["messages"][-1]
        assert tool_msg["role"] == "tool" and "Creative Minds" in tool_msg["content"]
        return NS(choices=[NS(message=NS(content="Creative Minds academy offers dance classes. Where in Jaipur are you?",
                                         tool_calls=None))])


def test_agent_loop_runs_tools_and_returns_cards():
    out = agent.chat("t1", "my 6 year old wants to learn dance", llm=FakeLLM())
    assert "Creative Minds" in out["reply"]
    assert out["cards"] and out["cards"][0]["name"] == "Creative Minds academy"
    assert agent.SESSIONS["t1"][-1]["role"] == "assistant"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
