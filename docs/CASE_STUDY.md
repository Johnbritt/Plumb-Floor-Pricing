# PLUMB Case Study

**A floor-pricing partner for ad ops: a statistics layer that proposes, an agent that can refuse, and a human who decides.**

By J John Britto, Head of Product. Solo submission, 100xEngineers Cohort 7 capstone.

*All numbers in this study come from a synthetic sample dataset. My real data is official and confidential, so none of it is used here. The sample world is built so the best floor is known for every placement and day, which is what lets decisions be scored properly.*

## The problem

Publishers set a price floor on each ad placement: the minimum bid an auction will accept. Set it too low and you leave money on the table. Set it too high and the auction goes unfilled. In most ad ops teams the floor is nudged by hand, placement by placement, on a belief about fill rate. Nobody can see the revenue curve, and nobody knows whether last week's change helped or whether a bidder outage, a demand surge or a reporting glitch made it look that way.

Two failure modes follow. Good moves are never made because the evidence is unclear, and bad moves are made because a one-day swing was read as a trend.

## The solution

PLUMB splits the job in three, and each part does only what it is good at.

1. **Statistics layer.** Fits revenue per 1,000 requests against the log of the floor over the last 21 days and estimates the gain from moving. The step is capped, and it shrinks when confidence is low.
2. **Agent that can refuse.** Reads the ops notes ("Bidder X paused until Friday") and the data-quality signals, and returns a trust plan: hold, exclude the last day, change the window, adjust direction. It never returns a price. It refuses only for data-quality reasons: thin traffic, almost no floor variation, an outlier last day, or too little history.
3. **Human decides.** Every recommendation lands in a queue with the evidence beside it. Ops accepts, edits or rejects, and the reason is logged.

## What was built

- **Sample-data generator.** 40 placement cells over 180 days. Second-price auction with a floor, daily demand shocks, four event types (bidder outage, demand surge, reporting glitch, demand regime shift) and free-text ops notes, including decoys and benign notes.
- **Engine and agent.** The statistics layer, the refusal rules, and an agent interface with two backends: an offline keyword stand-in (produced every number below) and a Claude backend (wired and unit-tested with a mock, not yet run against the live API).
- **Evaluation harness.** Closed loop with common random numbers, a 60-day burn-in, six arms, and cluster bootstrap intervals over cells.
- **Working web app.** FastAPI, SQLite and a browser UI: decision queue, per-cell evidence, accept/edit/reject with reasons, CSV upload, export of floors and decisions. Deploys with Docker or Render.
- **Clickable demo.** A static product demo with the same queue, hosted publicly.
- **Tests and CI.** 11 automated tests, GitHub Actions passing.

## How it was tested

Thresholds were tuned on 10 development cells of one sample world, then frozen and scored on a second, fresh world (new seed, thinner cells) that was never used for tuning. That gives 4,800 floor decisions across 40 cells, 462 of them during an event. A decision is scored by the true revenue of the chosen floor divided by the revenue at the true best floor.

| Arm | Revenue captured (95% CI) | Refused | Harmful moves |
|---|---|---|---|
| Ops alone (modelled manual pricing) | 78.7% (74.0 to 84.0) | 0% | 16.3% |
| Stats layer, full step | 98.3% (97.6 to 98.8) | 0% | 6.2% |
| Stats layer, confidence-scaled step | 96.1% (93.4 to 97.9) | 0% | 2.6% |
| Stats plus rule refusal | 95.0% (90.5 to 97.7) | 17.7% | 3.0% |
| Stats plus agent refusal | 95.0% (91.4 to 97.3) | 20.3% | 2.9% |
| Ops plus agent (the pair) | 95.3% (92.6 to 96.9) | 19.5% | 6.1% |

## What the results show, and what they don't

- **The statistics layer does almost all the work.** About 20 points of captured revenue over the modelled manual process.
- **Refusal buys safety, not dollars.** Harmful moves fall from 6.2% to about 3%, at a cost of 2 to 3 points of revenue.
- **The agent did not beat a plain rule.** The offline stand-in is itself a rule set, so this question stays open until the Claude backend is run.
- **The pair did not beat the model alone.** Refusals hand decisions back to a human whose manual process is the weakest arm, and wrong overrides cost more than catches save.
- **The size of the gap to manual pricing depends on my model of manual pricing.** Read the direction, not the size, until real ops colleagues run that arm.
- **No bidder reaction is modelled.** Real bidders adapt to floors.
- **Two sample worlds, one seed each.** The intervals do not capture world-to-world variation.

## What changed along the way

1. **The first version refused 82% of days.** A hard significance gate was too cautious and cost 1.7 points. It became a confidence-scaled step, with refusal reserved for data-quality problems. Refusals fell to 17.7%.
2. **The first safety metric was wrong.** Exploration jitter made a held floor look harmful. Harm is now defined as a floor moved more than 10% with revenue down more than 1%.
3. **Refusing on thin cells freezes learning.** A refused cell stays stuck at its starting floor. The next iteration pairs "insufficient signal" with a small randomized floor test, or pools thin cells with similar ones.
4. **Holding during an outage can hurt.** An outage removes bidders, which lowers the best floor, so freezing is the wrong response. The agent should adjust direction, not only hold.

## Is the pilot plan any good?

Before proposing a live pilot I tested the pilot design itself on sample data: matched pairs, a shadow week, difference-in-differences on revenue per 1,000 requests, 100 runs per design, plus an A/A placebo and a 25%-adoption case.

- **20 cells and one live week** passes its own success criteria only 26% of the time, and 28% of A/A runs wrongly read a 3% gain. The 5% harm limit sits below the system's own harmful-move rate.
- **40 cells, one shadow week and four live weeks** has a lower bound above zero in 71% of runs, with a 3% A/A false-positive rate.
- **At 25% adoption** almost no pilot passes.
- **Revised criteria:** lower 90% bound above zero, harmful moves at most 0.6 times the matched manual cells, override rate between 5% and 40%. The pilot is falsified if the upper bound is below +3%, or if the override rate is under 2% with no written reasons.
- About 27% of cell-days need a human look, roughly 11 of 40 cells.

## Limits and next steps

1. Run the Claude backend on a sample of cells to settle the agent-versus-rule question. The plan is to run this on a real ad stack with real numbers, calling a custom model through an API.
2. Add the thin-cell randomized floor test and an outage-aware direction change.
3. Run a matched-cell pilot with real ops colleagues using the revised criteria.
4. Replace the modelled manual arm with measured manual decisions.

## Links

- Product demo: https://plumb-floor-pricing-demo.vercel.app
- Code, tests, deploy files and detailed results: https://github.com/Johnbritt/Plumb-Floor-Pricing
- Detailed generated results: `docs/RESULTS_DETAIL.md`
