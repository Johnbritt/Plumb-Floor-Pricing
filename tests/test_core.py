"""Fast checks on the parts that carry the claims. They use a tiny world, so they run in seconds."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from agents import heuristic_agent  # noqa: E402
from engine import GRID, stats_fit  # noqa: E402
from sim import build  # noqa: E402

PLAN_KEYS = {"hold_reason", "exclude_last", "window", "direction", "step_scale", "evidence", "strength"}


def curve(f, peak=1.5, curv=-0.6, base=1.0):
    return base + curv * np.log(f / peak) ** 2


def test_stats_fit_finds_the_peak_without_noise():
    rng = np.random.default_rng(1)
    f = 1.2 * np.exp(rng.uniform(-0.2, 0.2, 21)); f[-1] = 1.2
    out = stats_fit(list(f), list(curve(f)))
    assert out["ok"] and out["concave"]
    assert out["rec"] > 1.2 and out["gain"] > 0       # the peak is above the current floor, so it proposes a raise


def test_stats_fit_refuses_tiny_history():
    assert stats_fit([1.0] * 5, [1.0] * 5)["ok"] is False


def test_step_is_capped():
    f = np.exp(np.linspace(-0.3, 0.3, 21)); f[-1] = 1.0
    out = stats_fit(list(f), list(curve(f, peak=5.0)))
    assert abs(np.log(out["rec"] / out["cur"])) <= 0.25 + 1e-9


def test_agent_returns_plan_only_and_never_a_price():
    plan = heuristic_agent({"notes": [{"text": "Bidder-H endpoint returning 5xx since 09:00"}]})
    assert set(plan) == PLAN_KEYS
    assert plan["hold_reason"].startswith("insufficient_signal")
    assert not any(isinstance(v, float) and k not in ("step_scale",) for k, v in plan.items())


def test_agent_ignores_benign_notes_and_trims_lagged_data():
    assert heuristic_agent({"notes": [{"text": "Alert cleared, no impact on bid flow"}]})["hold_reason"] is None
    assert heuristic_agent({"notes": [{"text": "Reporting ingestion lag, yesterday looks short"}]})["exclude_last"] == 2
    assert heuristic_agent({"notes": [{"text": "Big campaign goes live tomorrow"}]})["direction"] == "raise"


def test_world_is_deterministic_and_shaped(tmp_path):
    a = build(seed=3, P=4, D=40, cache=str(tmp_path / "a.npz"), thin_rng=(80, 700))
    b = build(seed=3, P=4, D=40, cache=str(tmp_path / "b.npz"), thin_rng=(80, 700))
    assert a["R"].shape == (4, 40, len(GRID))
    assert np.allclose(a["R"], b["R"])
    assert (a["R"] >= 0).all()
