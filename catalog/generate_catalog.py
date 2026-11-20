"""
ShelfReady — synthetic catalogue generator.

Produces a deterministic, fully synthetic product catalogue plus a ground-truth
"answer key". NOTHING here is real: brands, codes, claims and prices are invented.

Why a ground-truth answer key?  So the eval harness can measure the pipeline
honestly: attribute-extraction accuracy, grounding (no invented specs),
cross-market consistency, and review-routing precision are all scored against
the `truth` block that the generator placed on every product.

Three categories, 100 products.  A controlled share of products carry a seeded
defect so the demo can show real behaviour rather than a happy path:
  * image_conflict   -> product image disagrees with supplier colour/variant
  * missing_mandatory-> a market-mandatory field (e.g. net_quantity) is absent
  * risky_claim      -> supplier text contains a non-compliant claim ("cures ...")
  * low_confidence   -> an attribute arrives with low extraction confidence

Run:  python catalog/generate_catalog.py
Out:  data/catalog.json, data/answer_key.json
"""
from __future__ import annotations
import json, os, random, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data")
SEED = 20261120

# ---------------------------------------------------------------------------
# Category templates.  Each defines the attribute space and plausible values
# for a fully invented product line.
# ---------------------------------------------------------------------------
CATEGORIES = {
    "packaged_food": {
        "label": "Packaged Food",
        "types": ["Organic Honey", "Cold-Pressed Olive Oil", "Masala Blend",
                  "Roasted Almonds", "Green Tea", "Basmati Rice"],
        "brands": ["Amrita Naturals", "Verdano", "Saffronleaf", "Nutriva"],
        "materials": ["glass jar", "tin", "pouch", "carton"],
        "colors": ["amber", "golden", "deep green", "natural"],
        "net_units": ["g", "ml", "kg"],
        "claims_ok": ["no added preservatives", "single origin", "cold pressed"],
        "claims_risky": ["cures diabetes", "clinically proven to detox",
                         "boosts immunity by 200%"],
        "regulated": True,
    },
    "home_kitchen": {
        "label": "Home & Kitchen",
        "types": ["Insulated Steel Bottle", "Cast-Iron Skillet", "LED Desk Lamp",
                  "Ceramic Knife Set", "Bamboo Chopping Board", "Glass Storage Jar"],
        "brands": ["Hearthline", "Nordkoda", "Luma", "Grove & Vale"],
        "materials": ["304 stainless steel", "cast iron", "borosilicate glass",
                      "bamboo", "ABS plastic"],
        "colors": ["matte black", "brushed steel", "sage green", "ivory"],
        "net_units": ["ml", "cm", "piece"],
        "claims_ok": ["BPA-free", "dishwasher safe", "keeps cold 24h"],
        "claims_risky": ["unbreakable guarantee", "lasts a lifetime, certified",
                         "100% non-toxic approved"],
        "regulated": False,
    },
    "personal_care": {
        "label": "Personal Care",
        "types": ["Mineral Sunscreen SPF50", "Gentle Face Wash", "Argan Hair Oil",
                  "Vitamin C Serum", "Aloe Body Lotion", "Charcoal Soap Bar"],
        "brands": ["Dewlume", "Baraka Botanics", "Pure & Co", "Lushen"],
        "materials": ["pump bottle", "tube", "glass dropper bottle", "bar"],
        "colors": ["white", "translucent", "pale gold", "charcoal grey"],
        "net_units": ["ml", "g"],
        "claims_ok": ["dermatologically tested", "fragrance-free", "non-comedogenic"],
        "claims_risky": ["cures acne permanently", "removes all wrinkles in 7 days",
                         "medically guaranteed whitening"],
        "regulated": True,
    },
}

MARKETS = ["IN", "DE", "AE"]            # India, Germany, UAE
COUNTRY_OF_ORIGIN = ["India", "Italy", "Germany", "Spain", "United Arab Emirates"]

# Distribution of seeded defects across the 100 products (rest are clean).
DEFECTS = (["image_conflict"] * 9 + ["missing_mandatory"] * 8 +
           ["risky_claim"] * 8 + ["low_confidence"] * 7)


def _conf(rng, base):
    return round(min(0.99, max(0.35, rng.gauss(base, 0.05))), 2)


def build():
    rng = random.Random(SEED)
    catalog, answers = [], []
    defect_pool = DEFECTS[:]
    rng.shuffle(defect_pool)

    idx = 0
    cat_keys = list(CATEGORIES)
    while idx < 100:
        cat_key = cat_keys[idx % len(cat_keys)]
        cat = CATEGORIES[cat_key]
        pid = f"SKU-{1000 + idx}"
        ptype = rng.choice(cat["types"])
        brand = rng.choice(cat["brands"])
        true_color = rng.choice(cat["colors"])
        material = rng.choice(cat["materials"])
        unit = rng.choice(cat["net_units"])
        qty = rng.choice([100, 200, 250, 330, 500, 750, 1000])
        origin = rng.choice(COUNTRY_OF_ORIGIN)
        mrp = rng.choice([149, 199, 299, 349, 499, 699, 899, 1299])

        # Ground truth (what is really correct for this product).
        truth = {
            "brand": brand, "product_type": ptype, "color": true_color,
            "material": material, "net_quantity": f"{qty} {unit}",
            "country_of_origin": origin, "mrp_inr": mrp,
            "manufacturer_or_importer": f"{brand} Pvt Ltd, {origin}",
            "consumer_care": "care@example-brand.test",
            "responsible_person_eu": f"{brand} EU GmbH, Berlin, Germany",
        }

        # Decide defect for this product.
        defect = defect_pool.pop() if (defect_pool and idx % 4 == 0) else None

        # Supplier-reported attributes carry a source + confidence each.
        def attr(value, source, base=0.9):
            return {"value": value, "source": source, "confidence": _conf(rng, base)}

        supplier = {
            "brand": attr(brand, "supplier_field", 0.97),
            "product_type": attr(ptype, "supplier_field", 0.95),
            "color": attr(true_color, "image", 0.9),
            "material": attr(material, "spec_sheet", 0.88),
            "net_quantity": attr(f"{qty} {unit}", "supplier_field", 0.93),
            "country_of_origin": attr(origin, "supplier_field", 0.9),
            "mrp_inr": attr(mrp, "supplier_field", 0.95),
            "manufacturer_or_importer": attr(truth["manufacturer_or_importer"],
                                             "spec_sheet", 0.9),
            "consumer_care": attr(truth["consumer_care"], "supplier_field", 0.92),
            "responsible_person_eu": attr(truth["responsible_person_eu"],
                                          "spec_sheet", 0.9),
        }
        claims = list(rng.sample(cat["claims_ok"], k=2))
        px = rng.choice([800, 1000, 1200, 1500])
        low_res = rng.random() < 0.05           # a few genuinely too-small assets
        if low_res:
            px = rng.choice([400, 500])
        image = {"desc": f"{true_color} {ptype} in {material}",
                 "bg": rng.choice(["white", "white", "white", "grey"]),
                 "px": px, "text_overlay": rng.random() < 0.06,
                 "shows_color": true_color}

        note = None
        if defect == "image_conflict":
            # Image shows a different colour than supplier data claims.
            wrong = rng.choice([c for c in cat["colors"] if c != true_color])
            image["shows_color"] = wrong
            note = f"image shows {wrong}, supplier says {true_color}"
        elif defect == "missing_mandatory":
            field = rng.choice(["net_quantity", "country_of_origin",
                                "manufacturer_or_importer", "responsible_person_eu"])
            supplier[field] = {"value": None, "source": "supplier_field",
                               "confidence": 0.0}
            note = f"missing mandatory field: {field}"
        elif defect == "risky_claim":
            claims.append(rng.choice(cat["claims_risky"]))
            note = "supplier text contains a non-compliant claim"
        elif defect == "low_confidence":
            supplier["material"]["confidence"] = round(rng.uniform(0.4, 0.58), 2)
            note = "low-confidence attribute from a blurry spec sheet"

        record = {
            "product_id": pid,
            "category": cat_key,
            "category_label": cat["label"],
            "regulated": cat["regulated"],
            "supplier_attributes": supplier,
            "supplier_claims": claims,
            "image": image,
            "raw_text": _raw_text(rng, brand, ptype, material, qty, unit, claims),
        }
        catalog.append(record)
        answers.append({
            "product_id": pid, "category": cat_key, "truth": truth,
            "seeded_defect": defect, "defect_note": note,
            "image_conflict": defect == "image_conflict",
            "missing_mandatory": defect == "missing_mandatory",
            "risky_claim": defect == "risky_claim",
            "low_confidence": defect == "low_confidence",
            "low_res_image": bool(low_res),
            # Any of these should route the product to human review.
            "should_review": (defect is not None) or bool(low_res),
        })
        idx += 1

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "catalog.json"), "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    with open(os.path.join(OUT, "answer_key.json"), "w", encoding="utf-8") as f:
        json.dump(answers, f, indent=2, ensure_ascii=False)

    n_def = sum(1 for a in answers if a["seeded_defect"])
    print(f"Wrote {len(catalog)} products to data/catalog.json")
    print(f"  categories: {sorted(set(c['category'] for c in catalog))}")
    print(f"  seeded defects: {n_def} "
          f"({', '.join(sorted(set(a['seeded_defect'] for a in answers if a['seeded_defect'])))})")
    print(f"Wrote ground-truth answer key to data/answer_key.json")


def _raw_text(rng, brand, ptype, material, qty, unit, claims):
    """A messy supplier blurb the extractor has to read, like a real feed."""
    bits = [f"{brand} {ptype}", f"Made of {material}.",
            f"Net: {qty}{unit}.", "Keep in a cool dry place.",
            " ".join(c.capitalize() + "." for c in claims)]
    rng.shuffle(bits)
    return " ".join(bits)


if __name__ == "__main__":
    build()
