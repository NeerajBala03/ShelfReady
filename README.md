# ShelfReady

**One product record in. Compliant, localised listings for every market out.**

Product content for large catalogues is written by hand for every market and
language. It is slow, inconsistent, and often non-compliant on marketplaces.
ShelfReady turns one canonical product record into complete, localised,
rule-checked listings — titles, bullets, descriptions, keywords, alt text and
channel-ready images — for every market and channel in a single pipeline run.

It does **not** just ask a model to write text. It runs a **generate → validate
→ repair** loop in which compliance rules are editable data, every claim is
traced back to a source attribute, and anything uncertain is routed to a human.

Built for the UST hackathon. **Powered by Claude through the `claude` CLI — no
API key.** Every product, brand, price and claim in the repo is **synthetic**.

---

## Why Claude via the CLI (no API key)

The whole pipeline talks to Claude by shelling out to the local `claude` CLI in
headless mode (`claude -p … --output-format json`). It uses the operator's
existing Claude login, so there is **zero key management** — ideal for a
hackathon machine or an air-gapped review station that already has Claude.
Cost and latency are read straight from the CLI telemetry, so ShelfReady reports
a true cost-per-listing.

If the CLI is missing, every stage falls back to a **deterministic offline
engine**, so the demo never breaks for a judge and evals are reproducible.
`backend/claude_client.py` is the whole integration.

## See it in 30 seconds

Open **`frontend/shelfready-demo-standalone.html`** in any browser — offline, no
setup. Press **Run ShelfReady** and watch 1,200 listings route into
auto-approve / auto-repair / human review, then read the KPIs, the real
Claude-CLI localisation (incl. right-to-left Arabic), the grounding guardrail and
the review queue.

A hosted copy is published as a private Claude artifact (share from its menu).

## Run it

```bash
make install      # python deps (FastAPI etc.)
make data         # synthetic catalogue + full pipeline run (offline, ~1s)
make build        # build the standalone interactive demo
make eval         # score the pipeline against the ground-truth answer key
make run          # serve API + demo at http://localhost:8000

make featured     # OPTIONAL: real Claude-CLI generations (needs `claude` logged in)
make docker       # build + run in Docker
```

The offline path needs no network and no key. `make featured` is the only step
that calls the real model.

## How it works — five re-runnable stages

1. **Ingest & enrich** (`backend/extract.py`) — map the supplier feed to one
   canonical schema; every attribute keeps its source and confidence; detect
   image-vs-supplier conflicts and missing mandatory fields (flag, never guess).
2. **Generate** (`backend/generator.py`) — Claude returns structured JSON
   (title, bullets, description, keywords, alt text), localised per market,
   grounded only in approved facts.
3. **Validate & repair** (`backend/rules.py`, `backend/pipeline.py`) —
   deterministic checks + claim grounding; the **exact** failure (e.g. "title is
   172 chars, limit 150") is fed back for up to three repairs.
4. **Images** (`backend/images.py`) — resize/normalise to each channel's spec,
   strip overlays, escalate genuinely low-res assets.
5. **Review & learn** (`backend/pipeline.py`) — risk-routed items go to a
   reviewer with source beside copy; every listing carries an audit trail.

## Compliance as configuration

Market and channel rules live in `rules/markets.yaml` and `rules/channels.yaml`
as **versioned, editable data** — a compliance team can change a forbidden term
or a required attribute with no code change. Markets: India (EN/HI, Legal
Metrology-style declarations), Germany (DE, EU responsible-person), UAE (AR,
right-to-left). Channels: brand website + two marketplace profiles.

## Measured against ground truth

The synthetic catalogue ships with a held-out answer key, and the engine reads
only the supplier feed, so the scores are honest (`make eval`):

| Measure | Result |
|---|---|
| Attribute extraction accuracy | 100% |
| Review-routing recall / precision | 100% / 100% |
| Cross-market consistency | 100% |
| Released-listing compliance | 100% |
| Unsupported claims released | 0 |

On one run of 100 products → 1,200 listings: ~67% pass first time, the repair
loop recovers more, and ~21–27% route to human review — every one for a named
reason (source conflict, missing mandatory data, a risky claim, or a low-res
asset), never a black box.

## What makes it defensible

- **Claim-level grounding** — no factual statement without a source attribute.
  In the live guardrail demo, Claude is handed a supplier's "medically guaranteed
  whitening" claim and drops it from the copy, logging why.
- **Compliance as editable config**, not hidden in prompts.
- **Repair loop with specific feedback**, so most failures fix themselves.
- **Audit trail on every listing** — input version, rules version, engine/model,
  repair attempts, decision — defensible to marketplaces and regulators.
- **Learns from reviewer edits** without retraining a model.

## Layout

```
shelfready/
├── README.md · DEMO.md · RUN.md       overview, 3-min pitch, quickstart
├── backend/      claude_client.py  extract.py  generator.py  rules.py
│                 images.py  pipeline.py  evaluate.py  app.py  requirements.txt
├── catalog/      generate_catalog.py        synthetic catalogue + answer key
├── rules/        markets.yaml  channels.yaml compliance as configuration
├── generator/    featured.py  export_bundle.py   real Claude runs + demo bundle
├── frontend/     app_template.html  build.py  shelfready-demo*.html
├── data/         catalog.json  answer_key.json  demo_data.json  featured_claude.json
└── Dockerfile · docker-compose.yml · Makefile · .env.example
```

*Synthetic demo data throughout. Built for the UST hackathon.*
