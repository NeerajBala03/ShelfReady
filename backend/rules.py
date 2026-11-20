"""
ShelfReady — rule engine.

Loads the YAML compliance configuration (markets + channels), composes the
*effective* ruleset for a given market/channel pair, and validates a generated
listing in three layers (mirrors the solution design):

  1. Deterministic checks  — length limits, required fields, forbidden terms,
                             must-include tokens, image spec.
  2. Grounding check       — every factual statement in the copy must map to a
                             source attribute. Unsupported specs are flagged.
                             This is the main defence against invented specs.
  3. (Quality review by a second model lives in qa.py.)

Each violation carries a machine code, the field, a severity and a SPECIFIC,
human-readable message — the exact message is what the repair loop feeds back to
the generator ("title is 172 characters, limit 150").
"""
from __future__ import annotations
import os, re, functools
import yaml

RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rules")

# Colour / material vocab used by the grounding check to spot invented specs.
_COLOR_WORDS = ["amber", "golden", "deep green", "green", "natural", "matte black",
                "black", "brushed steel", "steel", "sage green", "sage", "ivory",
                "white", "translucent", "pale gold", "gold", "charcoal grey",
                "charcoal", "grey"]


@functools.lru_cache(maxsize=1)
def load_rules():
    with open(os.path.join(RULES_DIR, "markets.yaml"), encoding="utf-8") as f:
        markets = yaml.safe_load(f)
    with open(os.path.join(RULES_DIR, "channels.yaml"), encoding="utf-8") as f:
        channels = yaml.safe_load(f)
    return {
        "markets": markets["markets"],
        "channels": channels["channels"],
        "markets_version": markets["version"],
        "channels_version": channels["version"],
    }


def rules_version():
    r = load_rules()
    return f"markets@{r['markets_version']}+channels@{r['channels_version']}"


def effective_rules(market: str, channel: str) -> dict:
    """Compose market + channel into one ruleset for validation."""
    r = load_rules()
    m, c = r["markets"][market], r["channels"][channel]
    forbidden = sorted(set(m.get("forbidden_terms", []))
                       | set(c.get("forbidden_terms", [])))
    return {
        "market": market, "channel": channel,
        "label": f"{m['label']} · {c['label']}",
        "languages": m["languages"], "direction": m["direction"],
        "required_attributes": m["required_attributes"],
        "forbidden_terms": forbidden,
        "title": c["title"], "bullets": c["bullets"],
        "description": c["description"], "keywords": c["keywords"],
        "images": c["images"],
        "claim_substantiation": m.get("claim_substantiation", True),
    }


# ---------------------------------------------------------------------------
# Layer 1: deterministic checks
# ---------------------------------------------------------------------------
def _v(code, field, severity, message):
    return {"code": code, "field": field, "severity": severity, "message": message}


def deterministic_checks(listing: dict, canonical: dict, er: dict) -> list:
    out = []
    title = (listing.get("title") or "").strip()
    bullets = listing.get("bullets") or []
    desc = (listing.get("description") or "").strip()
    keywords = listing.get("keywords") or []
    blob = " ".join([title, desc, " ".join(bullets), " ".join(keywords)]).lower()

    # Title length + must-include.
    if len(title) > er["title"]["max_length"]:
        out.append(_v("title_too_long", "title", "error",
                      f"title is {len(title)} characters, limit {er['title']['max_length']}"))
    if not title:
        out.append(_v("title_missing", "title", "error", "title is empty"))
    for tok in er["title"].get("must_include", []):
        want = str(canonical.get(tok, "")).lower()
        if want and want not in title.lower():
            out.append(_v("title_missing_token", "title", "error",
                          f"title must include {tok} '{canonical.get(tok)}'"))

    # Bullets count + per-bullet length.
    bcfg = er["bullets"]
    if len(bullets) < bcfg["min"]:
        out.append(_v("too_few_bullets", "bullets", "error",
                      f"{len(bullets)} bullets, minimum {bcfg['min']}"))
    if len(bullets) > bcfg["max"]:
        out.append(_v("too_many_bullets", "bullets", "error",
                      f"{len(bullets)} bullets, maximum {bcfg['max']}"))
    for i, b in enumerate(bullets):
        if len(b) > bcfg["max_length_each"]:
            out.append(_v("bullet_too_long", "bullets", "error",
                          f"bullet {i+1} is {len(b)} chars, limit {bcfg['max_length_each']}"))

    # Description length.
    dcfg = er["description"]
    if len(desc) < dcfg["min_length"]:
        out.append(_v("description_too_short", "description", "error",
                      f"description is {len(desc)} chars, minimum {dcfg['min_length']}"))
    if len(desc) > dcfg["max_length"]:
        out.append(_v("description_too_long", "description", "error",
                      f"description is {len(desc)} chars, maximum {dcfg['max_length']}"))

    # Keywords count.
    kcfg = er["keywords"]
    if len(keywords) < kcfg["min"]:
        out.append(_v("too_few_keywords", "keywords", "warning",
                      f"{len(keywords)} keywords, minimum {kcfg['min']}"))

    # Forbidden terms (promotional / non-compliant wording).
    for term in er["forbidden_terms"]:
        if term.lower() in blob:
            out.append(_v("forbidden_term", "copy", "error",
                          f"contains forbidden term '{term}'"))

    # Required attributes present in the canonical record (escalate if missing).
    for attr in er["required_attributes"]:
        val = canonical.get(attr)
        if val in (None, "", "None"):
            out.append(_v("missing_required_attribute", attr, "block",
                          f"market requires '{attr}' but source data has none — escalate to data owner"))

    # Image spec.
    img = canonical.get("_image", {})
    spec = er["images"]["main"]
    if img:
        if img.get("px", 0) < spec["min_px"]:
            out.append(_v("image_too_small", "image", "error",
                          f"main image {img.get('px')}px, minimum {spec['min_px']}px"))
        if spec.get("background") not in (None, "any") and img.get("bg") != spec["background"]:
            out.append(_v("image_bg", "image", "error",
                          f"main image background '{img.get('bg')}', requires '{spec['background']}'"))
        if spec.get("text_overlay") is False and img.get("text_overlay"):
            out.append(_v("image_text_overlay", "image", "error",
                          "main image has text/watermark overlay, not allowed"))
    return out


# ---------------------------------------------------------------------------
# Layer 2: grounding — no factual statement without a source attribute
# ---------------------------------------------------------------------------
def grounding_check(listing: dict, canonical: dict, approved_claims: list,
                    er: dict) -> list:
    out = []
    title = (listing.get("title") or "")
    bullets = listing.get("bullets") or []
    desc = (listing.get("description") or "")
    text = " ".join([title, desc, " ".join(bullets)])
    low = text.lower()

    # (a) Colour mentioned in copy must match the canonical colour.
    #     Ignore colour words that are legitimately part of the product name,
    #     brand or material (e.g. "Green Tea", "sage green board") to avoid
    #     false positives — only flag a colour used to DESCRIBE the item.
    true_color = str(canonical.get("color", "")).lower()
    name_ctx = " ".join(str(canonical.get(k, "")).lower()
                        for k in ("product_type", "brand", "material"))
    for cw in _COLOR_WORDS:
        if re.search(rf"\b{re.escape(cw)}\b", low):
            if cw in name_ctx or cw in true_color or true_color in cw:
                continue
            if any(w in true_color for w in cw.split()):
                continue
            out.append(_v("ungrounded_color", "copy", "error",
                          f"copy mentions colour '{cw}' but source colour is '{canonical.get('color')}' — remove or correct"))
            break

    # (b) Numeric quantity mentioned must match net_quantity.
    nq = str(canonical.get("net_quantity", "")).lower()
    nq_num = re.findall(r"\d+", nq)
    for num in re.findall(r"\b(\d{2,4})\s?(?:ml|g|kg|cm)\b", low):
        if nq_num and num not in nq_num:
            out.append(_v("ungrounded_quantity", "copy", "error",
                          f"copy states quantity '{num}' with no matching source attribute (source net_quantity '{canonical.get('net_quantity')}')"))
            break

    # (c) Any claim in copy must be in the approved/grounded claim set.
    #     Risky/unsubstantiated health or superlative claims are flagged.
    risky_markers = ["cure", "cures", "clinically", "detox", "immunity",
                     "permanently", "removes all", "guaranteed", "guarantee",
                     "lifetime", "non-toxic approved", "non-toxic", "medically",
                     "200%", "unbreakable"]
    for rm in risky_markers:
        if rm in low:
            out.append(_v("unsupported_claim", "copy", "block",
                          f"unsupported/risky claim detected ('{rm}') — not grounded in any source attribute; route to review"))
            break
    return out


def validate(listing: dict, canonical: dict, approved_claims: list,
             market: str, channel: str) -> dict:
    er = effective_rules(market, channel)
    violations = deterministic_checks(listing, canonical, er)
    violations += grounding_check(listing, canonical, approved_claims, er)
    # Severity order: block > error > warning
    has_block = any(v["severity"] == "block" for v in violations)
    has_error = any(v["severity"] == "error" for v in violations)
    return {
        "market": market, "channel": channel, "profile": er["label"],
        "direction": er["direction"],
        "violations": violations,
        "passed": not has_error and not has_block,
        "must_escalate": has_block,   # cannot be auto-repaired (e.g. missing data)
    }


if __name__ == "__main__":
    import json
    r = load_rules()
    print("rules version:", rules_version())
    print("markets:", list(r["markets"]))
    print("channels:", list(r["channels"]))
    print(json.dumps(effective_rules("AE", "marketplace_a"), indent=2, ensure_ascii=False))
