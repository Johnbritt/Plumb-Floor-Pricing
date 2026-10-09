"""PLUMB evaluation, design v2.

Protocol
  1. Tune the gate on DEV placements of synthetic world 1 (maximise revenue capture).
  2. Freeze. Score on world 2: a fresh world (new seed, thinner cells), never used for tuning. Headline.
  3. Also score on world 1 EVAL placements, which the v1 design was already scored on ("seen").
Run: python3 evaluate.py
"""
import itertools
import json
import numpy as np
import pandas as pd
from sim import build
from engine import Rng, run_arm, DEV
from agents import heuristic_agent

ARMS = ["ops", "stats", "shrink", "rule", "agent", "pair"]
LABEL = {"ops": "A. Ops alone (today)", "stats": "B. Stats layer, no refusal, full step",
         "shrink": "C. Stats layer, confidence-scaled step", "rule": "D. Stats + rule refusal (no notes)",
         "agent": "E. Stats + agent refusal (model alone)", "pair": "F. Ops + agent (the pair)"}
HP = dict(blind=0.35, catch=0.6, catch_noted=0.9, false_override=0.10, fallback_hold=0.5)
BOOT = np.random.default_rng(0)


def tune(w, rg):
    rows = []
    for zfull, rz, thinV, nc in itertools.product([1, 2, 3, 4], [2.5, 3.5], [1500, 3000], [0.5, 1.0]):
        prm = dict(v=2, zfull=zfull, rz=rz, thinV=thinV, nc_scale=nc, zthr=0)
        r = pd.DataFrame(run_arm(w, rg, "rule", DEV, prm))
        rows.append(dict(zfull=zfull, rz=rz, thinV=thinV, nc_scale=nc, capture=r.rev.sum() / r.rev_oracle.sum(),
                         refuse=float(r.refused.mean())))
    t = pd.DataFrame(rows).sort_values("capture", ascending=False)
    b = t.iloc[0]
    return dict(v=2, zfull=float(b.zfull), rz=float(b.rz), thinV=float(b.thinV), nc_scale=float(b.nc_scale), zthr=0), t


def cap(df):
    return float(df.rev.sum() / df.rev_oracle.sum())


def ci(x):
    return [float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))]


def moved_harm(df):
    """Harmful move: floor moved by more than the exploration dither (>10%) and revenue fell more than 1%."""
    mv = np.abs(np.log(df.chosen / df.cur)) > 0.10
    return mv & (df.rev < df.rev_cur * 0.99)


def evaluate(w, rg, placements, prm, hp, hp_grid=True):
    recs = {a: pd.DataFrame(run_arm(w, rg, a, placements, prm, agent=heuristic_agent, hp=hp)) for a in ARMS}
    out = dict(prm=prm, hp=hp, n_placements=len(placements), n_decisions=int(len(recs["ops"])),
               n_anomaly_decisions=int(recs["ops"].anomaly.sum()),
               tiers={int(k): int(v) for k, v in pd.Series([int(w["tier"][p]) for p in placements]).value_counts().items()})
    ps = np.array(placements)
    per_p = {a: recs[a].groupby("p").agg(rev=("rev", "sum"), oracle=("rev_oracle", "sum")).loc[ps] for a in ARMS}
    idx = BOOT.integers(0, len(ps), (2000, len(ps)))
    boot = {a: per_p[a].rev.values[idx].sum(1) / per_p[a].oracle.values[idx].sum(1) for a in ARMS}
    arms = {}
    for a in ARMS:
        r = recs[a]
        cw = (~r.refused) & (r.rev_rec < r.rev_cur * 0.99) & (np.abs(np.log(r.rev_rec.clip(1e-9) / 1) * 0 + np.log(r.chosen / r.cur)) > 0.10) if a != "ops" else moved_harm(r)
        cellmean = float((per_p[a].rev / per_p[a].oracle).mean())
        arms[a] = dict(label=LABEL[a], capture=cap(r), capture_ci=ci(boot[a]), cell_mean_capture=cellmean,
                       refuse_rate=float(r.refused.mean()), harmful_move_rate=float(moved_harm(r).mean()),
                       capture_thick=cap(r[(r.tier == 0) & (r.anomaly == 0)]) if len(r[(r.tier == 0) & (r.anomaly == 0)]) else None,
                       capture_anomaly=cap(r[r.anomaly == 1]),
                       capture_mid=cap(r[r.tier == 1]) if (r.tier == 1).any() else None,
                       capture_thin=cap(r[r.tier == 2]) if (r.tier == 2).any() else None,
                       cell_capture_thin=float((per_p[a].rev / per_p[a].oracle)[[p for p in ps if w["tier"][p] == 2]].mean()) if (w["tier"][ps] == 2).any() else None,
                       harmful_move_rate_thin=float(moved_harm(r[r.tier == 2]).mean()) if (r.tier == 2).any() else None,
                       regret_usd=float((r.rev_oracle - r.rev).sum()))
    out["arms"] = arms
    out["diffs"] = {}
    for a, b in [("pair", "ops"), ("pair", "agent"), ("agent", "ops"), ("agent", "rule"), ("rule", "shrink"),
                 ("shrink", "stats"), ("agent", "shrink"), ("stats", "ops"), ("rule", "ops")]:
        d = boot[a] - boot[b]
        out["diffs"][f"{a}-{b}"] = dict(point=cap(recs[a]) - cap(recs[b]), ci=ci(d), p_gt0=float((d > 0).mean()))

    for a in ["rule", "agent"]:
        r = recs[a]
        ref = r[r.refused]
        # counterfactual: the same decision made by the confidence-scaled stats layer without any refusal
        sh = recs["shrink"].set_index(["p", "d"])
        j = ref.join(sh[["rev_rec"]].rename(columns={"rev_rec": "rev_shrink_rec"}), on=["p", "d"])
        prevented = j[j.rev_shrink_rec < j.rev_cur * 0.99]
        missed = j[j.rev_shrink_rec > j.rev_cur * 1.01]
        out[f"refusal_{a}"] = dict(refusals=int(len(ref)),
                                   by_tier={int(k): int(v) for k, v in ref.tier.value_counts().items()},
                                   prevented_bad_moves=int(len(prevented)), usd_saved=float((prevented.rev_cur - prevented.rev_shrink_rec).sum()),
                                   false_refusals=int(len(missed)), usd_missed=float((missed.rev_shrink_rec - missed.rev_cur).sum()),
                                   reasons=ref.reason.str.split(":").str[0].value_counts().to_dict())
        out[f"refusal_{a}"]["net_usd"] = out[f"refusal_{a}"]["usd_saved"] - out[f"refusal_{a}"]["usd_missed"]

    pr, ag = recs["pair"], recs["agent"]
    m = pr.merge(ag[["p", "d", "refused", "rev_rec"]], on=["p", "d"], suffixes=("", "_ag"))
    bad = m[(~m.refused_ag) & (m.rev_rec < m.rev_cur * 0.99)]
    caught = bad[bad.human.str.contains("override")]
    wrong = m[m.human.str.contains("wrong")]
    out["pair_human"] = dict(system_recs=int((~m.refused_ag).sum()), harmful_recs=int(len(bad)), caught=int(len(caught)),
                             usd_from_catches=float((caught.rev - caught.rev_rec).sum()),
                             wrong_overrides=int(len(wrong)), usd_lost_wrong_overrides=float((wrong.rev_rec - wrong.rev).sum()),
                             refusals_handed_back=int(m.refused_ag.sum()),
                             override_rate=float(m[~m.refused_ag].human.str.contains("override").mean()),
                             actions=pr.human.value_counts().to_dict())

    # penalty multiplier on harmful moves (bidder reaction / persistence, not simulated)
    mult = {}
    for k in [1, 2, 3, 5, 10, 20]:
        row = {}
        for a in ARMS:
            r = recs[a]; h = moved_harm(r)
            loss = np.maximum(r.rev_cur - r.rev, 0.0) * h
            row[a] = float((r.rev - (k - 1) * loss).sum() / r.rev_oracle.sum())
        mult[str(k)] = row
    out["harm_multiplier"] = mult

    cm = recs["agent"].merge(recs["rule"][["p", "d", "rev"]], on=["p", "d"], suffixes=("", "_rule"))
    cm["gain"] = cm.rev - cm.rev_rule
    out["agent_vs_rule_usd"] = {
        "anomaly_days": dict(n=int((cm.anomaly == 1).sum()), usd=float(cm[cm.anomaly == 1].gain.sum())),
        "noted_days": dict(n=int((cm.noted == 1).sum()), usd=float(cm[cm.noted == 1].gain.sum())),
        "other_days": dict(n=int((cm.noted == 0).sum()), usd=float(cm[cm.noted == 0].gain.sum()))}

    if hp_grid:
        sens = []
        for blind, catch, fb in itertools.product([0.0, 0.35, 0.7, 1.0], [0.2, 0.6, 0.9], [0.0, 0.5, 1.0]):
            h2 = dict(hp, blind=blind, catch=catch, catch_noted=max(catch, 0.9), fallback_hold=fb)
            r = pd.DataFrame(run_arm(w, rg, "pair", placements, prm, agent=heuristic_agent, hp=h2))
            sens.append(dict(blind=blind, catch=catch, fallback_hold=fb, capture=cap(r),
                             vs_agent=cap(r) - cap(recs["agent"]), vs_ops=cap(r) - cap(recs["ops"])))
        out["sensitivity"] = sens
    return out, recs


def main():
    w1 = build(); rg1 = Rng(40, 180)
    prm, tune_tbl = tune(w1, rg1)
    print("v2 params tuned on world-1 DEV:", prm)
    tune_tbl.to_csv("/home/claude/plumb/tuning_grid_v2.csv", index=False)
    w2 = build(seed=29, cache="/home/claude/plumb/world2.npz", thin_rng=(80, 700), mid=(5, 12, 18, 24, 30, 38))
    rg2 = Rng(40, 180, seed=77)
    res = {}
    o2, r2 = evaluate(w2, rg2, list(range(40)), prm, HP)
    res["world2_confirmation"] = o2
    pd.concat(r2.values(), ignore_index=True).to_csv("/home/claude/plumb/eval_decisions_world2.csv", index=False)
    o1, r1 = evaluate(w1, rg1, list(range(10, 40)), prm, HP, hp_grid=False)
    res["world1_seen"] = o1
    json.dump(res, open("/home/claude/plumb/results_v2.json", "w"), indent=1, default=float)
    for name, o in res.items():
        print("\n==", name, o["n_decisions"], "decisions;", o["n_anomaly_decisions"], "anomalous;", "tiers", o["tiers"])
        for a in ARMS:
            t = o["arms"][a]
            print(f"{t['label']:42s} cap {t['capture']*100:5.2f}% [{t['capture_ci'][0]*100:5.2f},{t['capture_ci'][1]*100:5.2f}] "
                  f"cell {t['cell_mean_capture']*100:5.2f} refuse {t['refuse_rate']*100:4.1f}% harm {t['harmful_move_rate']*100:4.1f}% "
                  f"thinharm {None if t['harmful_move_rate_thin'] is None else round(t['harmful_move_rate_thin']*100,1)}")
        for k, v in o["diffs"].items():
            print(f"  {k:14s} {v['point']*100:+6.2f} pts  CI [{v['ci'][0]*100:+5.2f},{v['ci'][1]*100:+5.2f}]")
    return res


if __name__ == "__main__":
    main()
