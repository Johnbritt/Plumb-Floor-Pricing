"""End-to-end checks of the web app on a temporary database."""
import importlib
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUMB_DB", str(tmp_path / "t.db"))
    monkeypatch.delenv("PLUMB_PASSWORD", raising=False)
    import app.store, app.service, app.main
    importlib.reload(app.store); importlib.reload(app.service); importlib.reload(app.main)
    with TestClient(app.main.app) as c:
        yield c


def test_demo_loads_and_queue_has_calls_and_holds(client):
    m = client.get("/api/meta").json()
    assert m["cells"] == 40 and m["default_as_of"]
    q = client.get("/api/queue").json()
    assert q["summary"]["total"] == 40 and q["summary"]["calls"] > 0 and q["summary"]["holds"] > 0
    for c in q["cells"]:
        if c["refused"]:
            assert c["reason"].startswith(("insufficient_signal", "hold"))
        else:
            assert abs(c["rec"] / c["cur"] - 1) <= 0.29          # step cap of 0.25 in log space


def test_decisions_flow_and_audit_trail(client):
    q = client.get("/api/queue").json(); as_of = q["as_of"]
    call = next(c for c in q["cells"] if not c["refused"]); held = next(c for c in q["cells"] if c["refused"])
    assert client.post("/api/decisions", json=dict(cell_id=held["cell_id"], as_of=as_of, action="accept")).status_code == 422     # cannot accept a refusal
    assert client.post("/api/decisions", json=dict(cell_id=call["cell_id"], as_of=as_of, action="custom", floor=2.0)).status_code == 422   # reason required
    assert client.post("/api/decisions", json=dict(cell_id=call["cell_id"], as_of=as_of, action="custom", floor=2.0, comment="partner call")).json()["final"] == 2.0
    r = client.post("/api/decisions/accept_all", json=dict(as_of=as_of)).json()
    assert r["accepted"] + r["held"] == 39                                       # the one already decided is skipped
    log = client.get("/api/decisions").json()
    assert log["total"] == 40 and log["counts"]["custom"] == 1 and log["override_rate"] == pytest.approx(1 / (1 + r["accepted"]))
    sheet = client.get(f"/api/export/floors?as_of={as_of}").text.splitlines()
    assert sheet[0].startswith("cell_id,for_date,floor_cpm") and len(sheet) == 41
    assert "2.0" in next(l for l in sheet if l.startswith(call["cell_id"]))


def test_upload_validation(client):
    bad = client.post("/api/upload/daily", files={"file": ("x.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")})
    assert bad.status_code == 422 and "Missing columns" in bad.json()["detail"]
    rows = ["cell_id,date,requests,floor_cpm,revenue_usd"] + [f"NEW-1,2026-10-{d:02d},10000,{1 + 0.05 * (d % 5)},{12 + d % 3}" for d in range(1, 21)]
    ok = client.post("/api/upload/daily", files={"file": ("x.csv", io.BytesIO("\n".join(rows).encode()), "text/csv")})
    assert ok.status_code == 200 and ok.json()["loaded"] == 20
    q = client.get("/api/queue").json()
    assert any(c["cell_id"] == "NEW-1" for c in q["cells"])


def test_notes_drive_the_agent(client):
    q = client.get("/api/queue").json()
    outage = [c for c in q["cells"] if c["plan"] and c["plan"]["hold_reason"] and "outage" in c["plan"]["hold_reason"]]
    assert outage, "expected at least one outage hold on the demo day"
    assert outage[0]["refused"]


def test_auth_when_password_set(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUMB_DB", str(tmp_path / "a.db")); monkeypatch.setenv("PLUMB_PASSWORD", "s3cret")
    import app.store, app.service, app.main
    importlib.reload(app.store); importlib.reload(app.service); importlib.reload(app.main)
    with TestClient(app.main.app) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/queue").status_code == 401
        assert c.get("/api/queue", auth=("jb", "wrong")).status_code == 401
        assert c.get("/api/queue", auth=("jb", "s3cret")).status_code == 200
