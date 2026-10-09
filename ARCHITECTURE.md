# Architecture

One loop, run every day for every placement cell.

```
logs  ->  statistics layer  ->  agent layer  ->  engine  ->  ops review  ->  floor applied
 ^                                                                                   |
 +------------------------------- next day's outcome ---------------------------------+
```

## Statistics layer (`engine.stats_fit`)
- OLS quadratic fit of revenue per 1,000 requests against `ln(floor / current)` over a 21-day window.
- Proposed floor is the best point within a step cap of 0.25 in log space.
- Returns the predicted gain, its standard error from the covariance matrix, a z score, and whether the fit is concave.
- Small random dither (5%) on applied floors keeps the curve identifiable.

## Agent layer (`agents.py`)
Receives the statistics summary and recent ops notes. Returns only this plan:

```json
{
  "hold_reason": "insufficient_signal: demand partner outage reported",
  "exclude_last": 0,
  "window": null,
  "direction": "both",
  "step_scale": 1.0,
  "evidence": ["Bidder-H endpoint returning 5xx since 09:00"],
  "strength": "strong"
}
```

The agent edits how far to trust the number, never the number. `heuristic_agent` is an offline keyword stand-in and produced every result in this repo. `make_llm_agent` calls Claude with the same contract and has only been mock-tested.

## Engine (`engine.decide_system`)
- Hard refusals (data quality only): too little history, floor variation below 0.04, thin traffic, an outlier last day.
- Otherwise the step is scaled by confidence (`z / zfull`, halved when the fit is not concave) and capped.
- Applies the agent's plan: hold, drop the last N days, shorten the window, raise-only, or halve the step.

## Human
Accept, hold, or set a floor. Refusals return to ops with the reason. On the sample data this is a parameterised model (accept, catch and false-override rates) swept in a sensitivity analysis.

## Data generator (`sim.py`)
Second-price auction with a reserve (the floor), lognormal bidders with participation probability, Monte Carlo revenue curve per cell and day over a 72-point floor grid, so the best floor is known exactly. Four event types (outage, surge, reporting glitch, regime shift), each of which may leave a free-text ops note, plus decoy, benign and noise notes.

## Evaluation (`evaluate.py`)
Closed loop (each arm lives with its own floor history), common random numbers across arms, 60-day burn-in under the manual heuristic, decisions for days 60 to 179, cluster bootstrap over cells. Gates are tuned on world 1 development cells, frozen, then scored on a fresh world 2.

## Web app (`app/`)
- `store.py`: SQLite tables for daily rows, notes, decisions (with a snapshot of what PLUMB showed) and cached agent plans.
- `ingest.py`: CSV validation and upsert. Accepts revenue per 1k requests or revenue in dollars.
- `service.py`: wraps `engine.decide_system` for live data. Recommendations are computed on demand from the stored history, so uploading a new day moves the desk forward with no jobs to run. The agent is called only for cells with a note in the last three days, and plans are cached.
- `main.py`: JSON API plus the static UI, optional HTTP Basic auth, CSV exports (floor sheet, decisions).
- Rules enforced server side: a refused cell cannot be accepted, and setting your own floor needs a written reason.
