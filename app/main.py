"""PLUMB web app. Run: uvicorn app.main:app --host 0.0.0.0 --port 8000"""
import base64
import csv
import io
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import service
from .ingest import DataError, ingest_daily, ingest_notes, read_csv
from .seed import seed_demo
from .store import db

STATIC = os.path.join(os.path.dirname(__file__), "static")
USER = os.environ.get("PLUMB_USER", "ops")
PASSWORD = os.environ.get("PLUMB_PASSWORD", "")

@asynccontextmanager
async def lifespan(_app):
    with db() as c:
        if c.execute("SELECT COUNT(*) FROM daily").fetchone()[0] == 0 and os.environ.get("PLUMB_SEED_DEMO", "1") == "1":
            seed_demo(c)
    yield


app = FastAPI(title="PLUMB", version="1.0.0", lifespan=lifespan,
              description="Floor pricing for ad ops: statistics, an agent that can refuse, a person who decides.")


def auth(request: Request):
    """HTTP Basic auth when PLUMB_PASSWORD is set. Returns the actor name."""
    if not PASSWORD:
        return USER
    h = request.headers.get("authorization", "")
    if h.lower().startswith("basic "):
        try:
            u, _, p = base64.b64decode(h[6:]).decode().partition(":")
            if secrets.compare_digest(p, PASSWORD):
                return u or USER
        except Exception:  # noqa: BLE001
            pass
    raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": 'Basic realm="PLUMB"'})


@app.get("/api/health")
def health():
    with db() as c:
        n = c.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
    return dict(status="ok", rows=n, agent=service.agent_backend())


@app.get("/api/meta")
def meta(actor: str = Depends(auth)):
    with db() as c:
        ds = service.dates(c)
        cells = len(service.cell_ids(c))
        notes = c.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        rows = c.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
        rng = c.execute("SELECT MIN(date) a, MAX(date) b FROM daily").fetchone()
    return dict(actor=actor, cells=cells, notes=notes, rows=rows, first=rng["a"], last=rng["b"], dates=ds,
                default_as_of=ds[-1]["date"] if ds else None, agent=service.agent_backend(), params=service.params(),
                auth=bool(PASSWORD), min_history=service.MIN_HISTORY, window_days=service.W_DAYS)


def _as_of(c, as_of):
    ds = service.dates(c)
    if not ds:
        raise HTTPException(409, "No data yet. Load the demo data or upload your own on the Data tab.")
    valid = {d["date"] for d in ds}
    as_of = as_of or ds[-1]["date"]
    if as_of not in valid:
        raise HTTPException(404, f"No decision day for {as_of}. Need at least {service.MIN_HISTORY} days of history.")
    return as_of


@app.get("/api/queue")
def queue(as_of: Optional[str] = None, actor: str = Depends(auth)):
    with db() as c:
        as_of = _as_of(c, as_of)
        cells = service.queue(c, as_of)
    dec = [x for x in cells if x["decision"]]
    return dict(as_of=as_of, target_date=service.target_date(as_of), cells=cells,
                summary=dict(total=len(cells), calls=sum(not x["refused"] for x in cells), holds=sum(x["refused"] for x in cells),
                             decided=len(dec), est_gain_day=round(sum(x["gain_day"] for x in cells if not x["refused"]), 2),
                             with_notes=sum(bool(x["notes"]) for x in cells)))


@app.get("/api/cells/{cell_id}")
def cell(cell_id: str, as_of: Optional[str] = None, actor: str = Depends(auth)):
    with db() as c:
        as_of = _as_of(c, as_of)
        r = service.recommend_cell(c, cell_id, as_of)
        if not r:
            raise HTTPException(404, "Unknown cell")
        hist = c.execute("SELECT date, requests, floor, rpm FROM daily WHERE cell_id=? AND date<=? ORDER BY date DESC LIMIT 60", (cell_id, as_of)).fetchall()
        notes = c.execute("SELECT date, text FROM notes WHERE cell_id=? AND date<=? ORDER BY date DESC LIMIT 15", (cell_id, as_of)).fetchall()
        decs = c.execute("SELECT as_of, ts, actor, action, current_floor, rec_floor, final_floor, comment FROM decisions WHERE cell_id=? ORDER BY id DESC LIMIT 20", (cell_id,)).fetchall()
        r["decision"] = service.decision_state(c, as_of).get(cell_id)
    r["history"] = [dict(x) for x in reversed(hist)]
    r["all_notes"] = [dict(x) for x in notes]
    r["past_decisions"] = [dict(x) for x in decs]
    return r


class DecisionIn(BaseModel):
    cell_id: str
    as_of: str
    action: str = Field(pattern="^(accept|hold|custom)$")
    floor: Optional[float] = Field(default=None, gt=0, lt=1000)
    comment: Optional[str] = Field(default=None, max_length=500)


def _record(c, actor, rec, action, final, comment):
    snap = {k: rec.get(k) for k in ("tier", "req", "cur", "rec", "refused", "reason", "gain_1k", "se", "z", "concave", "plan", "notes")}
    c.execute("INSERT INTO decisions (cell_id, as_of, ts, actor, action, current_floor, rec_floor, refused, reason, final_floor, comment, snapshot) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              (rec["cell_id"], rec["as_of"], datetime.now(timezone.utc).isoformat(timespec="seconds"), actor, action, rec["cur"], rec["rec"],
               int(rec["refused"]), rec["reason"], final, comment, json.dumps(snap, default=list)))


@app.post("/api/decisions")
def decide(body: DecisionIn, actor: str = Depends(auth)):
    with db() as c:
        as_of = _as_of(c, body.as_of)
        rec = service.recommend_cell(c, body.cell_id, as_of)
        if not rec:
            raise HTTPException(404, "Unknown cell")
        if body.action == "accept":
            if rec["refused"] or rec["rec"] is None:
                raise HTTPException(422, "PLUMB refused this cell, so there is no call to accept. Hold it or set your own floor.")
            final = rec["rec"]
        elif body.action == "hold":
            final = rec["cur"]
        else:
            if body.floor is None:
                raise HTTPException(422, "Give the floor you want to set.")
            if not (body.comment or "").strip():
                raise HTTPException(422, "Write a short reason when you set your own floor.")
            final = round(body.floor, 4)
        _record(c, actor, rec, body.action, final, (body.comment or "").strip() or None)
    return dict(ok=True, final=final)


class AllIn(BaseModel):
    as_of: str


@app.post("/api/decisions/accept_all")
def accept_all(body: AllIn, actor: str = Depends(auth)):
    n_acc = n_hold = 0
    with db() as c:
        as_of = _as_of(c, body.as_of)
        st = service.decision_state(c, as_of)
        for rec in service.queue(c, as_of):
            if rec["cell_id"] in st:
                continue
            if rec["refused"] or rec["rec"] is None:
                _record(c, actor, rec, "hold", rec["cur"], "Held: PLUMB refused. " + (rec["reason"] or ""))
                n_hold += 1
            else:
                _record(c, actor, rec, "accept", rec["rec"], None)
                n_acc += 1
    return dict(ok=True, accepted=n_acc, held=n_hold)


@app.post("/api/decisions/reset")
def reset_day(body: AllIn, actor: str = Depends(auth)):
    with db() as c:
        c.execute("DELETE FROM decisions WHERE as_of=?", (body.as_of,))
    return dict(ok=True)


@app.get("/api/decisions")
def decisions(as_of: Optional[str] = None, limit: int = Query(200, le=2000), actor: str = Depends(auth)):
    with db() as c:
        q = "SELECT id, cell_id, as_of, ts, actor, action, current_floor, rec_floor, refused, reason, final_floor, comment FROM decisions"
        args = []
        if as_of:
            q += " WHERE as_of=?"; args.append(as_of)
        rows = [dict(r) for r in c.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()]
        stats = c.execute("SELECT action, COUNT(*) n FROM decisions" + (" WHERE as_of=?" if as_of else "") + " GROUP BY action", args).fetchall()
    n = {r["action"]: r["n"] for r in stats}
    tot = sum(n.values())
    called = n.get("accept", 0) + n.get("custom", 0)
    return dict(rows=rows, counts=n, total=tot, override_rate=(n.get("custom", 0) / called) if called else None)


def _csv(rows, cols, name):
    buf = io.StringIO()
    w = csv.writer(buf); w.writerow(cols)
    for r in rows:
        w.writerow([r.get(k, "") for k in cols])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/export/floors")
def export_floors(as_of: Optional[str] = None, actor: str = Depends(auth)):
    """The floor sheet: one row per cell with the floor to set for the next day. Undecided cells keep the current floor."""
    with db() as c:
        as_of = _as_of(c, as_of)
        cells = service.queue(c, as_of)
    rows = []
    for x in cells:
        d = x["decision"]
        rows.append(dict(cell_id=x["cell_id"], for_date=service.target_date(as_of), floor_cpm=d["final"] if d else x["cur"],
                         status=d["action"] if d else "undecided_keep_current", current_floor=x["cur"], plumb_call=x["rec"] if not x["refused"] else "",
                         held_reason=x["reason"] if x["refused"] else "", comment=(d or {}).get("comment") or ""))
    return _csv(rows, ["cell_id", "for_date", "floor_cpm", "status", "current_floor", "plumb_call", "held_reason", "comment"], f"floors_{service.target_date(as_of)}.csv")


@app.get("/api/export/decisions")
def export_decisions(actor: str = Depends(auth)):
    d = decisions(None, 100000, actor)
    return _csv(d["rows"], ["id", "ts", "actor", "as_of", "cell_id", "action", "current_floor", "rec_floor", "final_floor", "refused", "reason", "comment"], "decisions.csv")


@app.post("/api/upload/daily")
async def upload_daily(file: UploadFile = File(...), actor: str = Depends(auth)):
    raw = await file.read()
    if len(raw) > 50_000_000:
        raise HTTPException(413, "File too large (50 MB max).")
    try:
        df = read_csv(raw)
        with db() as c:
            n, bad = ingest_daily(c, df)
    except DataError as e:
        raise HTTPException(422, str(e))
    return dict(ok=True, loaded=n, skipped=bad)


@app.post("/api/upload/notes")
async def upload_notes(file: UploadFile = File(...), actor: str = Depends(auth)):
    raw = await file.read()
    try:
        df = read_csv(raw)
        with db() as c:
            n = ingest_notes(c, df)
    except DataError as e:
        raise HTTPException(422, str(e))
    return dict(ok=True, added=n)


@app.post("/api/seed")
def seed(actor: str = Depends(auth)):
    with db() as c:
        return dict(ok=True, **seed_demo(c))


@app.post("/api/data/clear")
def clear(confirm: str = "", actor: str = Depends(auth)):
    if confirm != "yes":
        raise HTTPException(422, "Pass confirm=yes to delete all data and decisions.")
    with db() as c:
        for t in ("daily", "notes", "decisions", "plans"):
            c.execute(f"DELETE FROM {t}")
    return dict(ok=True)


@app.get("/api/templates/{kind}")
def template(kind: str):
    if kind == "daily":
        return PlainTextResponse("cell_id,date,requests,floor_cpm,revenue_per_1k_requests\nHOME-TOP,2026-10-01,52000,1.20,0.94\n", media_type="text/csv")
    if kind == "notes":
        return PlainTextResponse("cell_id,date,text\nHOME-TOP,2026-10-01,Bidder-H endpoint returning 5xx since 09:00\n", media_type="text/csv")
    raise HTTPException(404)


@app.get("/")
def index(actor: str = Depends(auth)):
    return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-cache"})


@app.get("/static/{path:path}")
def static_files(path: str, actor: str = Depends(auth)):
    full = os.path.abspath(os.path.join(STATIC, path))
    if not full.startswith(os.path.abspath(STATIC)) or not os.path.isfile(full):
        raise HTTPException(404)
    return FileResponse(full, headers={"Cache-Control": "no-cache"})
