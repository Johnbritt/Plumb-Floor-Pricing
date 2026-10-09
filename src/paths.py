"""One place for file locations, relative to the repo root, so the code runs from a fresh clone."""
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RESULTS = os.path.join(ROOT, "results")
DATA = os.path.join(ROOT, "data")
DEMO = os.path.join(ROOT, "demo")
DOCS = os.path.join(ROOT, "docs")
CACHE = os.path.join(ROOT, ".cache")          # generated worlds; deterministic from the seeds, git-ignored
for _d in (RESULTS, DATA, DEMO, DOCS, CACHE):
    os.makedirs(_d, exist_ok=True)


def p(folder, name):
    return os.path.join(folder, name)
