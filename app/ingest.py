"""CSV ingestion with validation. Accepts revenue per 1k requests directly, or revenue in dollars."""
import io
import re

import pandas as pd

REQ = ["cell_id", "date", "requests", "floor_cpm"]


class DataError(ValueError):
    pass


def _norm(df):
    df = df.copy()
    df.columns = [re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower()).strip("_") for c in df.columns]
    return df


def read_csv(raw: bytes):
    try:
        return pd.read_csv(io.BytesIO(raw))
    except Exception as e:  # noqa: BLE001
        raise DataError(f"Could not read the file as CSV: {e}")


def ingest_daily(conn, df):
    df = _norm(df)
    missing = [c for c in REQ if c not in df.columns]
    if missing:
        raise DataError("Missing columns: " + ", ".join(missing) + ". Expected cell_id, date, requests, floor_cpm and either revenue_per_1k_requests or revenue_usd.")
    if "revenue_per_1k_requests" in df.columns:
        rpm = pd.to_numeric(df["revenue_per_1k_requests"], errors="coerce")
    elif "revenue_usd" in df.columns:
        rpm = pd.to_numeric(df["revenue_usd"], errors="coerce") / pd.to_numeric(df["requests"], errors="coerce") * 1000.0
    else:
        raise DataError("Need revenue_per_1k_requests or revenue_usd.")
    out = pd.DataFrame(dict(cell_id=df["cell_id"].astype(str).str.strip(), date=pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d"),
                            requests=pd.to_numeric(df["requests"], errors="coerce"), floor=pd.to_numeric(df["floor_cpm"], errors="coerce"), rpm=rpm))
    bad = out.isna().any(axis=1)
    if bad.all():
        raise DataError("No valid rows. Check the date format (YYYY-MM-DD) and that numbers are numeric.")
    out = out[~bad]
    out = out[(out.requests > 0) & (out.floor > 0) & (out.rpm >= 0)]
    if out.empty:
        raise DataError("No rows with positive requests and floor.")
    conn.executemany("INSERT OR REPLACE INTO daily VALUES (?,?,?,?,?)", out[["cell_id", "date", "requests", "floor", "rpm"]].itertuples(index=False, name=None))
    return int(len(out)), int(bad.sum())


def ingest_notes(conn, df):
    df = _norm(df)
    missing = [c for c in ["cell_id", "date", "text"] if c not in df.columns]
    if missing:
        raise DataError("Missing columns: " + ", ".join(missing) + ". Expected cell_id, date, text.")
    out = pd.DataFrame(dict(cell_id=df["cell_id"].astype(str).str.strip(), date=pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d"),
                            text=df["text"].astype(str).str.strip())).dropna()
    out = out[out.text != ""]
    before = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    conn.executemany("INSERT OR IGNORE INTO notes VALUES (?,?,?)", out.itertuples(index=False, name=None))
    return int(conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] - before)
