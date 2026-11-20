"""
ShelfReady — the pipeline: ingest -> generate -> validate -> repair -> route.

For every (product, market, language, channel) it runs:
  1. extract (once per product)        [extract.py]
  2. generate a structured listing      [generator.py]
  3. validate: deterministic + grounding [rules.py]
  4. repair up to MAX_REPAIR times, feeding the EXACT failures back
  5. route by risk to human review when it can't / shouldn't be auto-approved

Every listing gets an audit trail (input version, rules version, model/engine,
repair attempts, decision, reviewer slot, cost). KPIs are aggregated for the
dashboard. Fully deterministic in offline mode so results are reproducible.
"""
from __future__ import annotations
import json, os, time
from . import rules as R
from . import extract as X
from . import generator as G
from . import images as IMG

MAX_REPAIR = 3
MARKET_LANG = [("IN", "en"), ("IN", "hi"), ("DE", "de"), ("AE", "ar")]
CHANNELS = ["brand_site", "marketplace_a", "marketplace_b"]

# Manual baseline assumptions (stated, not measured) for the savings story.
MANUAL_MIN_PER_LISTING = 20.0
AUTO_SPOTCHECK_MIN = 0.5
REVIEW_MIN = 6.0

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


def _approved_claims(product):
    """Approved claims = supplier claims minus risky ones (those must be earned).
    The offline generator deliberately keeps risky claims in the *draft* so the
    grounding check can catch them; the approved set is what's truly allowed."""
    risky_markers = ["cure", "cures", "clinically", "detox", "immunity", "permanently",
                     "removes all", "guaranteed", "lifetime", "non-toxic approved",
                     "medically", "200%", "unbreakable"]
    approved, risky = [], []
    for c in product.get("supplier_claims", []):
        (risky if any(m in c.lower() for m in risky_markers) else approved).append(c)
    return approved, risky


def process_listing(product, enr, market, lang, channel, engine="offline"):
    canonical = dict(enr["canonical"])
    canonical["market"], canonical["lang"] = market, lang
    er = R.effective_rules(market, channel)
    approved, risky = _approved_claims(product)

    # Stage 4: prepare the image to this channel's spec (resize/bg/overlay).
    img_result = IMG.process_for_channel(canonical.get("_image", {}),
                                         er["images"]["main"])
    canonical["_image"] = img_result["image"]
    image_fixes = img_result["fixes"]
    image_needs_asset = img_result["needs_better_asset"]

    # For the demo: the draft is given approved claims; risky claims are injected
    # into the draft text by appending them so the guardrail has to catch them.
    draft_claims = approved + risky  # naive first draft includes risky supplier text
    cost = 0.0
    attempts = []

    listing = G.generate(canonical, draft_claims, market, channel, lang, er, engine=engine)
    cost += (listing.get("_meta", {}) or {}).get("cost_usd", 0.0)
    result = R.validate(listing, canonical, approved, market, channel)
    attempts.append({"attempt": 0, "violations": result["violations"],
                     "passed": result["passed"], "engine": listing.get("_meta", {}).get("engine")})
    first_pass = result["passed"]

    n = 0
    while (not result["passed"]) and (not result["must_escalate"]) and n < MAX_REPAIR:
        n += 1
        listing = G.repair(listing, result["violations"], canonical, approved,
                           market, channel, lang, er, engine=engine)
        cost += (listing.get("_meta", {}) or {}).get("cost_usd", 0.0)
        result = R.validate(listing, canonical, approved, market, channel)
        attempts.append({"attempt": n, "violations": result["violations"],
                         "passed": result["passed"],
                         "engine": listing.get("_meta", {}).get("engine")})

    # --- routing decision ---
    reasons = []
    if enr["conflicts"]:
        reasons.append("source conflict: " + enr["conflicts"][0]["message"])
    if enr["low_confidence"]:
        reasons.append("low-confidence attribute(s): %s — verify before publish"
                       % ", ".join(enr["low_confidence"]))
    if result["must_escalate"]:
        blk = next((v for v in result["violations"] if v["severity"] == "block"), None)
        reasons.append(blk["message"] if blk else "mandatory check failed")
    if image_needs_asset:
        reasons.append("image below channel minimum — request higher-res asset")
    # "still failing" only counts non-image violations the repair loop couldn't fix.
    other_unfixed = [v for v in result["violations"]
                     if v["severity"] == "error" and v["code"] != "image_too_small"]
    if other_unfixed and not result["must_escalate"]:
        reasons.append("still failing after %d repair attempts: %s"
                       % (MAX_REPAIR, other_unfixed[0]["message"]))
    if product.get("regulated") and risky:
        reasons.append("regulated category with claim(s) requiring review")

    if reasons:
        status = "review"
    elif first_pass:
        status = "approved_auto"
    else:
        status = "approved_repaired"

    minutes = (AUTO_SPOTCHECK_MIN if status != "review" else REVIEW_MIN)

    audit = {
        "product_id": product["product_id"],
        "input_version": "catalog@2026.11",
        "rules_version": R.rules_version(),
        "engine": listing.get("_meta", {}).get("engine", engine),
        "model": listing.get("_meta", {}).get("model"),
        "repair_attempts": n,
        "first_pass": first_pass,
        "decision": status,
        "reviewer": None if status == "review" else "auto",
        "cost_usd": round(cost, 6),
    }
    return {
        "product_id": product["product_id"],
        "category": product["category"],
        "market": market, "lang": lang, "channel": channel,
        "profile": result["profile"], "direction": result["direction"],
        "status": status, "first_pass": first_pass, "repair_attempts": n,
        "review_reasons": reasons,
        "image_fixes": image_fixes,
        "conflicts": enr["conflicts"],
        "overall_confidence": enr["overall_confidence"],
        "violations_first": attempts[0]["violations"],
        "violations_final": result["violations"],
        "listing": {k: listing[k] for k in
                    ("title", "bullets", "description", "keywords", "alt_text", "lang", "direction")
                    if k in listing},
        "attempts": attempts,
        "audit": audit,
        "review_minutes": minutes,
        "cost_usd": round(cost, 6),
    }


def run(catalog=None, engine="offline", limit=None,
        market_lang=None, channels=None, progress=None):
    if catalog is None:
        catalog = json.load(open(os.path.join(DATA, "catalog.json"), encoding="utf-8"))
    if limit:
        catalog = catalog[:limit]
    mlp = market_lang or MARKET_LANG
    chans = channels or CHANNELS

    listings, t0 = [], time.time()
    for pi, product in enumerate(catalog):
        enr = X.extract(product, engine=engine)
        for market, lang in mlp:
            for channel in chans:
                listings.append(process_listing(product, enr, market, lang,
                                                 channel, engine=engine))
        if progress:
            progress(pi + 1, len(catalog))
    wall = time.time() - t0
    return summarise(listings, catalog, wall)


def summarise(listings, catalog, wall_seconds):
    n = len(listings)
    by_status = {}
    for l in listings:
        by_status[l["status"]] = by_status.get(l["status"], 0) + 1
    auto = by_status.get("approved_auto", 0)
    repaired = by_status.get("approved_repaired", 0)
    review = by_status.get("review", 0)
    first_pass = sum(1 for l in listings if l["first_pass"])
    final_ok = auto + repaired
    total_cost = round(sum(l["cost_usd"] for l in listings), 4)
    released = [l for l in listings if l["status"] != "review"]
    # unsupported claims that slipped into RELEASED copy (should be zero)
    leaked = sum(1 for l in released
                 if any(v["code"] in ("unsupported_claim", "forbidden_term",
                                      "ungrounded_color", "ungrounded_quantity")
                        for v in l["violations_final"]))
    avg_repair = round(sum(l["repair_attempts"] for l in listings) / max(1, n), 2)

    manual_hours = round(n * 20.0 / 60.0, 1)
    shelf_hours = round(sum(l["review_minutes"] for l in listings) / 60.0, 1)
    saved_hours = round(manual_hours - shelf_hours, 1)

    kpis = {
        "products": len(catalog),
        "listings": n,
        "markets": sorted(set(l["market"] for l in listings)),
        "languages": sorted(set(l["lang"] for l in listings)),
        "channels": sorted(set(l["channel"] for l in listings)),
        "first_pass_rate": round(100 * first_pass / max(1, n), 1),
        "final_pass_rate": round(100 * final_ok / max(1, n), 1),
        "auto_approved": auto,
        "repaired": repaired,
        "to_review": review,
        "review_rate": round(100 * review / max(1, n), 1),
        "avg_repair_attempts": avg_repair,
        "unsupported_claims_released": leaked,
        "total_cost_usd": total_cost,
        "cost_per_listing_usd": round(total_cost / max(1, n), 5),
        "wall_seconds": round(wall_seconds, 2),
        "ms_per_listing": round(1000 * wall_seconds / max(1, n), 1),
        "manual_hours": manual_hours,
        "shelfready_hours": shelf_hours,
        "hours_saved": saved_hours,
        "pct_effort_saved": round(100 * saved_hours / max(0.1, manual_hours), 1),
        "engine": listings[0]["audit"]["engine"] if listings else "offline",
        "rules_version": R.rules_version(),
    }
    return {"kpis": kpis, "listings": listings}


if __name__ == "__main__":
    out = run(engine="offline", limit=6)
    print(json.dumps(out["kpis"], indent=2))
    s = out["listings"][0]
    print("\nsample listing:", s["product_id"], s["market"], s["channel"],
          "->", s["status"])
    print(json.dumps(s["listing"], indent=2, ensure_ascii=False)[:500])
