"""
ShelfReady — Stage 1: ingest & enrich (attribute extraction + conflict detection).

Builds ONE canonical product record from the supplier feed. Each attribute keeps
its source and confidence. Two things that make the output trustworthy:

  * Conflict detection — if the product image shows a colour/variant that
    disagrees with the supplier field, the item is FLAGGED, never guessed.
  * Missing-mandatory detection — a market-required field with no value is marked
    for escalation to the data owner, never filled with plausible text.

By default this runs deterministically (offline) so evals are reproducible. With
engine="claude" the raw supplier blurb is additionally read by the model to
pull attributes from free text — but conflicts/missing are always decided here.
"""
from __future__ import annotations
import json
from . import claude_client

CORE_ATTRS = ["brand", "product_type", "color", "material", "net_quantity",
              "country_of_origin", "mrp_inr", "manufacturer_or_importer",
              "consumer_care", "responsible_person_eu"]

EXTRACT_SYSTEM = (
    "You extract structured product attributes from a messy supplier blurb. "
    "Return STRICT JSON mapping attribute name to value. Use ONLY what the text "
    "states; use null when absent. Never invent values."
)


def extract(product: dict, engine: str = "offline") -> dict:
    """Return a canonical record + extraction metadata (confidence, flags)."""
    sa = product["supplier_attributes"]
    canonical = {k: (sa.get(k, {}) or {}).get("value") for k in CORE_ATTRS}
    confidences = {k: (sa.get(k, {}) or {}).get("confidence", 0.0) for k in CORE_ATTRS}
    sources = {k: (sa.get(k, {}) or {}).get("source") for k in CORE_ATTRS}

    # Optional: read the free-text blurb with Claude to corroborate attributes.
    text_extract, meta = {}, {"engine": "offline", "cost_usd": 0.0}
    if engine == "claude" and claude_client.available():
        try:
            text_extract, meta = claude_client.complete_json(
                f"Supplier text:\n{product.get('raw_text','')}\n"
                f"Extract these attributes as JSON (null if absent): {CORE_ATTRS}",
                system=EXTRACT_SYSTEM)
        except Exception as e:
            meta = {"engine": "offline(fallback)", "error": str(e)[:100], "cost_usd": 0.0}

    # Conflict detection: image colour vs supplier colour.
    img = product.get("image", {})
    conflicts = []
    shown = img.get("shows_color")
    declared = canonical.get("color")
    if shown and declared and shown != declared:
        conflicts.append({
            "field": "color", "supplier": declared, "image": shown,
            "message": f"image shows '{shown}' but supplier colour is '{declared}' — do not guess"})

    # Missing mandatory (across any market) & low-confidence attrs.
    missing = [k for k in CORE_ATTRS if canonical.get(k) in (None, "", "None")]
    low_conf = [k for k, c in confidences.items() if 0 < c < 0.6]

    canonical["product_id"] = product["product_id"]
    canonical["_image"] = img
    overall_conf = round(
        sum(c for c in confidences.values() if c > 0) /
        max(1, len([c for c in confidences.values() if c > 0])), 3)

    return {
        "canonical": canonical,
        "confidences": confidences,
        "sources": sources,
        "conflicts": conflicts,
        "missing_mandatory": missing,
        "low_confidence": low_conf,
        "overall_confidence": overall_conf,
        "text_extract": text_extract,
        "extract_meta": meta,
    }
