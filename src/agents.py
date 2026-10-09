"""Agent layer. Two interchangeable backends behind one function signature.

heuristic_agent  - offline stand-in: keyword rules over the free-text notes. It is NOT an LLM.
make_llm_agent   - Claude backend (needs ANTHROPIC_API_KEY). Same input, same JSON plan out.

A plan is: {hold_reason, exclude_last, window, direction, step_scale, evidence, strength}
The engine applies the plan deterministically; the agent never writes a floor number itself.
"""
import json
import os
import re

BENIGN = ("no impact", "no change in bid flow", "auto-resolved", "cleared")
OUTAGE = ("5xx", "paused by their side", "not bidding", "gone quiet", "bid responses down")
DATA = ("ingestion lag", "incomplete", "pipeline delayed", "look short", "backfill")
SURGE = ("campaign goes live", "traffic expected", "expect higher demand", "ramping spend")
SHIFT = ("changed their bidding strategy", "new buyer onboarded")
AMBIG = ("timeouts on", "bid rate looks", "monitoring", "keeping an eye")


def _has(t, keys):
    return any(k in t for k in keys)


def heuristic_agent(ctx):
    plan = dict(hold_reason=None, exclude_last=0, window=None, direction="both", step_scale=1.0,
                evidence=[], strength="none")
    for n in ctx["notes"]:
        t = n["text"].lower()
        if _has(t, BENIGN):
            plan["evidence"].append(("benign, ignored", n["text"])); continue
        if _has(t, OUTAGE):
            plan["hold_reason"] = "insufficient_signal: demand partner outage reported, history not representative"
            plan["strength"] = "strong"; plan["evidence"].append(("outage", n["text"]))
        elif _has(t, DATA):
            plan["exclude_last"] = 2
            plan["strength"] = plan["strength"] if plan["strength"] == "strong" else "medium"
            plan["evidence"].append(("data incomplete, dropping last 2 days", n["text"]))
        elif _has(t, SURGE):
            plan["direction"] = "raise"
            plan["strength"] = plan["strength"] if plan["strength"] == "strong" else "medium"
            plan["evidence"].append(("demand surge expected, raise-only", n["text"]))
        elif _has(t, SHIFT):
            plan["window"] = 10
            plan["evidence"].append(("regime change, shortening window", n["text"]))
        elif _has(t, AMBIG):
            plan["step_scale"] = min(plan["step_scale"], 0.5)
            plan["evidence"].append(("ambiguous warning, halving the step", n["text"]))
    return plan


PROMPT = """You are the judgment layer of a CPM floor-pricing assistant for ad operations.
A deterministic statistics layer already fitted a revenue-vs-floor curve and proposes a floor.
You never output a price. You decide how far the proposal can be trusted, using the stats summary
and the recent ops notes (free text, some irrelevant, some benign, some ambiguous).

Return ONLY JSON with keys:
  hold_reason: string or null  (set when the data cannot support a move; start with "insufficient_signal:")
  exclude_last: int 0-3        (drop this many most recent days from the fit if notes show they are corrupted)
  window: int or null          (shorter fit window in days if demand has structurally changed)
  direction: "both" or "raise" (use "raise" if demand is about to rise and lowering would be wrong)
  step_scale: number 0-1       (shrink the move when evidence is ambiguous)
  evidence: list of short strings citing the note text you relied on
  strength: "none"|"weak"|"medium"|"strong"
Refuse (hold_reason) rather than guess. Ignore notes that are benign or unrelated.

CONTEXT:
{ctx}
"""


def make_llm_agent(model="claude-sonnet-5-5", log=None):
    import anthropic
    client = anthropic.Anthropic()

    def agent(ctx):
        msg = client.messages.create(model=model, max_tokens=500,
                                     messages=[{"role": "user", "content": PROMPT.format(ctx=json.dumps(ctx, default=float))}])
        txt = msg.content[0].text
        m = re.search(r"\{.*\}", txt, re.S)
        try:
            plan = json.loads(m.group(0))
        except Exception:
            plan = dict(hold_reason="insufficient_signal: unparseable agent output")
        plan.setdefault("hold_reason", None); plan.setdefault("exclude_last", 0); plan.setdefault("window", None)
        plan.setdefault("direction", "both"); plan.setdefault("step_scale", 1.0)
        plan["exclude_last"] = int(min(max(plan["exclude_last"] or 0, 0), 3))
        plan["step_scale"] = float(min(max(plan["step_scale"] or 1.0, 0.0), 1.0))
        if log is not None:
            log.append((ctx, plan))
        return plan
    return agent


if not os.environ.get("ANTHROPIC_API_KEY"):
    LLM_AVAILABLE = False
else:
    LLM_AVAILABLE = True
