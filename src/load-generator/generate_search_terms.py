"""Build an original offline fashion search coverage sample, not shopper telemetry."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from generate_catalog import PRODUCT_TYPES

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "data" / "catalog" / "products.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "search-terms-fashion-1000"
SEED = 20261009
QUOTAS = {
    "product_type": 100,
    "feature": 350,
    "brand": 150,
    "exact": 80,
    "use_case": 100,
    "price": 80,
    "size": 60,
    "synonym": 40,
    "typo": 30,
    "non_product": 10,
}

USE_CASES = {
    "jeans": ("weekend", "casual friday", "travel", "everyday", "concert"),
    "trousers": ("office", "job interview", "summer holiday", "smart casual", "travel"),
    "jackets": ("spring", "autumn", "commuting", "festival", "evening out"),
    "coats": ("winter", "cold weather", "commuting", "city break", "work"),
    "shirts": ("office", "wedding guest", "job interview", "holiday", "dinner"),
    "t-shirts": ("everyday", "summer", "weekend", "festival", "holiday"),
    "knitwear": ("winter", "office", "layering", "cold weather", "weekend"),
    "hoodies": ("weekend", "travel", "lounging", "cold weather", "casual wear"),
    "dresses": ("wedding guest", "graduation", "date night", "summer holiday", "party"),
    "skirts": ("office", "summer", "party", "holiday", "weekend"),
    "shorts": ("summer holiday", "beach", "festival", "weekend", "warm weather"),
    "trainers": ("everyday", "commuting", "city break", "weekend", "casual wear"),
    "boots": ("autumn", "winter", "festival", "commuting", "evening out"),
    "bags": ("commuting", "travel", "work", "weekend", "city break"),
    "accessories": ("summer", "holiday", "festival", "weekend", "casual wear"),
}

ALIASES = (
    ("jeans", "denim pants", "jeans"),
    ("trousers", "pants", "trousers"),
    ("t-shirts", "tee", "t-shirt"),
    ("knitwear", "sweater", "jumper"),
    ("trainers", "sneakers", "trainers"),
    ("bags", "purse", "bag"),
    ("jackets", "jean jacket", "denim jacket"),
    ("boots", "booties", "ankle boots"),
)

MISSPELLINGS = (
    ("jeans", "jeens", "jeans"),
    ("trousers", "trousres", "trousers"),
    ("jackets", "jakcet", "jacket"),
    ("coats", "caot", "coat"),
    ("shirts", "shrit", "shirt"),
    ("t-shirts", "t shrit", "t-shirt"),
    ("knitwear", "jumpr", "jumper"),
    ("hoodies", "hoddie", "hoodie"),
    ("dresses", "dreses", "dresses"),
    ("skirts", "skrit", "skirt"),
    ("shorts", "shrots", "shorts"),
    ("trainers", "trainres", "trainers"),
    ("boots", "booots", "boots"),
    ("bags", "crossbdy bag", "crossbody bag"),
    ("accessories", "basebal cap", "baseball cap"),
)

SERVICE_QUERIES = (
    "returns policy",
    "delivery charges",
    "size guide",
    "track my order",
    "exchange an item",
    "international shipping",
    "contact customer service",
    "gift cards",
    "student discount",
    "care instructions",
)

SHOPPER_MATERIALS = {
    "satin-look fabric": "satin-look",
    "suede-look fabric": "suede-look",
    "textile and synthetic upper": "textile",
    "recycled mesh": "mesh",
}


@dataclass(frozen=True)
class SearchTerm:
    query: str
    intent: str
    category: str
    canonical_query: str


@dataclass(frozen=True)
class Product:
    product_id: str
    title: str
    brand: str
    category: str
    colour: str
    fit: str
    material: str
    skus: tuple[str, ...]


def text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Source field {field} must be a nonempty string.")
    return value.strip()


def read_products(source: Path) -> list[Product]:
    products = []
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError(f"Source line {line_number} must be a product object.")
        variants = raw.get("variants")
        if not isinstance(variants, list) or not variants:
            raise ValueError(f"Source line {line_number} needs variants.")
        skus = []
        for variant in variants:
            if not isinstance(variant, dict):
                raise ValueError(f"Source line {line_number} has an invalid variant.")
            skus.append(text(variant.get("sku"), "sku"))
        products.append(Product(
            text(raw.get("productId"), "productId"),
            text(raw.get("title"), "title"),
            text(raw.get("brand"), "brand"),
            text(raw.get("category"), "category"),
            text(raw.get("colour"), "colour"),
            text(raw.get("fit"), "fit"),
            text(raw.get("material"), "material"),
            tuple(skus),
        ))
    if not products or len({product.product_id for product in products}) != len(products):
        raise ValueError("Source must contain products with unique product IDs.")
    categories = {product.category for product in products}
    if categories != {product_type.category for product_type in PRODUCT_TYPES}:
        raise ValueError("Source must cover the existing 15 fashion categories.")
    return products


def build_terms(products: list[Product], seed: int = SEED) -> list[SearchTerm]:
    rng = random.Random(seed)
    pools: dict[str, list[SearchTerm]] = {intent: [] for intent in QUOTAS}

    def add(intent: str, category: str, query: str, canonical: str | None = None) -> None:
        query = " ".join(query.split()).lower()
        pools[intent].append(SearchTerm(query, intent, category, canonical or query))

    for product_type in PRODUCT_TYPES:
        category = product_type.category
        noun = category if category != "accessories" else "caps"
        for base in sorted({noun, product_type.name.lower()}):
            add("product_type", category, base)
            audiences = ("women",) if product_type.audience == "women" else ("women", "men")
            for audience in audiences:
                for query in (
                    f"{audience}'s {base}", f"{audience}s {base}", f"{base} for {audience}",
                ):
                    add("product_type", category, query)
        for occasion in USE_CASES[category]:
            for query in (f"{occasion} {noun}", f"{noun} for {occasion}",
                          f"looking for {noun} for {occasion}"):
                add("use_case", category, query)
        low, high = product_type.price_range
        price_points = sorted({
            ((low + 9) // 10) * 10,
            ((low + high) // 20) * 10,
            ((high + 9) // 10) * 10,
        })
        for price in price_points:
            add("price", category, f"{noun} under {price} pounds")
            add("price", category, f"{noun} under gbp {price}")
            upper = min(price + 30, price_points[-1])
            if upper > price:
                add("price", category, f"{noun} between {price} and {upper} pounds")
        for size in product_type.sizes:
            add("size", category, f"{noun} size {size}")
            if size != "One Size":
                add("size", category, f"black {noun} size {size}")

    for product in products:
        noun = next(p.name.lower() for p in PRODUCT_TYPES if p.category == product.category)
        material = SHOPPER_MATERIALS.get(product.material, product.material)
        fitted_noun = f"{product.fit} {noun}"
        if product.category == "accessories":
            fitted_noun = {
                "beanie": "beanie",
                "bucket": "bucket hat",
                "baseball": "baseball cap",
                "five-panel": "five-panel cap",
            }[product.fit]
            noun = fitted_noun
        elif product.fit == "regular":
            fitted_noun = f"regular-fit {noun}"
        for query in (
            f"{product.colour} {noun}",
            fitted_noun,
            f"{material} {noun}",
            f"{product.colour} {fitted_noun}",
            f"{product.colour} {material} {noun}",
        ):
            add("feature", product.category, query)
        for query in (product.brand, f"{product.brand} {noun}",
                      f"{product.brand} {product.colour} {noun}",
                      f"{product.brand} {fitted_noun}"):
            add("brand", product.category, query)
        add("exact", product.category, product.title)

    for category, alias, canonical in ALIASES:
        for colour in ("", "black ", "white ", "blue ", "grey "):
            add("synonym", category, f"{colour}{alias}", f"{colour}{canonical}")
    for category, typo, corrected in MISSPELLINGS:
        for prefix in ("", "black "):
            add("typo", category, f"{prefix}{typo}", f"{prefix}{corrected}")
    for query in SERVICE_QUERIES:
        add("non_product", "service", query)

    selected: list[SearchTerm] = []
    seen: set[str] = set()

    def take(pool: list[SearchTerm], count: int) -> None:
        # Round-robin categories so a large product pool cannot dominate coverage.
        buckets: dict[str, list[SearchTerm]] = {}
        for item in pool:
            buckets.setdefault(item.category, []).append(item)
        for bucket in buckets.values():
            rng.shuffle(bucket)
        categories = sorted(buckets)
        rng.shuffle(categories)
        added = 0
        while added < count:
            progress = False
            for category in categories:
                bucket = buckets[category]
                while bucket:
                    item = bucket.pop()
                    key = item.query.casefold()
                    if key not in seen:
                        seen.add(key)
                        selected.append(item)
                        added += 1
                        progress = True
                        break
                if added == count:
                    break
            if not progress:
                raise ValueError(f"Not enough distinct candidates for quota {count}.")

    for intent, count in QUOTAS.items():
        if intent == "product_type":
            heads = [SearchTerm(
                p.category if p.category != "accessories" else "caps",
                intent, p.category,
                p.category if p.category != "accessories" else "caps",
            ) for p in PRODUCT_TYPES]
            take(heads, len(heads))
            take(pools[intent], count - len(heads))
        elif intent == "exact":
            take([SearchTerm(p.product_id.lower(), intent, p.category, p.product_id)
                  for p in products], 20)
            take([SearchTerm(sku.lower(), intent, p.category, sku)
                  for p in products for sku in p.skus], 20)
            take(pools[intent], 40)
        else:
            take(pools[intent], count)
    rng.shuffle(selected)
    return selected


def write_dataset(source: Path, output: Path, seed: int = SEED) -> dict[str, object]:
    products = read_products(source)
    terms = build_terms(products, seed)
    if len(terms) != 1000 or Counter(term.intent for term in terms) != Counter(QUOTAS):
        raise ValueError("Dataset must have exactly 1000 terms and the documented intent quotas.")
    output.mkdir(parents=True, exist_ok=True)
    with (output / "search-terms.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "queryId", "query", "intent", "category", "canonicalQuery",
        ), lineterminator="\n")
        writer.writeheader()
        for index, term in enumerate(terms, 1):
            writer.writerow({
                "queryId": f"fashion-{index:04d}",
                "query": term.query,
                "intent": term.intent,
                "category": term.category,
                "canonicalQuery": term.canonical_query,
            })
    (output / "search-terms.txt").write_text(
        "".join(f"{term.query}\n" for term in terms), encoding="utf-8",
    )
    batches = output / "evaluation-batches"
    batches.mkdir(exist_ok=True)
    generated_paths = [output / "search-terms.csv", output / "search-terms.txt"]
    for start in range(0, len(terms), 100):
        cases = [{
            "name": f"fashion-{index:04d}",
            "request": {"area": "storefront", "collection": "products", "query": term.query},
        } for index, term in enumerate(terms[start:start + 100], start + 1)]
        batch_path = batches / f"batch-{start // 100 + 1:02d}.json"
        batch_path.write_text(
            json.dumps(cases, indent=2) + "\n", encoding="utf-8",
        )
        generated_paths.append(batch_path)
    manifest: dict[str, object] = {
        "datasetVersion": "synthetic-fashion-search-v1",
        "researchDate": "2026-10-09",
        "seed": seed,
        "queryCount": len(terms),
        "uniqueQueryCount": len({term.query.casefold() for term in terms}),
        "language": "en-GB",
        "currency": "GBP",
        "synthetic": True,
        "distribution": "Designed coverage quotas, not measured shopper traffic.",
        "sourceProductCount": len(products),
        "sourceProjectionSha256": hashlib.sha256(json.dumps(
            [asdict(product) for product in products], sort_keys=True,
        ).encode("utf-8")).hexdigest(),
        "intentCounts": dict(sorted(Counter(term.intent for term in terms).items())),
        "categoryCounts": dict(sorted(Counter(term.category for term in terms).items())),
        "tokenCountHistogram": dict(sorted(Counter(
            len(term.query.split()) for term in terms
        ).items())),
        "researchSources": [
            "https://baymard.com/research-articles/ecommerce-search-query-types",
            "https://github.com/amazon-science/esci-data",
        ],
        "files": {
            str(path.relative_to(output)).replace("\\", "/"): {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
            for path in sorted(generated_paths)
        },
        "relevanceJudgments": False,
        "liveSearchVerified": False,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    try:
        manifest = write_dataset(args.source, args.output, args.seed)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Search-term generation failed: {error}\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
