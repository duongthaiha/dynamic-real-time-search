#!/usr/bin/env python3
"""Generate a deterministic synthetic fashion catalog and index documents."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


CATALOG_VERSION = "synthetic-fashion-v1"
DEFAULT_SEED = 20260924
DEFAULT_COUNT = 1000
DEFAULT_IMAGE_BASE_URL = "https://cdn.example.com/synthetic-products"
GENERATED_AT = "2026-09-24T00:00:00Z"


@dataclass(frozen=True)
class ProductType:
    category: str
    name: str
    audience: str
    sizes: tuple[str, ...]
    fits: tuple[str, ...]
    materials: tuple[str, ...]
    price_range: tuple[int, int]
    icon: str


PRODUCT_TYPES = (
    ProductType("jeans", "jeans", "unisex", ("W28 L30", "W30 L30", "W30 L32", "W32 L32", "W34 L32", "W36 L32", "W38 L32"), ("baggy", "straight-leg", "slim", "wide-leg", "tapered"), ("cotton denim", "recycled-cotton denim", "stretch denim"), (28, 78), "trousers"),
    ProductType("trousers", "trousers", "unisex", ("XS", "S", "M", "L", "XL", "XXL"), ("relaxed", "wide-leg", "tailored", "tapered"), ("cotton twill", "linen blend", "recycled polyester"), (30, 85), "trousers"),
    ProductType("jackets", "jacket", "unisex", ("XS", "S", "M", "L", "XL", "XXL"), ("oversized", "regular", "cropped", "relaxed"), ("cotton twill", "recycled polyester", "faux leather", "denim"), (42, 140), "jacket"),
    ProductType("coats", "coat", "unisex", ("XS", "S", "M", "L", "XL"), ("oversized", "longline", "regular", "relaxed"), ("wool blend", "recycled polyester", "cotton twill"), (65, 180), "jacket"),
    ProductType("shirts", "shirt", "unisex", ("XS", "S", "M", "L", "XL", "XXL"), ("regular", "relaxed", "oversized", "slim"), ("organic cotton", "linen blend", "viscose"), (24, 68), "top"),
    ProductType("t-shirts", "T-shirt", "unisex", ("XS", "S", "M", "L", "XL", "XXL"), ("regular", "relaxed", "oversized", "slim"), ("organic cotton", "cotton jersey", "recycled-cotton blend"), (14, 42), "top"),
    ProductType("knitwear", "jumper", "unisex", ("XS", "S", "M", "L", "XL", "XXL"), ("regular", "relaxed", "oversized", "cropped"), ("cotton knit", "wool blend", "recycled yarn"), (28, 82), "top"),
    ProductType("hoodies", "hoodie", "unisex", ("XS", "S", "M", "L", "XL", "XXL"), ("regular", "relaxed", "oversized"), ("cotton fleece", "organic-cotton blend", "recycled-cotton blend"), (28, 75), "top"),
    ProductType("dresses", "dress", "women", ("UK 4", "UK 6", "UK 8", "UK 10", "UK 12", "UK 14", "UK 16", "UK 18"), ("bodycon", "relaxed", "slip", "tea", "wrap"), ("viscose", "cotton poplin", "satin-look fabric", "linen blend"), (30, 110), "dress"),
    ProductType("skirts", "skirt", "women", ("UK 4", "UK 6", "UK 8", "UK 10", "UK 12", "UK 14", "UK 16", "UK 18"), ("A-line", "column", "pleated", "wrap"), ("cotton twill", "denim", "satin-look fabric", "linen blend"), (24, 72), "skirt"),
    ProductType("shorts", "shorts", "unisex", ("XS", "S", "M", "L", "XL", "XXL"), ("regular", "relaxed", "tailored", "longline"), ("cotton twill", "linen blend", "denim"), (20, 58), "shorts"),
    ProductType("trainers", "trainers", "unisex", ("UK 3", "UK 4", "UK 5", "UK 6", "UK 7", "UK 8", "UK 9", "UK 10", "UK 11", "UK 12"), ("low-profile", "chunky", "retro", "running-inspired"), ("textile and synthetic upper", "faux leather", "recycled mesh"), (38, 125), "shoe"),
    ProductType("boots", "boots", "unisex", ("UK 3", "UK 4", "UK 5", "UK 6", "UK 7", "UK 8", "UK 9", "UK 10", "UK 11", "UK 12"), ("ankle", "lace-up", "Chelsea", "hiking-inspired"), ("faux leather", "textile and synthetic upper", "suede-look fabric"), (48, 145), "shoe"),
    ProductType("bags", "bag", "unisex", ("One Size",), ("crossbody", "tote", "shoulder", "backpack"), ("recycled polyester", "faux leather", "cotton canvas"), (22, 95), "bag"),
    ProductType("accessories", "cap", "unisex", ("One Size",), ("five-panel", "baseball", "bucket", "beanie"), ("organic cotton", "recycled polyester", "cotton twill"), (12, 38), "accessory"),
)

COLOURS = (
    ("black", "Jet Black", "#242424"),
    ("blue", "Dark Wash Blue", "#315C86"),
    ("blue", "Sky Blue", "#77AEDD"),
    ("navy", "Midnight Navy", "#253451"),
    ("white", "Soft White", "#EDEBE5"),
    ("cream", "Warm Cream", "#D9CDB5"),
    ("grey", "Slate Grey", "#777D84"),
    ("green", "Forest Green", "#3E654A"),
    ("green", "Sage Green", "#8EA58B"),
    ("brown", "Chocolate Brown", "#654536"),
    ("beige", "Stone Beige", "#B8A58B"),
    ("red", "Cherry Red", "#A73538"),
    ("pink", "Dusty Pink", "#C78F9C"),
    ("purple", "Deep Plum", "#664A70"),
    ("orange", "Burnt Orange", "#B76532"),
    ("yellow", "Butter Yellow", "#D8BF63"),
)

BRANDS = (
    "Alder Studio",
    "Arc & Loom",
    "Common Form",
    "Daymark",
    "Field Note",
    "Harbour Standard",
    "Kindred Works",
    "Northline",
    "Parallel Supply",
    "Studio Thread",
)

DETAILS = (
    "clean finish",
    "utility detailing",
    "minimal styling",
    "contrast stitching",
    "tonal hardware",
    "everyday construction",
)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def stable_int(value: str, modulus: int) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:12], 16) % modulus


def money(value: float) -> float:
    return round(value + 1e-9, 2)


def make_variants(
    rng: random.Random,
    product_id: str,
    product_type: ProductType,
    colour_name: str,
    base_price: float,
) -> list[dict[str, Any]]:
    variants = []
    for position, size in enumerate(product_type.sizes, start=1):
        stock = rng.choices((0, rng.randint(2, 18), rng.randint(19, 60)), weights=(1, 5, 2), k=1)[0]
        variants.append(
            {
                "variantId": f"{product_id}-{position:02d}",
                "sku": f"SYN-{product_id.removeprefix('PROD-')}-{position:02d}",
                "size": size,
                "colour": colour_name,
                "price": base_price,
                "currency": "GBP",
                "stockQuantity": stock,
                "isInStock": stock > 0,
            }
        )
    if not any(variant["isInStock"] for variant in variants):
        variants[0]["stockQuantity"] = 5
        variants[0]["isInStock"] = True
    return variants


def product_image_svg(product: dict[str, Any], accent: str, icon: str) -> str:
    title = html.escape(product["title"])
    category = html.escape(product["category"].upper())
    colour = html.escape(product["colourName"])
    shapes = {
        "top": '<path d="M210 245 275 195h50l65 50-38 66-34-22v220H282V289l-34 22z"/>',
        "jacket": '<path d="M220 245 278 190h44l58 55-34 72-26-18v215h-40V299l-26 18z"/><path d="M300 192v322" fill="none" stroke="#fff" stroke-width="7"/>',
        "trousers": '<path d="M245 196h110l-8 318h-58l11-205-11 205h-58z"/>',
        "dress": '<path d="M270 190h60l25 82-22 20 73 222H194l73-222-22-20z"/>',
        "skirt": '<path d="M258 205h84l57 309H201z"/>',
        "shorts": '<path d="M235 225h130l-14 190h-48l-3-94-3 94h-48z"/>',
        "shoe": '<path d="M160 365c70 4 103-42 133-95 28 72 81 103 147 112 25 4 39 25 30 48-8 22-29 34-53 34H179c-38 0-55-18-54-48 1-29 13-53 35-51z"/>',
        "bag": '<rect x="175" y="260" width="250" height="220" rx="25"/><path d="M235 270c0-105 130-105 130 0" fill="none" stroke="#fff" stroke-width="24"/>',
        "accessory": '<path d="M177 332c15-114 230-151 268 10-57-21-179-21-268-10z"/><path d="M177 332c90 1 172 17 226 59-62 22-177 17-248-20z"/>',
    }
    shape = shapes[icon]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800" viewBox="0 0 600 800" role="img" aria-labelledby="title desc">
  <title id="title">{title}</title>
  <desc id="desc">Synthetic catalog illustration of {colour} {html.escape(product["productType"])}</desc>
  <rect width="600" height="800" fill="#F4F1EA"/>
  <rect x="36" y="36" width="528" height="590" rx="18" fill="{accent}" opacity=".16"/>
  <g fill="{accent}" stroke="#202020" stroke-width="8" stroke-linejoin="round">{shape}</g>
  <text x="54" y="680" font-family="Arial, sans-serif" font-size="18" letter-spacing="3" fill="#555">{category}</text>
  <text x="54" y="720" font-family="Arial, sans-serif" font-size="25" font-weight="700" fill="#202020">{html.escape(product["brand"])}</text>
  <text x="54" y="755" font-family="Arial, sans-serif" font-size="20" fill="#444">{colour}</text>
</svg>
"""


def build_product(index: int, rng: random.Random, image_base_url: str) -> tuple[dict[str, Any], str, dict[str, Any]]:
    product_id = f"PROD-{index:06d}"
    product_type = PRODUCT_TYPES[(index - 1) % len(PRODUCT_TYPES)]
    brand = BRANDS[stable_int(f"{product_id}-brand", len(BRANDS))]
    colour, colour_name, hex_value = COLOURS[stable_int(f"{product_id}-colour", len(COLOURS))]
    fit = product_type.fits[stable_int(f"{product_id}-fit", len(product_type.fits))]
    material = product_type.materials[stable_int(f"{product_id}-material", len(product_type.materials))]
    detail = DETAILS[stable_int(f"{product_id}-detail", len(DETAILS))]
    title = f"{brand} {fit} {product_type.name} in {colour_name.lower()}"
    low, high = product_type.price_range
    price = money(rng.randrange(low * 2, high * 2 + 1) / 2)
    variants = make_variants(rng, product_id, product_type, colour_name, price)
    image_name = f"{product_id.lower()}.svg"
    image_url = f"{image_base_url.rstrip('/')}/{image_name}"
    tags = sorted({colour, product_type.category, fit, material.split()[0], product_type.audience})
    product = {
        "schemaVersion": "1.0",
        "catalogVersion": CATALOG_VERSION,
        "productId": product_id,
        "colourWayId": f"CW-{index:06d}",
        "title": title,
        "description": f"A {fit} {product_type.name} made from {material}, finished with {detail}. Designed as a synthetic retail product for search and ranking demonstrations.",
        "brand": brand,
        "department": product_type.audience,
        "category": product_type.category,
        "productType": product_type.name,
        "collection": "products",
        "colour": colour,
        "colourName": colour_name,
        "colourHex": hex_value,
        "fit": fit,
        "material": material,
        "careInstructions": "Machine wash according to the instructions on the care label.",
        "price": price,
        "currency": "GBP",
        "isSearchable": True,
        "isInStock": any(variant["isInStock"] for variant in variants),
        "tags": tags,
        "imageUrl": image_url,
        "imagePath": f"images/{image_name}",
        "images": [
            {"url": image_url, "alt": title, "position": 1}
        ],
        "variants": variants,
        "trendingScore": 0.0,
        "lastTrendingAt": None,
        "trendingTags": [],
        "trendStateVersion": 0,
        "trendScoreVersion": "deterministic-v1",
        "createdAt": GENERATED_AT,
        "updatedAt": GENERATED_AT,
    }
    prompt = {
        "productId": product_id,
        "targetFile": f"images/{image_name.replace('.svg', '.webp')}",
        "prompt": (
            f"Original ecommerce studio photograph of a {colour_name.lower()} {fit} "
            f"{product_type.name} made from {material}, centered on a warm light-grey "
            "seamless background, soft diffused lighting, full product visible, no model, "
            "no text, no logo, no watermark, squarely framed, high detail"
        ),
        "negativePrompt": "brand logo, text, watermark, duplicate product, clutter, cropped item",
    }
    return product, product_image_svg(product, hex_value, product_type.icon), prompt


def search_document(product: dict[str, Any]) -> dict[str, Any]:
    return {
        "@search.action": "upload",
        "productId": product["productId"],
        "title": product["title"],
        "description": product["description"],
        "brand": product["brand"],
        "department": product["department"],
        "category": product["category"],
        "productType": product["productType"],
        "collection": product["collection"],
        "colour": product["colour"],
        "colourName": product["colourName"],
        "fit": product["fit"],
        "material": product["material"],
        "price": product["price"],
        "currency": product["currency"],
        "isSearchable": product["isSearchable"],
        "isInStock": product["isInStock"],
        "tags": product["tags"],
        "imageUrl": product["imageUrl"],
        "availableSizes": [variant["size"] for variant in product["variants"] if variant["isInStock"]],
        "variantSkus": [variant["sku"] for variant in product["variants"]],
        "trendingScore": product["trendingScore"],
        "lastTrendingAt": product["lastTrendingAt"],
        "trendingTags": product["trendingTags"],
        "trendStateVersion": str(product["trendStateVersion"]).zfill(20),
        "trendScoreVersion": product["trendScoreVersion"],
    }


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")


def generate_catalog(output_dir: Path, count: int, seed: int, image_base_url: str, batch_size: int) -> dict[str, Any]:
    if count < 1:
        raise ValueError("count must be at least 1")
    if batch_size < 1 or batch_size > 1000:
        raise ValueError("batch-size must be between 1 and 1000")
    if (output_dir / "image-generation").exists():
        raise ValueError("Catalog has image-generation state; use a different output directory to reseed")

    rng = random.Random(seed)
    images_dir = output_dir / "images"
    batches_dir = output_dir / "azure-search-batches"
    images_dir.mkdir(parents=True, exist_ok=True)
    batches_dir.mkdir(parents=True, exist_ok=True)

    for stale_file in images_dir.glob("prod-*.svg"):
        stale_file.unlink()
    for stale_file in batches_dir.glob("batch-*.json"):
        stale_file.unlink()

    products: list[dict[str, Any]] = []
    prompts: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        product, svg, prompt = build_product(index, rng, image_base_url)
        products.append(product)
        prompts.append(prompt)
        (images_dir / Path(product["imagePath"]).name).write_text(svg, encoding="utf-8", newline="\n")

    write_jsonl(output_dir / "products.jsonl", products)
    write_jsonl(output_dir / "image-prompts.jsonl", prompts)

    documents = [search_document(product) for product in products]
    for offset in range(0, len(documents), batch_size):
        batch_number = offset // batch_size + 1
        batch_path = batches_dir / f"batch-{batch_number:04d}.json"
        batch_path.write_text(
            json.dumps({"value": documents[offset : offset + batch_size]}, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    manifest = {
        "schemaVersion": "1.0",
        "catalogVersion": CATALOG_VERSION,
        "generatedAt": GENERATED_AT,
        "seed": seed,
        "productCount": len(products),
        "variantCount": sum(len(product["variants"]) for product in products),
        "imageCount": len(products),
        "searchBatchCount": (len(products) + batch_size - 1) // batch_size,
        "searchBatchSize": batch_size,
        "imageBaseUrl": image_base_url,
        "files": {
            "products": "products.jsonl",
            "imagePrompts": "image-prompts.jsonl",
            "images": "images/",
            "searchBatches": "azure-search-batches/",
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/catalog"))
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--image-base-url", default=DEFAULT_IMAGE_BASE_URL)
    parser.add_argument("--batch-size", type=int, default=100)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = generate_catalog(
        output_dir=args.output_dir,
        count=args.count,
        seed=args.seed,
        image_base_url=args.image_base_url,
        batch_size=args.batch_size,
    )
    print(
        f"Generated {manifest['productCount']} products, "
        f"{manifest['variantCount']} variants, and {manifest['imageCount']} images "
        f"in {args.output_dir.resolve()}"
    )


if __name__ == "__main__":
    main()
