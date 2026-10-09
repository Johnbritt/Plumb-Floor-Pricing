"""Loads the synthetic dataset so the product runs with no data of your own."""
import os

import pandas as pd

from .ingest import ingest_daily, ingest_notes

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def seed_demo(conn):
    daily = pd.read_csv(os.path.join(DATA, "synthetic_daily_cells.csv"))
    notes = pd.read_csv(os.path.join(DATA, "synthetic_ops_notes.csv"))
    a, _ = ingest_daily(conn, daily)
    b = ingest_notes(conn, notes)
    return dict(daily_rows=a, notes=b)
