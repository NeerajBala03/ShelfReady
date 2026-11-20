# ShelfReady — three-minute demo script

Open `frontend/shelfready-demo-standalone.html` full-screen. Everything below is
on that one page; the numbers come from a real pipeline run over synthetic data.

**Hook (20s).** "Product content for big catalogues is written by hand — every
title, bullet and description, for every market and language. It's slow, it's
inconsistent, and it fails marketplace rules. Here's one source product record.
To launch it in India, Germany and the UAE, someone writes twelve listings by
hand. We do it in one run — and the thing writing them is Claude, through the
CLI, with no API key."

**Run (45s).** Press **Run ShelfReady**. "One hundred synthetic products, four
market-language pairs, three channels — twelve hundred listings." Watch the
counters fill: auto-approved, auto-repaired, routed to human review. "Green sails
through, amber was repaired automatically, red goes to a person. Nobody writes
twelve hundred listings; people review the exceptions."

**Grounding guardrail (40s).** Scroll to the guardrail card. "This is real Claude
output through the CLI. The supplier feed carried a claim — *medically guaranteed
whitening*. Watch what Claude did: it dropped it from the listing and logged
why — a medical claim restricted by marketplace policy. Our own grounding check
then independently confirms nothing unsupported reached the shelf. That's the
whole trust story: no factual statement without a source."

**Repair loop (25s).** Scroll to the repair card. "When a check fails we don't
retry blindly — we send the *exact* failure back. Here: title too long, and a
banned superlative. One pass later it's fixed and compliant. Most failures fix
themselves; only the genuinely hard cases reach a human."

**Localisation (25s).** Scroll to the market tabs. "Same canonical record, four
markets, written natively — not translated. Hindi, German, and right-to-left
Arabic, all generated live through the CLI. Units, tone and search phrasing adapt
per market."

**Numbers (20s).** Scroll to the trust panel. "Because the catalogue has a
held-out answer key and the engine reads only the supplier feed, these are
honest: 100% routing recall and precision, 100% cross-market consistency, zero
unsupported claims released. And the business case — manual authoring for this
run is about 400 hours; ShelfReady needs about 40 hours of review. Ninety percent
less human effort."

**Close (15s).** "Compliance lives as editable config a compliance team owns, not
buried in a prompt. Every listing has an audit trail. Roadmap is live marketplace
connectors. ShelfReady — generate, validate, repair, route. Powered by Claude."

---

### If a judge asks…

- **"Is this just a wrapper around a prompt?"** No — generation is one of five
  stages. The value is the validate/repair loop, claim grounding, risk routing
  and the audit trail around it. Swap the model and the guarantees still hold.
- **"No API key — really?"** `backend/claude_client.py` shells out to
  `claude -p … --output-format json`. It uses your existing login. Cost comes
  from the CLI's own telemetry.
- **"How do I know the numbers aren't self-graded?"** `make eval` scores the
  pipeline against `data/answer_key.json`, which the engine never reads.
- **"What's real vs. simulated in the demo?"** The localisation strip and the
  guardrail are real Claude-CLI output (saved in `data/featured_claude.json`).
  The 1,200-listing dashboard is the deterministic offline engine so it's free
  and reproducible — run `make featured` to regenerate the real ones.
