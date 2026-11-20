# RUN — quickstart

## Fastest: just the demo (zero setup)
Open **`frontend/shelfready-demo-standalone.html`** in any browser. Offline, no
install, no key. Press **Run ShelfReady**.

## Regenerate everything (offline, no key)
```bash
python catalog/generate_catalog.py     # synthetic catalogue + answer key
python generator/export_bundle.py      # full pipeline run -> data/demo_data.json
python frontend/build.py               # build the standalone demo
python -m backend.evaluate             # score vs ground truth
```
or simply `make demo && make eval`.

## Real Claude generations (optional)
Requires the `claude` CLI installed and logged in (`claude --version`).
```bash
python generator/featured.py           # real localisation + guardrail output
python generator/export_bundle.py      # fold them into the demo bundle
python frontend/build.py
```
No `ANTHROPIC_API_KEY` is used anywhere — the pipeline calls the CLI.

## API server
```bash
pip install -r backend/requirements.txt
uvicorn backend.app:app --reload       # http://localhost:8000
#   GET  /                  the interactive demo
#   GET  /api/kpis          cached run KPIs
#   GET  /api/eval          eval vs ground truth
#   GET  /api/review        human review queue
#   POST /api/generate      live generation {product_id, market, lang, channel, engine}
```
`engine:"claude"` in the POST body uses the CLI; `"offline"` (default) uses the
deterministic engine.

## Docker
```bash
docker compose up --build              # http://localhost:8000
```
To use the real CLI from inside the container, mount your logged-in `~/.claude`
and the `claude` binary (see `docker-compose.yml`).

## Notes
- The offline engine is the default and needs no network or key.
- `make eval` is reproducible and reads only the supplier feed, never the answer
  key, so the scores are honest.
- All data is synthetic.
