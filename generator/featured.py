"""
Run a few REAL Claude-CLI generations for the demo's "featured" strip, so the
showpiece includes authentic model output (real Hindi / German / Arabic copy and
a real grounding guardrail), not just the offline template engine.

Saves: data/featured_claude.json   (safe to commit; fully synthetic input)
Cost and latency come straight from the CLI telemetry.
"""
from __future__ import annotations
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import rules as R, extract as X, generator as G, claude_client

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def run():
    if not claude_client.available():
        print("claude CLI not available — skipping real generations"); return
    cat = {p["product_id"]: p for p in json.load(open(os.path.join(DATA, "catalog.json"), encoding="utf-8"))}
    featured = {"generated_with": "claude-cli", "listings": [], "guardrail": None,
                "total_cost_usd": 0.0}

    # 1) Localisation showcase: one clean product across four market-language pairs.
    prod = cat["SKU-1003"]
    enr = X.extract(prod)
    approved = [c for c in prod["supplier_claims"]]
    for market, lang in [("IN", "en"), ("IN", "hi"), ("DE", "de"), ("AE", "ar")]:
        canonical = dict(enr["canonical"]); canonical["market"] = market
        er = R.effective_rules(market, "marketplace_a")
        out = G.generate(canonical, approved, market, "marketplace_a", lang, er,
                         engine="claude")
        meta = out.get("_meta", {})
        featured["total_cost_usd"] += meta.get("cost_usd", 0.0)
        featured["listings"].append({
            "product_id": "SKU-1003", "market": market, "lang": lang,
            "channel": "marketplace_a", "direction": "rtl" if lang == "ar" else "ltr",
            "listing": {k: out.get(k) for k in
                        ("title", "bullets", "description", "keywords", "alt_text")},
            "engine": meta.get("engine"), "model": meta.get("model"),
            "cost_usd": round(meta.get("cost_usd", 0.0), 4),
            "wall_ms": meta.get("wall_ms")})
        print(f"  generated SKU-1003 {market}/{lang}  ${meta.get('cost_usd',0):.3f}  {meta.get('wall_ms')}ms")

    # 2) Guardrail showcase: hand Claude a RISKY supplier claim and see it drop it.
    risky_prod = cat["SKU-1020"]
    enr2 = X.extract(risky_prod)
    all_claims = risky_prod["supplier_claims"]  # includes a non-compliant claim
    risky = [c for c in all_claims if any(m in c.lower() for m in
             ("guaranteed", "medically", "cure", "whitening"))]
    canonical2 = dict(enr2["canonical"]); canonical2["market"] = "IN"
    er2 = R.effective_rules("IN", "marketplace_a")
    out2 = G.generate(canonical2, all_claims, "IN", "marketplace_a", "en", er2,
                      engine="claude")
    val = R.validate(out2, canonical2,
                     [c for c in all_claims if c not in risky], "IN", "marketplace_a")
    text = (out2.get("title", "") + " " + " ".join(out2.get("bullets", [])) + " "
            + out2.get("description", "")).lower()
    dropped = [c for c in risky if c.lower() not in text]
    meta2 = out2.get("_meta", {})
    featured["total_cost_usd"] += meta2.get("cost_usd", 0.0)
    featured["guardrail"] = {
        "product_id": "SKU-1020", "risky_supplier_claims": risky,
        "claims_dropped_by_claude": dropped,
        "validator_passed": val["passed"],
        "listing": {k: out2.get(k) for k in ("title", "bullets", "description")},
        "model": meta2.get("model"), "cost_usd": round(meta2.get("cost_usd", 0.0), 4)}
    print(f"  guardrail SKU-1020: Claude dropped {len(dropped)}/{len(risky)} risky claim(s)")

    featured["total_cost_usd"] = round(featured["total_cost_usd"], 4)
    with open(os.path.join(DATA, "featured_claude.json"), "w", encoding="utf-8") as f:
        json.dump(featured, f, indent=2, ensure_ascii=False)
    print(f"Saved data/featured_claude.json  total ${featured['total_cost_usd']}")


if __name__ == "__main__":
    run()
