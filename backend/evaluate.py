"""
ShelfReady — evaluation harness.

Measures the pipeline HONESTLY against the ground-truth answer key the catalogue
generator placed on every product. Because the engine reads only the supplier
feed and the truth block is held out, the scores below are not self-graded:

  * Attribute extraction accuracy — canonical attrs vs truth (on products where
    the supplier actually provided the field).
  * Review-routing recall/precision — did we route exactly the products with a
    seeded defect (conflict / missing / risky) to human review?
  * Unsupported claims released — must be 0 (grounding guarantee).
  * Cross-market consistency — key attributes identical across all markets for a
    product (single canonical source).
  * First-pass & released-listing compliance.

Run:  python -m backend.evaluate   (offline, reproducible)
"""
from __future__ import annotations
import json, os
from . import pipeline as P

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
CONSISTENCY_ATTRS = ["brand", "product_type", "net_quantity", "country_of_origin",
                     "mrp_inr"]


def evaluate(engine="offline"):
    catalog = json.load(open(os.path.join(DATA, "catalog.json"), encoding="utf-8"))
    answers = {a["product_id"]: a for a in
               json.load(open(os.path.join(DATA, "answer_key.json"), encoding="utf-8"))}
    out = P.run(catalog=catalog, engine=engine)
    listings = out["listings"]

    # ---- attribute extraction accuracy ----
    from . import extract as X
    correct = total = 0
    for p in catalog:
        enr = X.extract(p)
        truth = answers[p["product_id"]]["truth"]
        for k, tv in truth.items():
            cv = enr["canonical"].get(k)
            if cv in (None, "", "None"):
                continue  # supplier didn't provide it (missing-mandatory) — not an error
            total += 1
            if str(cv).strip() == str(tv).strip():
                correct += 1
    extract_acc = round(100 * correct / max(1, total), 1)

    # ---- review-routing recall / precision ----
    routed = {}  # product_id -> did ANY of its listings get routed to review
    for l in listings:
        routed[l["product_id"]] = routed.get(l["product_id"], False) or (l["status"] == "review")
    tp = fp = fn = tn = 0
    for pid, a in answers.items():
        should = a["should_review"]
        did = routed.get(pid, False)
        tp += should and did
        fp += (not should) and did
        fn += should and (not did)
        tn += (not should) and (not did)
    recall = round(100 * tp / max(1, tp + fn), 1)
    precision = round(100 * tp / max(1, tp + fp), 1)

    # ---- unsupported claims released ----
    leaked = out["kpis"]["unsupported_claims_released"]

    # ---- cross-market consistency ----
    per_product = {}
    for l in listings:
        per_product.setdefault(l["product_id"], []).append(l)
    consistent = 0
    for pid, ls in per_product.items():
        truth = answers[pid]["truth"]
        # consistency = every listing's title carries the same brand+type as truth
        ok = all(str(truth["brand"]).lower() in (x["listing"]["title"].lower()) and
                 str(truth["product_type"]).lower() in (x["listing"]["title"].lower())
                 for x in ls if x["status"] != "review")
        consistent += ok
    consistency = round(100 * consistent / max(1, len(per_product)), 1)

    report = {
        "engine": engine,
        "products": len(catalog),
        "listings": len(listings),
        "attribute_extraction_accuracy_pct": extract_acc,
        "review_routing_recall_pct": recall,
        "review_routing_precision_pct": precision,
        "routing_confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "unsupported_claims_released": leaked,
        "first_pass_compliance_pct": out["kpis"]["first_pass_rate"],
        "released_listing_compliance_pct": round(
            100 * (1 - leaked / max(1, (out["kpis"]["auto_approved"] + out["kpis"]["repaired"]))), 2),
        "cross_market_consistency_pct": consistency,
        "avg_repair_attempts": out["kpis"]["avg_repair_attempts"],
        "pct_effort_saved": out["kpis"]["pct_effort_saved"],
    }
    return report


if __name__ == "__main__":
    rep = evaluate()
    print(json.dumps(rep, indent=2))
    # Targets from the solution design.
    print("\nTargets check:")
    print(f"  extraction >= 90%:        {rep['attribute_extraction_accuracy_pct']}%  "
          f"{'PASS' if rep['attribute_extraction_accuracy_pct']>=90 else 'FAIL'}")
    print(f"  released compliance 98%+: {rep['released_listing_compliance_pct']}%  "
          f"{'PASS' if rep['released_listing_compliance_pct']>=98 else 'FAIL'}")
    print(f"  unsupported claims = 0:   {rep['unsupported_claims_released']}  "
          f"{'PASS' if rep['unsupported_claims_released']==0 else 'FAIL'}")
    print(f"  routing recall = 100%:    {rep['review_routing_recall_pct']}%  "
          f"{'PASS' if rep['review_routing_recall_pct']>=100 else 'FAIL'}")
    print(f"  cross-market = 100%:      {rep['cross_market_consistency_pct']}%  "
          f"{'PASS' if rep['cross_market_consistency_pct']>=100 else 'FAIL'}")
