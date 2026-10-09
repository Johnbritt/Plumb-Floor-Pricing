"""Snapshots every one of the 40 cells on three eventful days of the held-out world (agent-arm trajectories)."""
import json
import numpy as np
from sim import build, GRID
from paths import RESULTS, DATA, DEMO, DOCS, CACHE, p as P_
from engine import Rng, observe, ops_floor, decide_system, stats_fit, true_rev, D0, D1
from agents import heuristic_agent

w = build(seed=29, cache=P_(CACHE, "world2.npz"), thin_rng=(80, 700), mid=(5, 12, 18, 24, 30, 38))
rg = Rng(40, 180, seed=77)
prm = json.load(open(P_(RESULTS, "results_v2.json")))["world2_confirmation"]["prm"]
by_p = {}
for n in w["notes"]:
    by_p.setdefault(n["p"], []).append(n)

# three eventful days, at least 12 days apart
score = [(int(w["anomaly"][:, d - 1].sum() + w["anomaly"][:, d].sum()), d) for d in range(80, 176)]
score.sort(reverse=True)
DATES = []
for s, d in score:
    if all(abs(d - x) >= 12 for x in DATES):
        DATES.append(d)
    if len(DATES) == 3:
        break
DATES.sort()
print("dates", DATES, [s for s, d in score if d in DATES])

SITES = ["Metro Daily", "Cricket Pulse", "Cinema Wire", "Kitchen Table", "Pocket Tech", "Fin Weekly", "Travel Compass", "Home & Hearth"]
PLACE = ["Article top", "Article mid", "Sidebar", "Listing", "Footer"]
dates = np.array(["2026-04-01"], dtype="datetime64[D]")[0] + np.arange(180)
R4 = lambda v: round(float(v), 4)

snaps = {d: [] for d in DATES}
for p in range(40):
    notes_p = by_p.get(p, [])
    f = float(np.clip(GRID[int(np.argmax(w["R"][p, 0]))] * np.exp(rg.f0[p]), GRID[0], GRID[-1]))
    hf, hR, hFill, hV = [], [], [], []
    for d in range(0, D0):
        R, Fl, V = observe(w, rg, p, d, f); hf.append(f); hR.append(R); hFill.append(Fl); hV.append(V)
        f = ops_floor(rg, p, d, f, Fl)
    for d in range(D0, max(DATES) + 1):
        cur = hf[-1]; vmed = float(np.median(hV[-14:]))
        manual = ops_floor(rg, p, d - 1, cur, hFill[-1])
        tgt, refused, reason, S, plan = decide_system("agent", w, notes_p, p, d - 1, hf, hR, vmed, prm, heuristic_agent)
        if d in DATES:
            S0 = stats_fit(hf, hR)
            plan = plan or {}
            lo, hi = cur * 0.35, cur * 3.0
            gi = [i for i, g in enumerate(GRID) if lo <= g <= hi]
            curve = [[R4(GRID[i]), R4(w["vol"][p, d] / 1000 * w["R"][p, d, i])] for i in gi]
            recent = [dict(age=int((d - 1) - n["day"]), text=n["text"]) for n in notes_p if d - 3 <= n["day"] <= d - 1]
            snaps[d].append(dict(
                p=p, name=f"{SITES[p // 5]} · {PLACE[p % 5]}", site=SITES[p // 5], place=PLACE[p % 5], tier=["thick", "mid", "thin"][int(w["tier"][p])],
                req=round(float(w["vol"][p, d])), cur=R4(cur), manual=R4(manual), target=R4(tgt), refused=bool(refused), reason=reason,
                hist_f=[R4(x) for x in hf[-21:]], hist_R=[R4(x) for x in hR[-21:]], notes=recent,
                beta=[R4(x) for x in S["beta"]] if S.get("ok") else None, beta_raw=[R4(x) for x in S0["beta"]] if S0.get("ok") else None,
                gain=R4(S["gain"]) if S.get("ok") else None, se=R4(S["se"]) if S.get("ok") else None, z=R4(S["z"]) if S.get("ok") else None,
                concave=bool(S.get("concave", True)), exclude_last=int(plan.get("exclude_last", 0)), direction=plan.get("direction", "both"),
                evidence=[[a, b] for a, b in plan.get("evidence", [])], curve=curve, best=R4(GRID[int(np.argmax(w["R"][p, d]))])))
        f_new = float(np.clip(tgt * np.exp(0.05 * rg.zd[p, d]), GRID[0], GRID[-1]))
        R, Fl, V = observe(w, rg, p, d, f_new)
        hf.append(f_new); hR.append(R); hFill.append(Fl); hV.append(V)

days = [dict(d=int(d), date=str(dates[d]), cells=snaps[d]) for d in DATES]
json.dump(days, open(P_(DEMO, "demo_queue.json"), "w"), separators=(",", ":"))
import os
print("bytes", os.path.getsize(P_(DEMO, "demo_queue.json")))
for dd in days:
    c = dd["cells"]
    print(dd["date"], "cells", len(c), "recommend", sum(not x["refused"] for x in c), "hold", sum(x["refused"] for x in c), "with notes", sum(bool(x["notes"]) for x in c))
