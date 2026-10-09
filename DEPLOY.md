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

## Free hosting for a demo (Render)

`render.yaml` is a blueprint for Render's free web service. No card is needed, and it runs the app as plain Python, so there is no Docker build.

1. Sign in at render.com with GitHub and allow it to read the `Plumb-Floor-Pricing` repo.
2. New, then Blueprint, pick the repo, and apply. Wait for the first deploy to go live (a few minutes).
3. Open the `onrender.com` URL it gives you.

What the free tier means in practice (Render's own limits, [render.com/docs/free](https://render.com/docs/free)):
- It spins down after 15 minutes without traffic, and the next visit takes about a minute to wake it. Open the link a couple of minutes before anyone reviews it.
- The filesystem is ephemeral: every restart or spin-down wipes the database. The synthetic demo data reloads automatically, but decisions and uploads are lost.
- 750 free instance hours a month.

Because the data resets and is open to anyone with the link by default, use this for the synthetic demo only. Never upload real data to it. To require a login, add `PLUMB_USER` and `PLUMB_PASSWORD` in the Render dashboard.

For a deployment that keeps its data, use a paid Render plan with a disk, a small VPS with the Docker command above, or any host that gives you a persistent volume.

## Free static hosting for the product demo (Vercel)

The product demo (`demo/index.html`) is one self-contained page, so it hosts for free on Vercel, Netlify or GitHub Pages. It never sleeps, has no cold start, and the Case study tab opens directly at `/#case`.

On Vercel: Add New, Project, import the repo, set **Root Directory** to `demo`, set Framework Preset to **Other**, and Deploy. Leave the build command empty.

This hosts the demo only. It does not run the web app, because Vercel runs Python as short-lived serverless functions with no persistent disk, so the app's SQLite file and saved decisions would not stay put. To run the full app there you would need to move storage to a hosted database such as Postgres. Use Render (above) or a VPS for the app.

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
