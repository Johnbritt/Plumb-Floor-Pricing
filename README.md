# PLUMB: floor pricing you can defend, or a plain "not enough signal"
100xEngineers C7 capstone (solo). All data is synthetic.

- `src/` simulator, engine, agent layer, evaluation
- `data/` synthetic datasets; `results/` metrics and figures
- `demo/plumb_product.html` offline copy of the product demo
- `docs/CASE_STUDY.md` full write-up; `workflow.json` pipeline; `DEMO_VIDEO_SCRIPT.md`

Run: `pip install -r requirements.txt`, then from `src/`: `python evaluate.py`, `python make_report.py`.
Headline (held-out world, simulation): 95.0% of best-possible revenue vs 78.7% manual; harmful moves 2.9% vs 16.3%.
Limits: the agent here is an offline keyword stand-in; the Claude backend is mock-tested only. No user interviews or pilot yet.

## Pilot simulation
`src/pilot_sim.py` simulates the proposed pilot (matched pairs, shadow week, half of cells on PLUMB) 100 times per design, with an A/A control and a low-adoption case. Run `python3 pilot_sim.py 100 four_weeks` (also `as_written`, `forty_cells`). Results are in `results/pilot_*.json`. Finding: the plan as first written cannot separate a real gain from noise; the revised design is 40 cells for 5 weeks judged on a confidence bound against matched cells.
