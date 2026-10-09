# Deploying PLUMB

PLUMB is one Python process (FastAPI) with a SQLite file. There is no separate database or build step.

## Run it on any server

```bash
git clone https://github.com/Johnbritt/Plumb-Floor-Pricing && cd Plumb-Floor-Pricing
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-app.txt
export PLUMB_USER=ops PLUMB_PASSWORD='choose-a-long-password' PLUMB_DB=/var/lib/plumb/plumb.db
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://<server>:8000`. The browser asks for the username and password.

## Docker

```bash
docker build -t plumb .
docker run -d --name plumb -p 8000:8000 -v plumb-data:/data \
  -e PLUMB_PASSWORD='choose-a-long-password' plumb
```

The database lives in the `/data` volume, so it survives restarts.

## Render, Railway, Fly

`render.yaml` is a ready blueprint (Docker, 1 GB disk, health check on `/api/health`). Set `PLUMB_PASSWORD` in the dashboard. On any host, mount a persistent disk at `/data`, otherwise the database resets on each deploy.

## Put it behind HTTPS

Basic auth sends the password with every request, so serve it over HTTPS. The simplest route is Caddy:

```
plumb.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

## Using real data

1. Set `PLUMB_SEED_DEMO=0` so it starts empty, or press "Delete all data" on the Data tab.
2. Upload daily rows (`cell_id, date, requests, floor_cpm, revenue_per_1k_requests` or `revenue_usd`) and ops notes (`cell_id, date, text`).
3. Each day: upload the new day, open the Floor desk, decide, export the floor sheet and load it into your ad server.

## Using Claude as the agent

Set `PLUMB_AGENT=claude` and `ANTHROPIC_API_KEY`. The agent is only called for cells that have a note in the last three days, and each plan is cached per cell, day and note set. Treat this as untested against real notes until you have compared it with the keyword rules on a sample.

## Limits to know about

- One process, one SQLite file: fine for hundreds of cells and a few users, not for many writers.
- Basic auth is a shared password. Put it behind your VPN or SSO proxy for anything sensitive.
- PLUMB suggests floors. It does not write to your ad server. The floor sheet is the hand-off.
