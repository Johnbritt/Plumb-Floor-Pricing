"""Simulates the pilot plan (shadow week, then half of cells on PLUMB, matched control) many times.
Run: python3 pilot_sim.py   -> pilot_results.json
Every pilot draws a random start day, a random subset of cells, a new noise seed and a random treatment split inside matched pairs.
"""
import json, sys
import numpy as np, pandas as pd
from sim import build
from engine import Rng, run_arm
from agents import heuristic_agent

O = "/home/claude/plumb/"
w = build(seed=29, cache=O + "world2.npz", thin_rng=(80, 700), mid=(5, 12, 18, 24, 30, 38))
prm = json.load(open(O + "results_v2.json"))["world2_confirmation"]["prm"]
HP = dict(blind=0.35, catch=0.6, catch_noted=0.9, false_override=0.10, fallback_hold=0.5)
N_REP = int(sys.argv[1]) if len(sys.argv) > 1 else 200
SHADOW = 7
vol = w["vol"].mean(1)
tier = w["tier"]

DESIGNS = {
    "as_written": dict(label="As written: 20 cells, 1 week shadow, 1 week half applied", cells=20, live=7),
    "four_weeks": dict(label="Extended: 20 cells, 1 week shadow, 4 weeks half applied", cells=20, live=28),
    "forty_cells": dict(label="Extended: 40 cells, 1 week shadow, 4 weeks half applied", cells=40, live=28),
}


def pilot(design, seed, placebo=False, adopt=1.0):
    rng = np.random.default_rng(seed)
    n, live = design["cells"], design["live"]
    cells = np.sort(rng.choice(40, n, replace=False)) if n < 40 else np.arange(40)
    order = sorted(cells, key=lambda p: (tier[p], vol[p]))          # matched pairs: neighbours by tier and volume
    pairs = [(order[i], order[i + 1]) for i in range(0, len(order) - 1, 2)]
    treat, ctrl = [], []
    for a, b in pairs:
        if rng.random() < 0.5: a, b = b, a
        treat.append(a); ctrl.append(b)
    d0 = int(rng.integers(70, 179 - SHADOW - live)); sw = d0 + SHADOW; d1 = sw + live - 1
    rg = Rng(40, 180, seed=int(rng.integers(1, 10**6)))
    t2 = "ops" if placebo else "pair"
    T = pd.DataFrame(run_arm(w, rg, "ops", treat, prm, agent=heuristic_agent, hp=HP, d0=d0, d1=d1, arm2=t2, switch=sw, adopt=adopt))
    C = pd.DataFrame(run_arm(w, rg, "ops", ctrl, prm, agent=heuristic_agent, hp=HP, d0=d0, d1=d1))
    def rpm(df, lo, hi):
        x = df[(df.d >= lo) & (df.d <= hi)]
        return x.groupby("p").apply(lambda g: (g.rpm_obs * g.req).sum() / g.req.sum())
    tb, ta, cb, ca = rpm(T, d0, sw - 1), rpm(T, sw, d1), rpm(C, d0, sw - 1), rpm(C, sw, d1)
    pt = {t: c for t, c in zip(treat, ctrl)}
    did = np.array([np.log(ta[t] / tb[t]) - np.log(ca[c] / cb[c]) for t, c in pt.items()])
    # simple read an ops lead would do: treated vs matched control revenue per 1k requests in the live period
    naive = np.array([np.log(ta[t] / ca[c]) for t, c in pt.items()])
    lift = float(np.expm1(did.mean())); se = did.std(ddof=1) / np.sqrt(len(did))
    L = T[T.d >= sw]; dec = L[~L.refused] if not placebo else L
    mv = np.abs(np.log(L.chosen / L.cur)) > 0.10
    harm = float((mv & (L.rev < L.rev_cur * 0.99)).mean())
    Lc = C[C.d >= sw]; harm_c = float(((np.abs(np.log(Lc.chosen / Lc.cur)) > 0.10) & (Lc.rev < Lc.rev_cur * 0.99)).mean())
    ov = L.human.str.contains("override|wrong").mean() if not placebo else np.nan
    holds = float(L.refused.mean()) if not placebo else np.nan
    # truth for this pilot (expected revenue, no noise), same difference-in-differences
    def tr(df, lo, hi):
        x = df[(df.d >= lo) & (df.d <= hi)]; return x.groupby("p").apply(lambda g: g.rev.sum() / (g.req.sum() / 1000))
    ttb, tta, tcb, tca = tr(T, d0, sw - 1), tr(T, sw, d1), tr(C, d0, sw - 1), tr(C, sw, d1)
    tdid = np.mean([np.log(tta[t] / ttb[t]) - np.log(tca[c] / tcb[c]) for t, c in pt.items()])
    return dict(lift=lift, lo90=float(np.expm1(did.mean() - 1.645 * se)), hi90=float(np.expm1(did.mean() + 1.645 * se)),
                naive_lift=float(np.expm1(naive.mean())), true_lift=float(np.expm1(tdid)), harm=harm, harm_ctrl=harm_c, override=float(ov), hold=holds,
                look=float((L.refused | L.human.str.contains("override|wrong") | (L.noted == 1)).mean()) if not placebo else np.nan)


def summarize(rows, placebo=False):
    d = pd.DataFrame(rows)
    out = dict(n=len(d), lift_median=float(d.lift.median()), lift_p10=float(d.lift.quantile(.1)), lift_p90=float(d.lift.quantile(.9)),
               lift_naive_median=float(d.naive_lift.median()), true_lift_median=float(d.true_lift.median()),
               p_lift_ge3=float((d.lift >= 0.03).mean()), p_lift_negative=float((d.lift <= 0).mean()), p_ci_above0=float((d.lo90 > 0).mean()))
    if not placebo:
        d["harm_ok"] = d.harm <= 0.05; d["ov_ok"] = d.override.between(0.05, 0.40)
        d["pass_plan"] = (d.lift >= 0.03) & d.harm_ok & d.ov_ok
        d["pass_strict"] = d.pass_plan & (d.lo90 > 0)
        d["pass_v2"] = (d.lo90 > 0) & (d.harm <= 0.6 * d.harm_ctrl) & d.ov_ok
        out.update(harm_ctrl_median=float(d.harm_ctrl.median()), p_pass_v2=float(d.pass_v2.mean()), harm_median=float(d.harm.median()), p_harm_ok=float(d.harm_ok.mean()), override_median=float(d.override.median()),
                   p_override_ok=float(d.ov_ok.mean()), p_override_lt2=float((d.override < 0.02).mean()), hold_median=float(d.hold.median()),
                   look_median=float(d.look.median()), p_pass_plan=float(d.pass_plan.mean()), p_pass_strict=float(d.pass_strict.mean()))
    return out


if __name__ == "__main__":
    k = sys.argv[2]; ds = DESIGNS[k]
    rows = [pilot(ds, 1000 + i) for i in range(N_REP)]
    null = [pilot(ds, 5000 + i, placebo=True) for i in range(N_REP)]
    weak = [pilot(ds, 9000 + i, adopt=0.25) for i in range(N_REP)] if k != "forty_cells" else None
    res = dict(label=ds["label"], plumb=summarize(rows), placebo=summarize(null, True),
               low_adoption=summarize(weak) if weak else None, example=rows[0],
               rows=[{a: (None if b != b else round(b, 4)) for a, b in r.items()} for r in rows],
               null_lifts=[round(r['lift'], 4) for r in null])
    json.dump(res, open(O + f"pilot_{k}.json", "w"), indent=1)
    print("done", k)
