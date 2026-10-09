"""PLUMB synthetic world: a bid landscape with known ground truth.

No real or official data is used anywhere. Every number comes from the random
generator below, so the true best floor for every placement-day is known.

Auction model: K bidders per placement each bid lognormal(mu, sigma) with
participation probability `part`. Second-price with a reserve (the floor):
the top bid must clear the floor, price paid = max(second bid, floor).
Revenue per 1,000 requests R(f) = mean price paid per auction (CPM-dollars).
"""
import json
import os
import numpy as np

GRID = np.geomspace(0.08, 8.0, 72)        # candidate floors in CPM dollars
LG = np.log(GRID)
KMAX = 8
N_MC = 5000
BIDDERS = [f"Bidder-{c}" for c in "ABCDEFGH"]
DOW_VOL = np.array([1.0, 1.05, 1.05, 1.0, 0.95, 0.8, 0.75])
DOW_MU = np.array([0.0, 0.02, 0.03, 0.02, 0.0, -0.04, -0.05])
THIN = {3, 9, 14, 21, 27, 35}

OUTAGE_T = ["{b} endpoint returning 5xx since {h}:00, bid responses down",
            "{b} paused by their side, timeouts across our placements",
            "Demand partner {b} not bidding today, support ticket open",
            "{b} has gone quiet since morning, checking with their AM"]
AMBIG_T = ["Seeing timeouts on {b}, monitoring",
           "{b} bid rate looks a bit low, keeping an eye on it"]
SURGE_T = ["{ev} campaign goes live {when}, expect higher demand",
           "Big {ev} traffic expected {when}, buyers ramping spend"]
EVENTS = ["IPL match", "festive sale", "election results", "cricket final"]
GLITCH_T = ["ClickHouse ingestion lag, {dn} numbers incomplete, backfill pending",
            "Reporting pipeline delayed, impression counts for yesterday look short"]
SHIFT_T = ["{b} changed their bidding strategy last night",
           "New buyer onboarded on {b}, seats ramping"]
BENIGN_T = ["{b} latency alert auto-resolved in 5 min, no impact",
            "Deploy v2.{n} rolled out, no change in bid flow",
            "{b} timeout spike cleared, no impact on fill"]
NOISE_T = ["Weekly sync moved to 4pm", "New ops dashboard link shared in channel",
           "Reminder: update sprint tickets", "Invoice reconciliation for last month done"]


def build(seed=11, P=40, D=180, cache=None, thin_rng=(500, 2500), mid=()):
    if cache is None:
        from paths import CACHE
        cache = os.path.join(CACHE, "world1.npz")
    if os.path.exists(cache):
        z = np.load(cache, allow_pickle=True)
        w = {k: z[k] for k in z.files}
        w["notes"] = json.loads(str(w["notes"]))
        return w
    rng = np.random.default_rng(seed)
    thin = np.array([p in THIN for p in range(P)])
    base_mu = rng.normal(np.log(1.1), 0.45, P)
    sigma = rng.uniform(0.45, 0.8, P)
    part = rng.uniform(0.55, 0.9, P)
    K = rng.integers(4, KMAX + 1, P)
    vb = np.exp(rng.normal(np.log(60000), 0.8, P)).clip(15000, 400000)
    vb[thin] = rng.uniform(thin_rng[0], thin_rng[1], thin.sum())
    for q in mid:
        vb[q] = rng.uniform(1000, 5000)
    tier = np.where(thin, 2, np.where(np.isin(np.arange(P), list(mid)), 1, 0))

    mu = np.zeros((P, D)); kact = np.zeros((P, D), int); vol = np.zeros((P, D))
    ev_out = np.zeros((P, D), int); ev_surge = np.zeros((P, D)); ev_gl = np.ones((P, D))
    ev_shift = np.zeros((P, D)); notes = []

    def note(p, day, text, kind):
        if 0 <= day < D:
            notes.append(dict(p=int(p), day=int(day), text=text, kind=kind))

    for p in range(P):
        ar = np.zeros(D)
        for d in range(1, D):
            ar[d] = 0.6 * ar[d - 1] + rng.normal(0, 0.06 * 0.8)
        step = np.zeros(D); cur = 0.0
        for d in range(D):
            if rng.random() < 0.004:
                cur += rng.normal(0, 0.25)
                ev_shift[p, d] = 1
                if rng.random() < 0.35:
                    note(p, d, rng.choice(SHIFT_T).format(b=rng.choice(BIDDERS)), "shift")
            step[d] = cur
        for d in range(D):
            if rng.random() < 0.012:
                dur = int(rng.integers(1, 3)); nd = int(rng.integers(1, 3))
                for k in range(dur):
                    if d + k < D:
                        ev_out[p, d + k] = max(ev_out[p, d + k], nd)
                if rng.random() < 0.75:
                    b = rng.choice(BIDDERS)
                    t = AMBIG_T if rng.random() < 0.25 else OUTAGE_T
                    kind = "outage_ambig" if t is AMBIG_T else "outage"
                    note(p, d + int(rng.integers(0, 2)), rng.choice(t).format(b=b, h=int(rng.integers(0, 12))), kind)
            if rng.random() < 0.015:
                dur = int(rng.integers(1, 4))
                for k in range(dur):
                    if d + k < D:
                        ev_surge[p, d + k] = 0.3
                if rng.random() < 0.6:
                    note(p, d - 1, rng.choice(SURGE_T).format(ev=rng.choice(EVENTS), when="tomorrow"), "surge")
            if rng.random() < 0.012:
                ev_gl[p, d] = rng.uniform(0.4, 0.7)
                if rng.random() < 0.5:
                    note(p, d, rng.choice(GLITCH_T).format(dn="today"), "glitch")
            # decoys and noise
            if rng.random() < 0.04:
                note(p, d, rng.choice(BENIGN_T).format(b=rng.choice(BIDDERS), n=int(rng.integers(10, 60))), "benign")
            if rng.random() < 0.015:
                note(p, d, rng.choice(AMBIG_T).format(b=rng.choice(BIDDERS)), "ambig_decoy")
            if rng.random() < 0.08:
                note(p, d, rng.choice(NOISE_T), "noise")
        for d in range(D):
            mu[p, d] = base_mu[p] + DOW_MU[d % 7] + ar[d] + step[d] + ev_surge[p, d]
            kact[p, d] = max(1, K[p] - ev_out[p, d])
            vol[p, d] = vb[p] * DOW_VOL[d % 7] * np.exp(rng.normal(0, 0.05))

    R = np.zeros((P, D, len(GRID))); F = np.zeros_like(R); S = np.zeros_like(R)
    for p in range(P):
        Zn = rng.standard_normal((N_MC, KMAX)); U = rng.random((N_MC, KMAX))
        for d in range(D):
            k = kact[p, d]
            b = np.exp(mu[p, d] + sigma[p] * Zn[:, :k]) * (U[:, :k] < part[p])
            b = np.sort(b, axis=1)
            top = b[:, -1]
            sec = b[:, -2] if k >= 2 else np.zeros(N_MC)
            clear = top[:, None] >= GRID[None, :]
            price = np.where(clear, np.maximum(sec[:, None], GRID[None, :]), 0.0)
            R[p, d] = price.mean(0); F[p, d] = clear.mean(0); S[p, d] = price.std(0)

    anomaly = ((ev_out > 0) | (ev_surge > 0) | (ev_gl < 1)).astype(int)
    w = dict(tier=tier, R=R, F=F, S=S, vol=vol, glitch=ev_gl, outage=ev_out, surge=ev_surge,
             shift=ev_shift, anomaly=anomaly, thin=thin, mu=mu, kact=kact,
             notes=json.dumps(notes))
    np.savez_compressed(cache, **w)
    w["notes"] = notes
    return w


def best_floor(w, p, d):
    return GRID[int(np.argmax(w["R"][p, d]))]


if __name__ == "__main__":
    import time
    t = time.time(); w = build()
    print("built in", round(time.time() - t, 1), "s", w["R"].shape, "notes", len(w["notes"]))
    from collections import Counter
    print(Counter(n["kind"] for n in w["notes"]))
    print("anomaly share", w["anomaly"].mean().round(3), "outage days", (w["outage"] > 0).sum(),
          "surge", (w["surge"] > 0).sum(), "glitch", (w["glitch"] < 1).sum(), "shifts", int(w["shift"].sum()))
    bf = np.array([[best_floor(w, p, d) for d in range(180)] for p in range(40)])
    print("best floor range", bf.min().round(2), bf.max().round(2), "median", np.median(bf).round(2))
