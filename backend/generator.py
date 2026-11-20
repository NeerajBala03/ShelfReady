"""
ShelfReady — content generation (Claude CLI + deterministic offline fallback).

Two engines behind one interface:
  * engine="claude"  -> prompts the real Claude model through the CLI client.
  * engine="offline" -> a deterministic, localised template engine that is
                        grounded by construction. Used when the CLI is absent,
                        for bulk dashboard volume, and for reproducible evals.

Both return the SAME listing shape so the pipeline, validator and repair loop
don't care which produced it:

    {title, bullets[], description, keywords[], alt_text, lang}

The generator never invents specifications: it is given only the canonical
attributes and the approved claim set. To *demonstrate* the guardrails, the
offline engine will, on a deterministic subset, draft copy that trips a rule
(an over-long title, a superlative, or a risky supplier claim echoed verbatim)
so the repair loop and review routing have something real to act on.
"""
from __future__ import annotations
import hashlib
from . import claude_client

# --- language scaffolding (synthetic, approximate — Claude path localises properly) ---
L = {
    "en": {"made_of": "Made of", "net": "Net", "origin": "Origin",
           "care": "Customer care", "by": "by", "mrp": "MRP",
           "tagline": "quality you can trust for every home",
           "kw": ["buy online", "premium", "authentic"]},
    "hi": {"made_of": "निर्मित सामग्री", "net": "शुद्ध मात्रा", "origin": "मूल देश",
           "care": "ग्राहक सेवा", "by": "द्वारा", "mrp": "अधिकतम खुदरा मूल्य",
           "tagline": "हर घर के लिए भरोसेमंद गुणवत्ता",
           "kw": ["ऑनलाइन खरीदें", "प्रीमियम", "असली"]},
    "de": {"made_of": "Material", "net": "Füllmenge", "origin": "Herkunft",
           "care": "Kundenservice", "by": "von", "mrp": "UVP",
           "tagline": "Qualität, der Sie für jeden Haushalt vertrauen können",
           "kw": ["online kaufen", "Premium", "original"]},
    "ar": {"made_of": "مصنوع من", "net": "الكمية الصافية", "origin": "بلد المنشأ",
           "care": "خدمة العملاء", "by": "من", "mrp": "السعر",
           "tagline": "جودة يمكنك الوثوق بها لكل منزل",
           "kw": ["اشترِ عبر الإنترنت", "ممتاز", "أصلي"]},
}

GEN_SYSTEM = (
    "You are ShelfReady, a product-content engine for e-commerce catalogues. "
    "You write localised marketplace listings that are factually grounded and "
    "rule-compliant. HARD RULES: (1) Use ONLY the canonical attributes and the "
    "approved claims provided — never invent specifications, materials, sizes or "
    "health benefits. (2) Localise, don't just translate: adapt units, tone and "
    "search phrasing to the market. (3) No superlatives ('best', '#1'), no "
    "medical claims, no promotional filler. (4) Output STRICT JSON only, no prose."
)


def _gen_prompt(canonical, approved_claims, market, channel, lang, rules):
    import json
    return (
        f"Create a {channel} product listing for market {market}, language '{lang}'.\n"
        f"CANONICAL ATTRIBUTES (the only facts you may use):\n"
        f"{json.dumps(canonical, ensure_ascii=False, indent=2)}\n"
        f"APPROVED CLAIMS (the only claims you may make):\n{json.dumps(approved_claims, ensure_ascii=False)}\n"
        f"CHANNEL LIMITS: title<= {rules['title']['max_length']} chars, "
        f"bullets {rules['bullets']['min']}-{rules['bullets']['max']} "
        f"(each <= {rules['bullets']['max_length_each']} chars), "
        f"description {rules['description']['min_length']}-{rules['description']['max_length']} chars, "
        f"keywords {rules['keywords']['min']}-{rules['keywords']['max']}.\n"
        f"Title MUST include the brand and product_type. Forbidden terms: "
        f"{rules['forbidden_terms']}.\n"
        f'Return STRICT JSON: {{"title": str, "bullets": [str], "description": str, '
        f'"keywords": [str], "alt_text": str}}. Write all text in language "{lang}".'
    )


def generate(canonical, approved_claims, market, channel, lang, rules,
             engine="offline"):
    if engine == "claude" and claude_client.available():
        try:
            prompt = _gen_prompt(canonical, approved_claims, market, channel, lang, rules)
            data, meta = claude_client.complete_json(prompt, system=GEN_SYSTEM)
            data.setdefault("lang", lang)
            data["_meta"] = meta
            return data
        except Exception as e:  # fall back, never break the pipeline
            fb = _offline_generate(canonical, approved_claims, market, channel, lang)
            fb["_meta"] = {"engine": "offline(fallback)", "error": str(e)[:120],
                           "cost_usd": 0.0}
            return fb
    out = _offline_generate(canonical, approved_claims, market, channel, lang)
    out["_meta"] = {"engine": "offline", "cost_usd": 0.0}
    return out


def _h(canonical, salt=""):
    key = f"{canonical.get('product_id','')}{canonical.get('market','')}{salt}"
    return int(hashlib.sha1(key.encode()).hexdigest(), 16)


def _offline_generate(canonical, approved_claims, market, channel, lang):
    """Deterministic, grounded draft. Trips rules on a fixed subset on purpose."""
    t = L.get(lang, L["en"])
    brand = canonical.get("brand", "")
    ptype = canonical.get("product_type", "")
    material = canonical.get("material") or ""
    nq = canonical.get("net_quantity") or ""
    origin = canonical.get("country_of_origin") or ""
    h = _h(canonical)

    # --- title (grounded: brand + type + material + qty) ---
    title = f"{brand} {ptype}"
    if material:
        title += f" – {material}"
    if nq:
        title += f", {nq}"
    # Deterministic first-pass defects for the repair demo:
    add_superlative = (h % 4 == 0)          # -> forbidden 'best'
    add_tagline = (h % 3 == 0)              # -> may exceed tight title limits
    if add_superlative:
        title = f"The best {title}"
    if add_tagline:
        title += f" | {t['tagline']}"

    # --- bullets (grounded in approved claims + attributes) ---
    bullets = []
    for c in approved_claims:
        bullets.append(c if lang == "en" else c)   # claim text kept; Claude path localises
    if material:
        bullets.append(f"{t['made_of']}: {material}")
    if nq:
        bullets.append(f"{t['net']}: {nq}")
    if origin:
        bullets.append(f"{t['origin']}: {origin}")
    # keep within a plausible range
    bullets = bullets[:6]

    # --- description ---
    desc = (f"{brand} {ptype}. {t['made_of']} {material}. {t['net']} {nq}. "
            f"{t['origin']}: {origin}. "
            + " ".join((c + ".") for c in approved_claims))
    # pad to minimum length deterministically
    while len(desc) < 130:
        desc += f" {t['tagline']}."

    # --- keywords (grounded tokens + localised search phrases) ---
    keywords = [brand, ptype] + [w for w in ptype.lower().split()] + list(t["kw"])
    keywords = list(dict.fromkeys([k for k in keywords if k]))[:10]

    alt = f"{canonical.get('color','')} {ptype} {brand}".strip()

    return {"title": title.strip(), "bullets": bullets, "description": desc,
            "keywords": keywords, "alt_text": alt, "lang": lang,
            "direction": "rtl" if lang == "ar" else "ltr"}


# ---------------------------------------------------------------------------
# Repair — fix the SPECIFIC violations the validator reported.
# ---------------------------------------------------------------------------
REPAIR_SYSTEM = GEN_SYSTEM + (
    " You will be given a prior listing and the exact rule failures. Return a "
    "corrected listing as STRICT JSON with the same fields, fixing ONLY what the "
    "failures describe, staying grounded in the canonical attributes."
)


def repair(listing, violations, canonical, approved_claims, market, channel,
           lang, rules, engine="offline"):
    if engine == "claude" and claude_client.available():
        try:
            import json
            prompt = (
                f"Fix this {channel}/{market} listing. FAILURES:\n"
                f"{json.dumps([v['message'] for v in violations], ensure_ascii=False)}\n"
                f"PRIOR LISTING:\n{json.dumps(listing, ensure_ascii=False)}\n"
                f"CANONICAL ATTRIBUTES:\n{json.dumps(canonical, ensure_ascii=False)}\n"
                f"APPROVED CLAIMS: {json.dumps(approved_claims, ensure_ascii=False)}\n"
                f"Channel title limit {rules['title']['max_length']} chars. "
                f"Forbidden terms {rules['forbidden_terms']}. "
                f'Return STRICT JSON {{"title","bullets","description","keywords","alt_text"}} in "{lang}".'
            )
            data, meta = claude_client.complete_json(prompt, system=REPAIR_SYSTEM)
            data.setdefault("lang", lang)
            data["_meta"] = meta
            return data
        except Exception:
            pass
    out = _offline_repair(listing, violations, canonical, rules)
    out["_meta"] = {"engine": "offline", "cost_usd": 0.0}
    return out


SUPERLATIVES = ["the best ", "best ", "#1 ", "number one ", "miracle ",
                "die beste ", "beste "]


def _offline_repair(listing, violations, canonical, rules):
    out = dict(listing)
    title = out.get("title", "")
    # strip superlatives / taglines
    low = title.lower()
    for s in SUPERLATIVES:
        idx = low.find(s)
        if idx != -1:
            title = (title[:idx] + title[idx + len(s):])
            low = title.lower()
    if "|" in title:
        title = title.split("|")[0].strip()
    # remove explicit forbidden terms
    for v in violations:
        if v["code"] == "forbidden_term":
            term = v["message"].split("'")[1]
            title = title.replace(term, "").replace("  ", " ")
            out["description"] = out.get("description", "").replace(term, "")
            out["bullets"] = [b.replace(term, "") for b in out.get("bullets", [])]
    # enforce title length
    maxlen = rules["title"]["max_length"]
    if len(title) > maxlen:
        title = title[:maxlen].rsplit(" ", 1)[0].strip()
    # ensure must-include tokens survived the trim
    for tok in rules["title"].get("must_include", []):
        want = str(canonical.get(tok, ""))
        if want and want.lower() not in title.lower():
            title = f"{want} {title}"[:maxlen]
    out["title"] = title.strip(" -|").strip()

    # bullet count / length
    bmax, bmin = rules["bullets"]["max"], rules["bullets"]["min"]
    elen = rules["bullets"]["max_length_each"]
    bullets = [b[:elen] for b in out.get("bullets", [])][:bmax]
    while len(bullets) < bmin:
        bullets.append(f"{canonical.get('product_type','')} — {canonical.get('net_quantity','')}".strip(" —"))
    out["bullets"] = bullets
    out["_repaired"] = True
    return out
