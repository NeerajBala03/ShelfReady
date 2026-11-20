"""
ShelfReady — FastAPI backend.

Serves the interactive demo and exposes the pipeline over HTTP so judges can run
it live. The heavy run is cached in data/demo_data.json (regenerate with
`make data`); per-product generation can hit the real Claude CLI on demand.

    uvicorn backend.app:app --reload     (or: make run)
    GET  /                      -> the interactive demo
    GET  /api/kpis              -> cached run KPIs + breakdowns
    GET  /api/eval              -> eval report vs ground truth
    GET  /api/review            -> human review queue
    GET  /api/catalog           -> synthetic catalogue (summary)
    GET  /api/product/{id}      -> one product + its generated listings
    POST /api/generate          -> generate one listing live
                                   {product_id, market, lang, channel, engine}
    GET  /healthz
"""
from __future__ import annotations
import json, os
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import pipeline as P, rules as R, extract as X, generator as G, claude_client

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")
DEMO = os.path.join(ROOT, "frontend", "shelfready-demo-standalone.html")

app = FastAPI(title="ShelfReady", version="0.1.0")


def _load(name):
    path = os.path.join(DATA, name)
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None


@app.get("/", response_class=HTMLResponse)
def home():
    if os.path.exists(DEMO):
        return open(DEMO, encoding="utf-8").read()
    return "<h1>ShelfReady</h1><p>Run <code>make data</code> then <code>make build</code> to generate the demo.</p>"


@app.get("/healthz")
def healthz():
    return {"ok": True, "claude_cli": claude_client.available(),
            "rules_version": R.rules_version()}


@app.get("/api/kpis")
def kpis():
    d = _load("demo_data.json")
    if not d:
        raise HTTPException(404, "run `make data` first")
    return {"kpis": d["kpis"], "breakdowns": d["breakdowns"], "meta": d["meta"]}


@app.get("/api/eval")
def eval_report():
    d = _load("demo_data.json")
    if d and d.get("eval"):
        return d["eval"]
    from . import evaluate as E
    return E.evaluate()


@app.get("/api/review")
def review_queue():
    d = _load("demo_data.json")
    if not d:
        raise HTTPException(404, "run `make data` first")
    return {"queue": d["review_queue"], "count": len(d["review_queue"])}


@app.get("/api/catalog")
def catalog():
    c = _load("catalog.json")
    if not c:
        raise HTTPException(404, "run `make data` first")
    return [{"product_id": p["product_id"], "category": p["category"],
             "brand": p["supplier_attributes"]["brand"]["value"],
             "product_type": p["supplier_attributes"]["product_type"]["value"]}
            for p in c]


@app.get("/api/product/{product_id}")
def product(product_id: str):
    c = {p["product_id"]: p for p in (_load("catalog.json") or [])}
    if product_id not in c:
        raise HTTPException(404, "unknown product")
    p = c[product_id]
    enr = X.extract(p)
    listings = []
    for market, lang in P.MARKET_LANG:
        for channel in P.CHANNELS:
            listings.append(P.process_listing(p, enr, market, lang, channel))
    return {"product_id": product_id, "enrichment": {
        "conflicts": enr["conflicts"], "missing": enr["missing_mandatory"],
        "low_confidence": enr["low_confidence"],
        "confidence": enr["overall_confidence"]}, "listings": listings}


class GenReq(BaseModel):
    product_id: str
    market: str = "IN"
    lang: str = "en"
    channel: str = "marketplace_a"
    engine: str = "offline"   # "claude" to use the CLI


@app.post("/api/generate")
def generate(req: GenReq):
    c = {p["product_id"]: p for p in (_load("catalog.json") or [])}
    if req.product_id not in c:
        raise HTTPException(404, "unknown product")
    if req.market not in R.load_rules()["markets"]:
        raise HTTPException(400, "unknown market")
    p = c[req.product_id]
    enr = X.extract(p, engine=req.engine)
    result = P.process_listing(p, enr, req.market, req.lang, req.channel,
                               engine=req.engine)
    return JSONResponse(result)
