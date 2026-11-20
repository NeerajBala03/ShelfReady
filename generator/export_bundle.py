"""
Assemble the compact demo bundle consumed by the standalone interactive demo.

Runs the full pipeline + eval (offline, reproducible), folds in the real
Claude-CLI featured listings, and writes data/demo_data.json — a single
self-contained bundle small enough to embed directly in the demo HTML so the
showpiece opens offline with zero setup.
"""
from __future__ import annotations
import json, os, datetime, collections, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import pipeline as P, evaluate as E, rules as R, claude_client

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def _compact(l):
    return {
        "product_id": l["product_id"], "category": l["category"],
        "market": l["market"], "lang": l["lang"], "channel": l["channel"],
        "status": l["status"], "first_pass": l["first_pass"],
        "repair_attempts": l["repair_attempts"],
        "title": l["listing"].get("title", ""),
        "bullets": l["listing"].get("bullets", [])[:4],
        "direction": l["listing"].get("direction", "ltr"),
        "review_reasons": l["review_reasons"],
        "image_fixes": l["image_fixes"],
        "violations_first": [{"code": v["code"], "severity": v["severity"],
                              "message": v["message"]} for v in l["violations_first"]],
        "audit": l["audit"],
        "confidence": l.get("overall_confidence"),
    }


def build():
    catalog = json.load(open(os.path.join(DATA, "catalog.json"), encoding="utf-8"))
    answers = {a["product_id"]: a for a in
               json.load(open(os.path.join(DATA, "answer_key.json"), encoding="utf-8"))}
    run = P.run(catalog=catalog, engine="offline")
    listings, kpis = run["listings"], run["kpis"]
    report = E.evaluate(engine="offline")

    by = lambda key: dict(collections.Counter(l[key] for l in listings))
    review_reason_counts = collections.Counter()
    for l in listings:
        for r in l["review_reasons"]:
            review_reason_counts[r.split(":")[0].split(" — ")[0].strip()[:46]] += 1

    cat_label = {c["category"]: c["category_label"] for c in catalog}
    by_category = collections.Counter(l["category"] for l in listings)

    # --- showcase: one product per defect type + a clean one, all markets/channels ---
    pick = {}
    for pid, a in answers.items():
        d = a["seeded_defect"] or ("clean" if not a["low_res_image"] else "low_res_image")
        pick.setdefault(d, pid)
    showcase = {}
    for d, pid in pick.items():
        recs = [_compact(l) for l in listings if l["product_id"] == pid]
        src = next(p for p in catalog if p["product_id"] == pid)
        showcase[d] = {
            "product_id": pid, "defect": d,
            "defect_note": answers[pid]["defect_note"],
            "supplier": {k: (v or {}).get("value") for k, v in
                         src["supplier_attributes"].items()},
            "supplier_claims": src["supplier_claims"],
            "image": src["image"],
            "listings": recs,
        }

    # --- a concrete repair example (before -> after) ---
    repair_example = None
    for l in listings:
        if l["status"] == "approved_repaired" and l["repair_attempts"] >= 1 \
                and l["violations_first"]:
            repair_example = {
                "product_id": l["product_id"], "profile": l["profile"],
                "market": l["market"], "channel": l["channel"],
                "attempts": l["attempts"],
                "before": l["attempts"][0]["violations"],
                "before_title": None, "after": l["listing"],
                "repair_attempts": l["repair_attempts"]}
            break

    # --- review queue: one item per reviewed product ---
    seen, queue = set(), []
    for l in listings:
        if l["status"] == "review" and l["product_id"] not in seen:
            seen.add(l["product_id"])
            queue.append({
                "product_id": l["product_id"], "category": l["category"],
                "market": l["market"], "profile": l["profile"],
                "reason": l["review_reasons"][0] if l["review_reasons"] else "",
                "confidence": l.get("overall_confidence"),
                "conflicts": l.get("conflicts", []),
                "title": l["listing"].get("title", "")})

    # --- animation stream: balanced sample of cards ---
    stream = []
    per_status = collections.Counter()
    for l in listings:
        if per_status[l["status"]] < 40:
            stream.append({"product_id": l["product_id"], "market": l["market"],
                           "lang": l["lang"], "channel": l["channel"],
                           "category": l["category"], "status": l["status"],
                           "first_pass": l["first_pass"],
                           "repair_attempts": l["repair_attempts"]})
            per_status[l["status"]] += 1

    featured = None
    fp = os.path.join(DATA, "featured_claude.json")
    if os.path.exists(fp):
        featured = json.load(open(fp, encoding="utf-8"))

    rules = R.load_rules()
    bundle = {
        "meta": {
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "engine": kpis["engine"], "rules_version": kpis["rules_version"],
            "claude_cli_available": claude_client.available(),
            "claude_cli_used_for_featured": bool(featured),
        },
        "kpis": kpis,
        "breakdowns": {
            "by_status": by("status"),
            "by_market": by("market"),
            "by_channel": by("channel"),
            "by_category": {cat_label.get(k, k): v for k, v in by_category.items()},
            "review_reasons": dict(review_reason_counts.most_common()),
        },
        "eval": report,
        "rules": {
            "markets": {m: {"label": v["label"], "languages": v["languages"],
                            "direction": v["direction"],
                            "required_attributes": v["required_attributes"],
                            "forbidden_terms": v["forbidden_terms"],
                            "reference": v.get("reference", "")}
                       for m, v in rules["markets"].items()},
            "channels": {c: {"label": v["label"], "title": v["title"],
                             "bullets": v["bullets"], "images": v["images"]}
                         for c, v in rules["channels"].items()},
        },
        "showcase": showcase,
        "repair_example": repair_example,
        "review_queue": queue,
        "stream": stream,
        "featured_claude": featured,
    }
    out = os.path.join(DATA, "demo_data.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(out) / 1024
    print(f"Wrote data/demo_data.json  ({size:.0f} KB)")
    print(f"  listings={kpis['listings']} review={kpis['to_review']} "
          f"showcase={list(showcase)} queue={len(queue)} stream={len(stream)}")
    return bundle


if __name__ == "__main__":
    build()
