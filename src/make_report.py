"""Exports the synthetic dataset, draws the figures, writes REPORT.md from results_v2.json / results_v1.json."""
import json
import zipfile
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from paths import RESULTS, DATA, DEMO, DOCS, CACHE, p as P_
from sim import build, GRID
from engine import Rng, observe, ops_floor

R2 = json.load(open(P_(RESULTS, "results_v2.json")))
H = R2["world2_confirmation"]; S = R2["world1_seen"]
V1 = json.load(open(P_(RESULTS, "results_v1.json")))
ARMS = ["ops", "stats", "shrink", "rule", "agent", "pair"]
SHORT = {"ops": "Ops alone", "stats": "Stats, full step", "shrink": "Stats, scaled step", "rule": "Stats + rule refusal",
         "agent": "Stats + agent refusal", "pair": "Ops + agent (pair)"}
COL = {"ops": "#8a8a8a", "stats": "#1f77b4", "shrink": "#6baed6", "rule": "#e6850e", "agent": "#c2410c", "pair": "#2a9d8f"}
pc = lambda x: f"{x*100:.1f}%"
pt = lambda x: f"{x*100:+.1f}"

# ---------------- dataset export (world 2, what the logs would look like under today's manual process)
w = build(seed=29, cache=P_(CACHE, "world2.npz"), thin_rng=(80, 700), mid=(5, 12, 18, 24, 30, 38)); rg = Rng(40, 180, seed=77)
rows, truth = [], []
dates = pd.date_range("2026-04-01", periods=180)
for p in range(40):
    f = float(np.clip(GRID[int(np.argmax(w["R"][p, 0]))] * np.exp(rg.f0[p]), GRID[0], GRID[-1]))
    for d in range(180):
        R, Fl, V = observe(w, rg, p, d, f)
        rows.append(dict(cell_id=f"CELL-{p:02d}", date=dates[d].date(), traffic_tier=["thick", "mid", "thin"][int(w["tier"][p])],
                         requests=int(V), floor_cpm=round(f, 3), fill_rate=round(Fl, 4), revenue_per_1k_requests=round(R, 4),
                         revenue_usd=round(R * V / 1000, 2)))
        bi = int(np.argmax(w["R"][p, d]))
        truth.append(dict(cell_id=f"CELL-{p:02d}", date=dates[d].date(), true_best_floor_cpm=round(float(GRID[bi]), 3),
                          true_revenue_per_1k_at_best=round(float(w["R"][p, d, bi]), 4), bidders_down=int(w["outage"][p, d]),
                          demand_surge=int(w["surge"][p, d] > 0), reporting_glitch_factor=round(float(w["glitch"][p, d]), 2),
                          demand_regime_shift_today=int(w["shift"][p, d])))
        f = ops_floor(rg, p, d, f, Fl)
pd.DataFrame(rows).to_csv(P_(DATA, "synthetic_daily_cells.csv"), index=False)
pd.DataFrame(truth).to_csv(P_(DATA, "synthetic_ground_truth.csv"), index=False)
nt = pd.DataFrame(w["notes"]); nt["cell_id"] = nt.p.map(lambda p: f"CELL-{p:02d}"); nt["date"] = nt.day.map(lambda d: dates[d].date())
nt[["cell_id", "date", "text"]].to_csv(P_(DATA, "synthetic_ops_notes.csv"), index=False)
nt[["cell_id", "date", "text", "kind"]].to_csv(P_(DATA, "synthetic_ops_notes_truth.csv"), index=False)

# ---------------- figures
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
fig, ax = plt.subplots(1, 2, figsize=(12.5, 4.6))
ys = np.arange(len(ARMS))[::-1]
for y, a in zip(ys, ARMS):
    t = H["arms"][a]
    ax[0].barh(y, t["capture"] * 100, color=COL[a], height=0.62)
    ax[0].plot(np.array(t["capture_ci"]) * 100, [y, y], color="black", lw=1.3)
    ax[0].text(60.8, y, f"{t['capture']*100:.1f}", va="center", ha="left", color="white", fontsize=9, fontweight="bold")
ax[0].set_yticks(ys); ax[0].set_yticklabels([SHORT[a] for a in ARMS]); ax[0].set_xlim(60, 100)
ax[0].set_xlabel("% of oracle revenue captured (bars: 95% CI over cells)"); ax[0].set_title("Revenue captured, world 2 (held out)", loc="left", fontweight="bold")
for a in ARMS:
    t = H["arms"][a]
    ax[1].scatter(t["harmful_move_rate"] * 100, t["capture"] * 100, s=90, color=COL[a], zorder=3)
    off = {"rule": (8, -14), "agent": (8, -26), "pair": (8, 6), "shrink": (8, 6), "stats": (8, 6), "ops": (-60, 8)}[a]
    ax[1].annotate(SHORT[a], (t["harmful_move_rate"] * 100, t["capture"] * 100), textcoords="offset points", xytext=off, fontsize=9)
ax[1].set_xlabel("Harmful moves (floor moved >10% and revenue fell >1%), % of decisions"); ax[1].set_ylabel("% of oracle revenue captured")
ax[1].set_title("Safety vs revenue", loc="left", fontweight="bold"); ax[1].grid(alpha=0.25)
ax[1].set_xlim(0, 19)
plt.tight_layout(); plt.savefig(P_(RESULTS, "fig1_results.png"), dpi=170); plt.close()

fig = plt.figure(figsize=(13.5, 4.6))
gs = fig.add_gridspec(1, 4, width_ratios=[1.5, 1, 1, 1], wspace=0.35)
a0 = fig.add_subplot(gs[0])
ks = [1, 2, 3, 5, 10, 20]
for a in ARMS:
    a0.plot(ks, [H["harm_multiplier"][str(k)][a] * 100 for k in ks], marker="o", color=COL[a], label=SHORT[a], lw=2 if a in ("stats", "agent") else 1.3)
a0.set_xscale("log"); a0.set_xticks(ks); a0.set_xticklabels(ks)
a0.set_xlabel("Penalty multiplier on harmful moves\n(bidder reaction, not modelled)"); a0.set_ylabel("% of oracle revenue captured")
a0.set_title("When does refusal start to pay?", loc="left", fontweight="bold", fontsize=10); a0.grid(alpha=0.25)
a0.set_ylim(35, 101); a0.legend(frameon=False, fontsize=7.5, loc="lower left")
sens = pd.DataFrame(H["sensitivity"])
im = None
for i, fb in enumerate([0.0, 0.5, 1.0]):
    ax = fig.add_subplot(gs[i + 1])
    sub = sens[sens.fallback_hold == fb].pivot(index="blind", columns="catch", values="vs_agent") * 100
    im = ax.imshow(sub.values, cmap="RdBu", vmin=-2.5, vmax=2.5, origin="lower", aspect="auto")
    for r in range(sub.shape[0]):
        for c in range(sub.shape[1]):
            ax.text(c, r, f"{sub.values[r, c]:+.1f}", ha="center", va="center", fontsize=8)
    ax.set_xticks(range(3)); ax.set_xticklabels(["20%", "60%", "90%"]); ax.set_xlabel("Ops catch rate")
    ax.set_yticks(range(4)); ax.set_yticklabels(["0%", "35%", "70%", "100%"] if i == 0 else [])
    if i == 0:
        ax.set_ylabel("Recs accepted unreviewed")
    ax.set_title(f"Refused -> ops holds {int(fb*100)}%", fontsize=9, loc="left")
    for sp in ax.spines.values():
        sp.set_visible(False)
fig.suptitle("Right: pair minus model-alone, revenue points, by assumed human behaviour", x=0.62, y=1.0, fontsize=10, fontweight="bold")
cax = fig.add_axes([0.92, 0.18, 0.012, 0.6]); fig.colorbar(im, cax=cax)
plt.savefig(P_(RESULTS, "fig2_sensitivity.png"), dpi=170, bbox_inches="tight"); plt.close()

# ---------------- report
A = H["arms"]; D = H["diffs"]; rf = H["refusal_agent"]; ph = H["pair_human"]
v1r, v1s = V1["arms"]["rule"], V1["arms"]["stats"]
sens_min, sens_max = sens.vs_agent.min() * 100, sens.vs_agent.max() * 100
md = f"""# PLUMB: results on sample data (synthetic)

**Everything here is computed on a synthetic sample dataset. No employer, customer or platform data was used.** The data generator builds a bid landscape per placement cell, so the best floor is known exactly for every cell and day. That is what lets us score decisions properly. It also means every number below describes the simulated world, not your ad stack.

## What was built
| Piece | What it does |
|---|---|
| `sim.py` | 40 placement cells x 180 days. Second-price auction with a floor, daily demand shocks, and four event types: bidder outage, demand surge, reporting glitch, demand regime shift. Each event may or may not leave a free-text ops note; decoy and benign notes are added. |
| `engine.py` | Stats layer (quadratic revenue-vs-floor fit on the last 21 days, uncertainty on the predicted gain), rule gate, closed-loop runner where each arm lives with its own floor history, modelled ops person. |
| `agents.py` | Agent layer behind one interface. **Offline stand-in** (keyword rules over the notes) is what produced the numbers below. **Claude backend** is wired and unit-tested with a mock, but not run: this session has no API key. |
| `evaluate.py` | Six arms, cluster bootstrap over cells, refusal accounting, human-catch accounting, sensitivity sweeps. |

Evaluation protocol: gate thresholds tuned on 10 dev cells of world 1, then frozen and scored on **world 2**, a fresh world (new seed, thinner cells) never used for tuning: {H['n_decisions']:,} floor decisions across {H['n_placements']} cells, {H['n_anomaly_decisions']} of them during an event. A decision is scored by the true revenue of the floor chosen, divided by the revenue at the true best floor.

## Results (world 2, held out)
| Arm | Revenue captured (95% CI) | Refused | Harmful moves |
|---|---|---|---|
""" + "\n".join(f"| {A[a]['label']} | {pc(A[a]['capture'])} ({pc(A[a]['capture_ci'][0])} to {pc(A[a]['capture_ci'][1])}) | {pc(A[a]['refuse_rate'])} | {pc(A[a]['harmful_move_rate'])} |" for a in ARMS) + f"""

![results](../results/fig1_results.png)

## Scorecard against the submission's claims
| Claim in the doc | Verdict on the sample data | Evidence |
|---|---|---|
| The pair beats ops alone | **Supported** (but see caveat 1) | {pt(D['pair-ops']['point'])} pts, CI {pt(D['pair-ops']['ci'][0])} to {pt(D['pair-ops']['ci'][1])} |
| The pair beats the model alone | **Not supported** | {pt(D['pair-agent']['point'])} pts, CI {pt(D['pair-agent']['ci'][0])} to {pt(D['pair-agent']['ci'][1])}; across 36 human-behaviour settings it ranges {sens_min:+.1f} to {sens_max:+.1f} pts |
| Refusal improves outcomes | **Safety yes, dollars no** | Harmful moves fall from {pc(A['stats']['harmful_move_rate'])} to {pc(A['agent']['harmful_move_rate'])}, but refusal and step-scaling cost {abs(D['shrink-stats']['point'])*100:.1f} to {abs(D['agent-ops']['point'] - D['stats-ops']['point'])*100:.1f} pts of revenue vs the unguarded stats layer |
| The agent beats a plain rule (Null Test) | **Not shown** by the stand-in | agent minus rule: {pt(D['agent-rule']['point'])} pts, CI {pt(D['agent-rule']['ci'][0])} to {pt(D['agent-rule']['ci'][1])}. The stand-in is itself a rule set, so this needs the Claude run |
| The human catches what the agent misses | **Weak** | {ph['caught']} of {ph['harmful_recs']} harmful recs caught; net ${ph['usd_from_catches']:+.0f}. Wrong overrides ({ph['wrong_overrides']}, at an assumed 10% false-override rate) cost ${ph['usd_lost_wrong_overrides']:,.0f} |

**The honest headline:** the statistical layer does almost all the work, about {abs(D['stats-ops']['point'])*100:.0f} points over the modelled manual process. Refusal is a safety feature that costs some revenue in this world. The model's own contribution is unproven until the Claude backend is run.

## Design changes the findings forced (use these for the build-journey slide)
1. **Hard significance gate refused {pc(v1r['refuse_rate'])} of days (v1) and cost {abs(v1r['capture']-v1s['capture'])*100:.1f} pts vs the unguarded stats layer.** Replaced with a confidence-scaled step: refuse only on data-quality problems, otherwise let confidence shrink the move. Refusals fell to {pc(A['rule']['refuse_rate'])}.
2. **The v1 safety metric was contaminated by the exploration dither** (a held floor looked "harmful" just from random jitter). Replaced with: floor moved more than 10% and revenue fell more than 1%.
3. **Refusing on thin cells freezes learning.** On the thinnest cells, refusal arms capture {pc(A['agent']['capture_thin'])} vs {pc(A['ops']['capture_thin'])} for ops and {pc(A['stats']['capture_thin'])} for the unguarded layer: a refused cell stays stuck at its starting floor. Next iteration: pair "insufficient signal" with a small randomized floor test so the cell gathers data, or pool thin cells with similar ones.
4. **Notes-driven holds hurt during outages.** Agent minus rule on event days: ${H['agent_vs_rule_usd']['anomaly_days']['usd']:+.0f}. Likely cause: an outage removes bidders, which lowers the best floor, so freezing the floor is the wrong response. I have not isolated this, but it points to an agent that adjusts direction instead of just holding.

![sensitivity](../results/fig2_sensitivity.png)

Left: if a harmful move carries a penalty beyond its same-day revenue loss (bidders pulling back, persistence), the guarded arms close the gap. At 20x the scaled-step arm overtakes the full-step arm. Right: the pair never reliably beats the model alone. Two things drive this: refusals hand decisions back to a human whose manual process is the weakest arm, and wrong overrides cost more than catches save.

## Caveats you must state in the deck
1. **The ops arm is my model of manual pricing** (nudge the floor toward a believed fill rate, with noise). The size of the gap to ops depends on that assumption. Real ops colleagues must run the human arm; until then, quote the direction, not the size.
2. **No bidder reaction.** Real bidders adapt to floors. The multiplier chart shows how much that would have to matter.
3. **The pair arm uses an assumed human** (accept, catch and false-override rates). It is a sensitivity analysis, not a measurement.
4. **The agent arm is a keyword stand-in, not Claude.** Do not present it as an LLM result.
5. Two synthetic worlds, one seed each. Intervals are cluster bootstraps over cells, so they do not capture world-to-world variation.
6. The $2.5K to $5K a month figure in the doc is not supported by this analysis. The gains here are percentages of oracle revenue, not rupees.

## Files
`synthetic_daily_cells.csv` (7,200 cell-days under manual pricing: requests, floor, fill, revenue), `synthetic_ground_truth.csv` (true best floor and event flags), `synthetic_ops_notes.csv` (what the agent reads), `synthetic_ops_notes_truth.csv` (same plus true note type), `eval_decisions_world2.csv` (all decisions, all arms), `results_v1.json`, `results_v2.json`, `tuning_grid_v1.csv`, `tuning_grid_v2.csv`, and the code.

## Run it
`python3 evaluate.py` reproduces everything (about 2 minutes). With `ANTHROPIC_API_KEY` set, replace `heuristic_agent` with `make_llm_agent()` in `evaluate.py`. Run it on a sample of cells first: it makes one API call per decision, so the full run is about {H['n_decisions']*2:,} calls across the agent and pair arms.
"""
open(P_(DOCS, "CASE_STUDY.md"), "w").write(md)

print("ok")
