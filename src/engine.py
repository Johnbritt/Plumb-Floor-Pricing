"""PLUMB engine: statistical layer, rule gate, agent hook, human model, closed-loop runner."""
import numpy as np
from sim import GRID, LG, build

W_DAYS = 21
STEP_CAP = 0.25
DITHER_SD = 0.05
D0, D1 = 60, 179          # decide floors for days D0..D1 (data through the day before)
DEV = list(range(0, 10))
EVAL = list(range(10, 40))


class Rng:
    """Common random numbers: every arm sees the same noise for the same (placement, day)."""
    def __init__(self, P, D, seed=5):
        r = np.random.default_rng(seed)
        self.zr = r.standard_normal((P, D)); self.zf = r.standard_normal((P, D))
        self.zd = r.standard_normal((P, D)); self.zo = r.standard_normal((P, D))
        self.uo = r.random((P, D)); self.uh = r.random((P, D, 3))
        self.tf = r.uniform(0.45, 0.7, P)          # each ops person's believed target fill
        self.f0 = r.normal(0, 0.35, P)             # initial floor miss vs. the true best


def observe(w, rg, p, d, f):
    """Return what the logs would show for placement p on day d at floor f."""
    lf = np.log(f)
    R = np.interp(lf, LG, w["R"][p, d]); F = np.interp(lf, LG, w["F"][p, d]); S = np.interp(lf, LG, w["S"][p, d])
    V = w["vol"][p, d]
    Ro = max(R + S / np.sqrt(V) * rg.zr[p, d], 0.0)
    Fo = float(np.clip(F + np.sqrt(max(F * (1 - F), 1e-6) / V) * rg.zf[p, d], 0, 1))
    g = w["glitch"][p, d]
    return Ro * g, Fo * g, V          # glitch under-counts revenue and fill, not requests


def true_rev(w, p, d, f):
    return w["vol"][p, d] / 1000.0 * np.interp(np.log(f), LG, w["R"][p, d])


def ops_floor(rg, p, d, f_cur, fill_obs):
    """Today's manual process: nudge the floor toward a believed target fill rate."""
    if rg.uo[p, d] < 0.15:
        step = 0.0
    else:
        step = 0.5 * (fill_obs - rg.tf[p]) + 0.10 * rg.zo[p, d]
    return float(np.clip(f_cur * np.exp(np.clip(step, -0.4, 0.4)), GRID[0], GRID[-1]))


def stats_fit(hf, hR, window=W_DAYS, exclude_last=0):
    """Weighted-free OLS of revenue per 1k requests on ln(floor) (quadratic), local to current floor."""
    n_all = len(hf)
    hi = n_all - exclude_last
    lo = max(0, hi - window)
    f = np.asarray(hf[lo:hi]); R = np.asarray(hR[lo:hi])
    cur = hf[-1]
    out = dict(ok=False, n=len(f), cur=cur)
    if len(f) < 8:
        return out
    x = np.log(f / cur)
    out["x_sd"] = float(x.std())
    X = np.c_[np.ones_like(x), x, x ** 2]
    try:
        beta, *_ = np.linalg.lstsq(X, R, rcond=None)
        XtXi = np.linalg.inv(X.T @ X)
    except np.linalg.LinAlgError:
        return out
    res = R - X @ beta
    dof = max(len(f) - 3, 1)
    s2 = float(res @ res / dof)
    xs = np.linspace(-STEP_CAP, STEP_CAP, 51)
    pred = beta[0] + beta[1] * xs + beta[2] * xs ** 2
    k = int(np.argmax(pred)); xstar = xs[k]
    d = np.array([0.0, xstar, xstar ** 2])
    gain = float(beta[1] * xstar + beta[2] * xstar ** 2)
    se = float(np.sqrt(max(s2 * d @ XtXi @ d, 1e-12)))
    last_res = float((R[-1] - X[-1] @ beta) / max(np.sqrt(s2), 1e-9))
    out.update(ok=True, beta=beta, xstar=float(xstar), rec=float(np.clip(cur * np.exp(xstar), GRID[0], GRID[-1])),
               gain=gain, se=se, z=gain / se if se > 0 else 0.0, concave=bool(beta[2] < 0),
               resid_z=last_res, rev_mean=float(R.mean()), s=float(np.sqrt(s2)))
    return out


def rule_gate(S, vmed, prm, minimal=False):
    """Structured-statistics refusal: no access to free-text notes. Returns reason or None."""
    if not S["ok"]:
        return "insufficient_signal: too little history"
    if S["x_sd"] < (0.02 if minimal else 0.04):
        return "insufficient_signal: floor barely varied, response curve not identified"
    if minimal:
        return None
    if vmed < prm.get("thinV", 3000):
        return "insufficient_signal: thin traffic"
    if prm.get("v", 1) == 1 and prm.get("concave", True) and not S["concave"]:
        return "insufficient_signal: no interior optimum"
    if abs(S["resid_z"]) > prm["rz"]:
        return "insufficient_signal: last day is an outlier vs the fitted curve"
    if prm.get("v", 1) == 1:
        if abs(S["xstar"]) < 0.015:
            return "no_move: floor already near the fitted optimum"
        if S["z"] < prm["zthr"]:
            return "no_significant_gain: predicted gain within noise"
    return None


def conf_scale(S, prm):
    """v2: confidence shrinks the step instead of refusing. z/zfull in [0,1]; non-concave fits are halved."""
    if prm.get("v", 1) != 2:
        return 1.0
    c = min(max(S["z"] / prm["zfull"], 0.0), 1.0)
    if not S["concave"]:
        c *= prm.get("nc_scale", 0.5)
    return c


def build_ctx(S, notes, d, vmed):
    return dict(day=d, stats={k: (float(v) if isinstance(v, (int, float, np.floating)) else v)
                              for k, v in S.items() if k not in ("beta",)},
                vmed=float(vmed),
                notes=[dict(age=d - n["day"], text=n["text"]) for n in notes if d - 2 <= n["day"] <= d + 1 and n["day"] <= d + 1])


def decide_system(mode, w, notes_p, p, d, hf, hR, vmed, prm, agent):
    """Returns (target_floor, refused, reason, S, plan)."""
    S = stats_fit(hf, hR)
    cur = hf[-1]
    plan = None
    if mode == "stats":
        why = rule_gate(S, vmed, prm, minimal=True)
        return (cur if why else S["rec"]), bool(why), why or "", S, plan
    if mode == "shrink":
        why = rule_gate(S, vmed, prm, minimal=True)
        if why:
            return cur, True, why, S, plan
        xs = S["xstar"] * conf_scale(S, prm)
        return float(np.clip(cur * np.exp(xs), GRID[0], GRID[-1])), False, "", S, plan
    if mode == "rule":
        why = rule_gate(S, vmed, prm)
        if why:
            return cur, True, why, S, plan
        xs = S["xstar"] * conf_scale(S, prm)
        if prm.get("v", 1) == 2 and abs(xs) < 0.015:
            return cur, False, "", S, plan
        return float(np.clip(cur * np.exp(xs), GRID[0], GRID[-1])), False, "", S, plan
    # agent
    if not S["ok"]:
        return cur, True, "insufficient_signal: too little history", S, plan
    ctx = build_ctx(S, [n for n in notes_p if n["day"] <= d], d, vmed)
    plan = agent(ctx)
    if plan.get("hold_reason"):
        return cur, True, plan["hold_reason"], S, plan
    S1 = S
    if plan.get("exclude_last", 0) or plan.get("window"):
        S1 = stats_fit(hf, hR, window=plan.get("window") or W_DAYS, exclude_last=plan.get("exclude_last", 0))
        if S1["ok"]:
            S1["cur"] = cur
            # refit was centred on the last included floor; re-anchor recommendation to the live floor
            S1["rec"] = float(np.clip(cur * np.exp(S1["xstar"]), GRID[0], GRID[-1]))
    why = rule_gate(S1, vmed, prm)
    if why:
        return cur, True, why, S1, plan
    xs = S1["xstar"] * conf_scale(S1, prm) * plan.get("step_scale", 1.0)
    if prm.get("v", 1) == 2 and abs(xs) < 0.015:
        return cur, False, "", S1, plan
    if plan.get("direction") == "raise" and xs < 0:
        return cur, True, "hold: surge expected, not lowering the floor", S1, plan
    return float(np.clip(cur * np.exp(xs), GRID[0], GRID[-1])), False, "", S1, plan


def human_step(rg, p, d, anomaly, noted, refused, rec, cur, manual, hp):
    """Simulated ops person. Parameters are assumptions, swept in the sensitivity analysis."""
    u = rg.uh[p, d]
    if refused:
        if anomaly and u[0] < hp["catch"]:
            return cur, "hold (knew why)"
        if u[1] < hp.get("fallback_hold", 0.5):
            return cur, "hold"
        return manual, "manual"
    if u[0] < hp["blind"]:
        return rec, "accept (unreviewed)"
    pc = hp["catch_noted"] if noted else hp["catch"]
    if anomaly and u[1] < pc:
        return cur, "override (caught)"
    if u[2] < hp["false_override"]:
        return manual, "override (wrong)"
    return rec, "accept"


def run_arm(w, rg, arm0, placements, prm, agent=None, hp=None, d0=D0, d1=D1, arm2=None, switch=None, adopt=1.0):
    recs = []
    notes_all = w["notes"]
    by_p = {}
    for n in notes_all:
        by_p.setdefault(n["p"], []).append(n)
    for p in placements:
        notes_p = by_p.get(p, [])
        # shared burn-in under today's manual process
        f = GRID[int(np.argmax(w["R"][p, 0]))] * np.exp(rg.f0[p]); f = float(np.clip(f, GRID[0], GRID[-1]))
        hf, hR, hFill, hV = [], [], [], []
        for d in range(0, d0):
            R, Fl, V = observe(w, rg, p, d, f)
            hf.append(f); hR.append(R); hFill.append(Fl); hV.append(V)
            f = ops_floor(rg, p, d, f, Fl)
        # f is the floor ops set for day d0 on the burn-in trajectory
        for d in range(d0, d1 + 1):
            arm = arm2 if (switch is not None and d >= switch) else arm0
            # decision for day d is made at end of day d-1; hf[-1] is the floor live on day d-1
            cur = hf[-1]
            vmed = float(np.median(hV[-14:]))
            manual = ops_floor(rg, p, d - 1, cur, hFill[-1])
            S = None; refused = False; reason = ""; rec = np.nan; hnote = ""; rec_f = None
            if arm == "ops":
                tgt = manual
            else:
                mode = {"stats": "stats", "shrink": "shrink", "rule": "rule", "agent": "agent", "pair": "agent"}[arm]
                tgt, refused, reason, S, plan = decide_system(mode, w, notes_p, p, d - 1, hf, hR, vmed, prm, agent)
                rec = tgt; rec_f = tgt
                if arm == "pair":
                    anomaly = bool(w["anomaly"][p, d - 1] or w["anomaly"][p, d])
                    noted = any(d - 2 <= n["day"] <= d - 1 and n["kind"] in ("outage", "outage_ambig", "surge", "glitch") for n in notes_p)
                    tgt, hnote = human_step(rg, p, d, anomaly, noted, refused, rec, cur, manual, hp)
                    if adopt < 1.0 and np.random.default_rng(p * 1000 + d).random() > adopt:
                        tgt, hnote = manual, hnote + "|not_adopted"
                if arm != "ops":
                    tgt = tgt * np.exp(DITHER_SD * rg.zd[p, d])
            f_new = float(np.clip(tgt, GRID[0], GRID[-1]))
            # what the stats layer alone would have proposed (for refusal accounting)
            S_alt = stats_fit(hf, hR)
            f_stats = S_alt["rec"] if S_alt["ok"] else cur
            r_choice = true_rev(w, p, d, f_new); r_cur = true_rev(w, p, d, cur)
            r_rec = true_rev(w, p, d, rec_f) if rec_f is not None else r_choice
            r_stats = true_rev(w, p, d, f_stats); r_or = w["vol"][p, d] / 1000.0 * w["R"][p, d].max()
            recs.append(dict(arm=arm, p=p, d=d, cur=cur, chosen=f_new, refused=refused, reason=reason,
                             rev=r_choice, rev_cur=r_cur, rev_rec=r_rec, rev_stats=r_stats, rev_oracle=r_or,
                             anomaly=int(w["anomaly"][p, d - 1] or w["anomaly"][p, d]),
                             thin=int(w["thin"][p]), tier=int(w["tier"][p]) if "tier" in w else int(w["thin"][p]) * 2, human=hnote,
                             noted=int(any(d - 2 <= n["day"] <= d - 1 and n["kind"] in ("outage", "outage_ambig", "surge", "glitch") for n in notes_p))))
            R, Fl, V = observe(w, rg, p, d, f_new)
            recs[-1]["rpm_obs"] = float(R); recs[-1]["req"] = float(w["vol"][p, d])
            hf.append(f_new); hR.append(R); hFill.append(Fl); hV.append(V)
    return recs
