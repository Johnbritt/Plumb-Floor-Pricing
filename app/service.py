"""Recommendation logic. Wraps the research engine (src/engine.py) for live data."""
import hashlib
import json
import os
import sys
from datetime import date as _date, timedelta

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from agents import heuristic_agent  # noqa: E402
from engine import GRID, W_DAYS, decide_system  # noqa: E402

from .store import db  # noqa: E402

DEFAULT_PRM = {"v": 2, "zfull": 2.0, "rz": 2.5, "thinV": 1500.0, "nc_scale": 0.5, "zthr": 0}
MIN_HISTORY = 14
TIER_THIN, TIER_MID = 1500, 5000


def params():
    p = dict(DEFAULT_PRM)
    path = os.path.join(os.path.dirname(__file__), "..", "results", "results_v2.json")
    try:
        p.update(json.load(open(path))["world2_confirmation"]["prm"])
    except Exception:
        pass
    if os.environ.get("PLUMB_PARAMS"):
        p.update(json.loads(os.environ["PLUMB_PARAMS"]))
    return p


def agent_backend():
    """'claude' when PLUMB_AGENT=claude and a key is set, else the offline keyword stand-in."""
    if os.environ.get("PLUMB_AGENT", "heuristic").lower() == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    return "heuristic"


_llm = None


def _agent():
    global _llm
    if agent_backend() == "claude":
        if _llm is None:
            from agents import make_llm_agent
            _llm = make_llm_agent(os.environ.get("PLUMB_MODEL", "claude-sonnet-5-5"))
        return _llm
    return heuristic_agent


def d2(s):
    return _date.fromisoformat(s)


def tier_of(v):
    return "thin" if v < TIER_THIN else ("mid" if v < TIER_MID else "thick")


def _plan_for(conn, cell_id, as_of, ctx):
    """Plans are cached per (cell, as_of, notes) so an LLM is called once per decision, and not at all when there are no notes."""
    if not ctx["notes"]:
        return heuristic_agent(ctx)
    key = hashlib.sha1((agent_backend() + json.dumps([n["text"] for n in ctx["notes"]])).encode()).hexdigest()[:16]
    row = conn.execute("SELECT plan FROM plans WHERE cell_id=? AND as_of=? AND key=?", (cell_id, as_of, key)).fetchone()
    if row:
        return json.loads(row["plan"])
    plan = _agent()(ctx)
    conn.execute("INSERT OR REPLACE INTO plans VALUES (?,?,?,?)", (cell_id, as_of, key, json.dumps(plan, default=list)))
    return plan


def recommend_cell(conn, cell_id, as_of, prm=None):
    prm = prm or params()
    rows = conn.execute("SELECT date, requests, floor, rpm FROM daily WHERE cell_id=? AND date<=? ORDER BY date", (cell_id, as_of)).fetchall()
    if not rows:
        return None
    hf = [r["floor"] for r in rows]; hR = [r["rpm"] for r in rows]; hV = [r["requests"] for r in rows]
    cur = float(hf[-1]); vmed = float(np.median(hV[-14:]))
    d0 = d2(rows[0]["date"])
    idx = (d2(rows[-1]["date"]) - d0).days
    notes = [dict(day=(d2(n["date"]) - d0).days, text=n["text"], date=n["date"])
             for n in conn.execute("SELECT date, text FROM notes WHERE cell_id=? AND date<=? ORDER BY date", (cell_id, as_of)).fetchall()]
    out = dict(cell_id=cell_id, as_of=as_of, last_data=rows[-1]["date"], tier=tier_of(vmed), req=round(vmed), cur=round(cur, 4),
               n_days=len(rows), rec=None, refused=True, reason="insufficient_signal: too little history", change=0.0,
               gain_1k=None, se=None, z=None, gain_day=0.0, concave=None, plan=None, beta=None)
    recent = [dict(date=n["date"], text=n["text"], age=idx - n["day"]) for n in notes if idx - 3 <= n["day"] <= idx]
    out["notes"] = recent
    if len(rows) < MIN_HISTORY:
        return out
    # decide_system needs the plan hook; wrap so the agent call goes through the cache
    ctx_cache = {}

    def agent(ctx):
        ctx_cache["ctx"] = ctx
        return _plan_for(conn, cell_id, as_of, ctx)

    tgt, refused, reason, S, plan = decide_system("agent", None, notes, 0, idx, hf, hR, vmed, prm, agent)
    out.update(refused=bool(refused), reason=reason or "", rec=round(float(tgt), 4))
    if plan:
        out["plan"] = dict(hold_reason=plan.get("hold_reason"), exclude_last=int(plan.get("exclude_last") or 0), window=plan.get("window"),
                           direction=plan.get("direction", "both"), step_scale=float(plan.get("step_scale", 1.0)),
                           strength=plan.get("strength", "none"), evidence=[list(e) if isinstance(e, (list, tuple)) else [str(e), ""] for e in plan.get("evidence", [])])
    if S.get("ok"):
        beta = [float(x) for x in S["beta"]]
        x_app = float(np.log(max(tgt, 1e-9) / cur))
        out.update(beta=beta, gain_1k=round(float(S["gain"]), 4), se=round(float(S["se"]), 4), z=round(float(S["z"]), 3), concave=bool(S["concave"]),
                   change=round(float(tgt / cur - 1), 4))
        out["gain_day"] = 0.0 if refused else round((beta[1] * x_app + beta[2] * x_app ** 2) * vmed / 1000.0, 2)
    return out


def cell_ids(conn):
    return [r["cell_id"] for r in conn.execute("SELECT DISTINCT cell_id FROM daily ORDER BY cell_id")]


def decision_state(conn, as_of):
    """Latest decision per cell for an as-of date."""
    rows = conn.execute(
        "SELECT d.* FROM decisions d JOIN (SELECT cell_id, MAX(id) mid FROM decisions WHERE as_of=? GROUP BY cell_id) m ON d.id=m.mid", (as_of,)).fetchall()
    return {r["cell_id"]: dict(action=r["action"], final=r["final_floor"], comment=r["comment"], actor=r["actor"], ts=r["ts"]) for r in rows}


def queue(conn, as_of):
    prm = params()
    cells = [recommend_cell(conn, c, as_of, prm) for c in cell_ids(conn)]
    cells = [c for c in cells if c]
    st = decision_state(conn, as_of)
    for c in cells:
        c["decision"] = st.get(c["cell_id"])
    return cells


def dates(conn):
    rows = conn.execute("SELECT date, COUNT(DISTINCT cell_id) n FROM daily GROUP BY date ORDER BY date").fetchall()
    nn = {r["date"]: r["n"] for r in conn.execute("SELECT date, COUNT(*) n FROM notes GROUP BY date")}
    out = []
    for i, r in enumerate(rows):
        if i >= MIN_HISTORY:
            out.append(dict(date=r["date"], cells=r["n"], notes=nn.get(r["date"], 0)))
    return out


def target_date(as_of):
    return (d2(as_of) + timedelta(days=1)).isoformat()
