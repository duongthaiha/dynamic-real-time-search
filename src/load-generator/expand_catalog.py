"""Create a separate, resumable fashion catalogue. This command makes no cloud calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from generate_catalog import (
    BRANDS,
    COLOURS,
    DEFAULT_SEED,
    PRODUCT_TYPES,
    ProductType,
    build_product,
    make_variants,
)
from generate_images import validate_png, write_json

MAX_PRODUCTS = 2_000_000
VERSION = "synthetic-fashion-v2"
PROMPT_VERSION = "adult-fashion-v1"
FIDELITY_PROMPT_VERSION = "product-focused-v3"
APPAREL = {"jeans", "trousers", "jackets", "coats", "shirts", "t-shirts", "knitwear",
           "hoodies", "dresses", "skirts", "shorts"}
SKIN_TONES = ("deep brown", "dark brown", "medium brown", "olive", "light brown", "fair")
BODY_TYPES = ("slender", "athletic", "mid-size", "plus-size", "broad-build")
PRESENTATIONS = ("woman", "man", "non-binary adult with androgynous presentation")


def accessory(category: str, name: str, fits: tuple[str, ...],
              materials: tuple[str, ...], sizes: tuple[str, ...] = ("One Size",)) -> ProductType:
    return ProductType(category, name, "unisex", sizes, fits, materials, (12, 95), "accessory")


TYPES = PRODUCT_TYPES[:-1] + (
    accessory("caps", "cap", ("baseball", "five-panel", "soft-crown"),
              ("cotton twill", "recycled polyester", "cotton canvas")),
    accessory("hats", "hat", ("bucket", "wide-brim", "cloche"),
              ("cotton twill", "woven paper fibre", "cotton canvas")),
    accessory("beanies", "beanie", ("ribbed", "cuffed", "slouchy"),
              ("cotton knit", "wool blend", "recycled yarn")),
    accessory("scarves", "scarf", ("long", "square", "wrap"),
              ("cotton voile", "wool blend", "viscose")),
    accessory("belts", "belt", ("narrow", "standard-width", "wide"),
              ("faux leather", "woven cotton", "recycled polyester"), ("S", "M", "L", "XL")),
    accessory("gloves", "gloves", ("fitted", "regular", "relaxed"),
              ("cotton knit", "wool blend", "recycled yarn"), ("S", "M", "L")),
    accessory("socks", "socks", ("ankle", "crew", "knee-high"),
              ("cotton blend", "wool blend", "recycled yarn"), ("UK 3-5", "UK 6-8", "UK 9-12")),
    accessory("sunglasses", "sunglasses", ("round-frame", "square-frame", "cat-eye"),
              ("recycled acetate", "bio-based acetate", "recycled plastic")),
    accessory("necklaces", "necklace", ("short", "mid-length", "long"),
              ("coloured glass beads", "coloured resin beads", "painted wooden beads")),
    accessory("bracelets", "bracelet", ("single-strand", "double-strand", "wide"),
              ("coloured glass beads", "coloured resin beads", "painted wooden beads")),
    accessory("earrings", "earrings", ("stud", "drop", "hoop"),
              ("coloured resin", "enamelled metal", "coloured glass")),
    accessory("wallets", "wallet", ("bifold", "trifold", "card-holder"),
              ("faux leather", "cotton canvas", "recycled polyester")),
    accessory("pouches", "pouch", ("flat", "boxy", "rounded"),
              ("cotton canvas", "faux leather", "recycled polyester")),
)


def design_options(kind: ProductType) -> tuple[tuple[str, ...], ...]:
    if kind.category in {"necklaces", "bracelets", "earrings", "sunglasses"}:
        patterns = ("solid colour", "marbled", "speckled", "two-tone")
        details = ("polished finish", "matte finish", "satin finish",
                   "translucent accents", "geometric accents", "rounded accents")
        accents = ("black accents", "cream accents", "silver-tone accents")
    else:
        patterns = ("solid colour", "fine stripe", "wide stripe", "small check",
                    "large check", "abstract print", "micro-dot", "colour-block")
        details = ("tonal stitching", "contrast stitching", "reinforced seams",
                   "decorative topstitching", "bound edges", "minimal seams")
        accents = ("black accents", "cream accents", "navy accents")
    return (BRANDS, tuple(c[1] for c in COLOURS), kind.fits, kind.materials,
            patterns, details, accents)


def capacity() -> int:
    # Round-robin allocation must fit even the smallest category's design space.
    return min(math.prod(map(len, design_options(kind))) for kind in TYPES) * len(TYPES)


def decode_design(rank: int, options: tuple[tuple[str, ...], ...]) -> list[str]:
    values = []
    for domain in options:
        rank, position = divmod(rank, len(domain))
        values.append(domain[position])
    if rank:
        raise ValueError("Requested catalogue exceeds the distinct fashion design space")
    return values


def fashion_product(index: int, ordinal: int, seed: int, image_base_url: str) -> tuple[dict[str, Any], str]:
    kind = TYPES[ordinal % len(TYPES)]
    rank = ordinal // len(TYPES)
    options = design_options(kind)
    total = math.prod(map(len, options))
    if rank >= total:
        raise ValueError("Requested catalogue exceeds category capacity")
    # A coprime permutation keeps designs distinct while varying adjacent products.
    multiplier = 104729
    if math.gcd(multiplier, total) != 1:
        raise ValueError("Design permutation is incompatible with taxonomy capacity")
    design = decode_design((rank * multiplier + seed) % total, options)
    brand, colour_name, fit, material, pattern, detail, accent = design
    colour, _, colour_hex = next(c for c in COLOURS if c[1] == colour_name)
    rng = random.Random(f"{VERSION}:{seed}:{index}")
    product, _, _ = build_product(index, rng, image_base_url, product_type=kind)
    product.update(
        catalogVersion=VERSION, brand=brand, colour=colour, colourName=colour_name,
        colourHex=colour_hex, fit=fit, material=material, pattern=pattern,
        designDetail=detail, accent=accent,
        title=f"{brand} {fit} {kind.name} in {colour_name.lower()} - {pattern}, {detail}, {accent}",
        description=f"A {fit} {kind.name} made from {material}, in {colour_name.lower()} "
                    f"with a {pattern} design, {detail} and {accent}. "
                    "Original fictional fashion merchandise.",
        careInstructions="Follow the material-specific care instructions supplied with this item.",
        imagePath=f"images/prod-{index:06d}.png",
        imageUrl=f"{image_base_url.rstrip('/')}/prod-{index:06d}.png",
    )
    product["tags"] = sorted({colour, kind.category, fit, material, pattern, detail, accent, kind.audience})
    product["variants"] = make_variants(rng, product["productId"], kind, colour_name, product["price"])
    product["images"] = [{"url": product["imageUrl"], "alt": product["title"], "position": 1}]
    product["photography"] = {
        "revision": PROMPT_VERSION,
        "presentation": "product-only" if kind.category in {"wallets", "pouches"} else "modelled",
        "adultModel": PRESENTATIONS[rank % len(PRESENTATIONS)],
        "skinTone": SKIN_TONES[(rank // len(PRESENTATIONS)) % len(SKIN_TONES)],
        "bodyType": BODY_TYPES[(rank // (len(PRESENTATIONS) * len(SKIN_TONES))) % len(BODY_TYPES)],
    }
    signature = hashlib.sha256(json.dumps([kind.category, *design]).encode()).hexdigest()
    return product, signature


PATTERN_INSTRUCTIONS = {
    "solid colour": "The main product surface is solid, without stripes, checks, dots or printed graphics.",
    "fine stripe": "Show repeated, clearly visible thin parallel stripes printed or woven into the product surface.",
    "wide stripe": (
        "Show bold, broad, repeated parallel bands across the main visible product surface. "
        "The stripes must be an obvious fabric pattern, not just seams, creases, shadows, "
        "piping or one contrasting side panel."
    ),
    "small check": "Show a repeated small-scale square check pattern, not stripes or stitching.",
    "large check": "Show an unmistakable repeated large-scale square check pattern, not stripes.",
    "abstract print": "Show a clearly visible repeating nonrepresentational abstract print, with no text or logos.",
    "micro-dot": "Show a visible, regular field of small dots on the main product surface.",
    "colour-block": "Show clearly separated large adjacent blocks of colour, not a plain single-colour item.",
    "marbled": "Show visible irregular marbled colour veining in the advertised item's material.",
    "speckled": "Show clearly visible small irregular colour speckles in the advertised item's material.",
    "two-tone": "Show two visibly distinct colour regions on the advertised item, using the specified palette.",
}


def build_fashion_prompt(
    product: dict[str, Any], *, prompt_revision: str = FIDELITY_PROMPT_VERSION,
) -> str:
    photo = product["photography"]
    if photo["revision"] != PROMPT_VERSION:
        raise ValueError("Unsupported photography policy")
    if prompt_revision not in {PROMPT_VERSION, "product-fidelity-v2", FIDELITY_PROMPT_VERSION}:
        raise ValueError("Unsupported image prompt revision")
    if prompt_revision == FIDELITY_PROMPT_VERSION:
        pattern = product["pattern"]
        if pattern not in PATTERN_INSTRUCTIONS:
            raise ValueError(f"No fidelity instructions for product pattern: {pattern}")
        if photo["presentation"] == "product-only":
            presentation = "One complete item on a plain studio surface. No people."
        else:
            presentation = (
                f"A fictional adult {photo['adultModel']}, age 25 or older, "
                f"with {photo['skinTone']} skin and a {photo['bodyType']} build, "
                "wearing a complete everyday outfit and naturally displaying the advertised item. "
                "Use a neutral standing pose and plain coordinating garments. "
            )
            if product["category"] in APPAREL:
                presentation += "Show the entire advertised garment, including its hem, with a clear front view."
            elif product["category"] in {"trainers", "boots", "socks", "gloves"}:
                presentation += "Frame the complete matching pair together as worn, with both items visible."
            elif product["category"] == "bags":
                presentation += "Show the complete bag carried beside the outfit, with its shape and straps visible."
            else:
                presentation += "Use an accessory-focused view showing the complete item as worn."
        return (
            "Create exactly ONE primary ecommerce photograph of the advertised product. "
            f"Item: {product['productType']}. Fit: {product['fit']}. "
            f"Material: {product['material']}. Main colour: {product['colourName']} "
            f"({product['colourHex']}); secondary palette: {product['accent']}. "
            f"REQUIRED VISIBLE PATTERN: {pattern}. {PATTERN_INSTRUCTIONS[pattern]} "
            f"Construction or finish: {product['designDetail']}. "
            "Keep these product details accurate and easy to inspect; distinguish surface patterns "
            "from seams and folds. "
            f"{presentation} "
            "Keep the item unobstructed and in focus. Soft neutral studio lighting, "
            "light-grey seamless background, realistic proportions and material texture. "
            "One camera view; plain unbranded merchandise, without text, logos or watermarks."
        )
    if photo["presentation"] == "product-only":
        presentation = "One complete product alone in a single three-quarter camera view. No people."
    else:
        presentation = (
            f"One fictional adult {photo['adultModel']}, age 25 or older, "
            f"with {photo['skinTone']} skin and a {photo['bodyType']} body type, "
            "naturally wearing or carrying the advertised item. "
            "Use a respectful, non-sexual commercial fashion pose. "
            "Frame the advertised item completely and prominently; incidental plain clothing "
            "must not obscure it. For footwear, socks or gloves show the complete matching pair. "
            "For trousers show the complete garment with two attached legs. "
            "For small accessories use a close fashion view that clearly shows the item."
        )
    legacy = (
        "Create one original photorealistic ecommerce fashion photograph. "
        f"Advertised item: {product['productType']}. {product['description']} "
        f"Main colour: {product['colourName']} ({product['colourHex']}). "
        f"{presentation} Soft studio lighting, realistic materials and construction, "
        "warm light-grey seamless background. One camera view, no collage, extra views, "
        "duplicate items, detached garment parts, text, logo, watermark or retailer imitation. "
        "Do not depict any real person. This is synthetic unbranded merchandise."
    )
    if prompt_revision == PROMPT_VERSION:
        return legacy
    pattern = product["pattern"]
    if pattern not in PATTERN_INSTRUCTIONS:
        raise ValueError(f"No fidelity instructions for product pattern: {pattern}")
    return (
        "Generate exactly ONE primary ecommerce photograph for exactly ONE advertised product. "
        "Product accuracy has priority over fashion styling or artistic interpretation. "
        f"ADVERTISED PRODUCT: {product['productType']}. "
        f"FIT/SILHOUETTE: {product['fit']}. MATERIAL: {product['material']}. "
        f"MAIN COLOUR: {product['colourName']} ({product['colourHex']}). "
        f"SECONDARY PALETTE: {product['accent']}. "
        f"REQUIRED VISIBLE PATTERN: {pattern}. {PATTERN_INSTRUCTIONS[pattern]} "
        "Use the main colour predominantly and the secondary palette for contrasting "
        "pattern elements or accents; do not silently replace the requested pattern with plain fabric. "
        f"CONSTRUCTION/FINISH: {product['designDetail']}. "
        "Render the specified material texture, fit and construction faithfully. "
        "Real construction seams must remain distinct from the decorative surface pattern. "
        "Do not add unrelated prints, pockets, panels, fastenings or ornamentation. "
        f"{presentation} "
        "Choose a pose and camera distance that keep the complete advertised item visible "
        "and make its pattern, material and finish easy to inspect. "
        "Do not hide identifying details behind hands, hair, folds or other clothing. "
        "Any incidental outfit pieces must be plain, neutral and visually subordinate. "
        "Soft neutral studio lighting must preserve the specified colours; use a warm "
        "light-grey seamless background. Realistic anatomy and garment construction. "
        "One camera view only, no collage, extra angles, duplicate products or alternative designs. "
        "No logo, text, watermark, retailer imitation or real person. Fictional adult models only. "
        "Before producing the image, ensure the advertised item's visible pattern, palette, "
        "material and silhouette all match these facts; do not substitute a simpler design."
    )


def connect(root: Path) -> sqlite3.Connection:
    db = sqlite3.connect(root / "catalog.sqlite", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS products (
            ordinal INTEGER PRIMARY KEY, product_id TEXT NOT NULL UNIQUE,
            design_key TEXT UNIQUE, payload TEXT NOT NULL, original INTEGER NOT NULL,
            state TEXT NOT NULL, local_path TEXT, sha256 TEXT UNIQUE,
            spec TEXT, fingerprint TEXT, error TEXT, blob_name TEXT,
            image_bytes INTEGER, md5 TEXT, verified_at TEXT
        );
        CREATE INDEX IF NOT EXISTS products_state ON products(state, ordinal);
        CREATE TABLE IF NOT EXISTS skus (sku TEXT PRIMARY KEY, variant_id TEXT NOT NULL UNIQUE,
            product_ordinal INTEGER NOT NULL
            REFERENCES products(ordinal));
        CREATE TABLE IF NOT EXISTS colourways (id TEXT PRIMARY KEY, product_ordinal INTEGER NOT NULL
            REFERENCES products(ordinal));
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY, product_id TEXT NOT NULL, budget TEXT NOT NULL,
            recorded_at TEXT NOT NULL, outcome TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS budgets (
            name TEXT PRIMARY KEY, limit_calls INTEGER NOT NULL, used_calls INTEGER NOT NULL DEFAULT 0
        );
    """)
    return db


@contextmanager
def run_lock(root: Path) -> Iterator[None]:
    path = root / "run.lock"
    with path.open("x", encoding="ascii") as handle:
        handle.write("Exclusive catalogue operation. Verify the previous process stopped before removal.\n")
    try:
        yield
    finally:
        path.unlink()


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_source_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"Missing or unsafe source asset: {relative}")
    return path


def copy_verified(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        temporary = destination.with_suffix(destination.suffix + ".copying")
        shutil.copyfile(source, temporary)
        temporary.replace(destination)
    if file_hash(source) != file_hash(destination):
        raise ValueError(f"Copied source differs: {destination.name}")


def source_inventory(source: Path) -> dict[str, str]:
    if (source / "image-generation" / "run.lock").exists():
        raise ValueError("Source image generation is running or needs lock reconciliation")
    inventory = {}
    for name in ("products.jsonl", "manifest.json", "image-prompts.jsonl"):
        path = source / name
        if path.exists():
            inventory[name] = file_hash(path)
    for name in ("images", "image-generation", "azure-search-batches"):
        for path in sorted((source / name).rglob("*")):
            if path.is_file():
                inventory[path.relative_to(source).as_posix()] = file_hash(path)
    if "products.jsonl" not in inventory:
        raise ValueError("Source products.jsonl is required")
    return inventory


def add_product(db: sqlite3.Connection, ordinal: int, product: dict[str, Any],
                signature: str | None, original: bool, local_path: str | None = None,
                sha256: str | None = None) -> None:
    db.execute(
        "INSERT INTO products(ordinal,product_id,design_key,payload,original,state,local_path,sha256) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (ordinal, product["productId"], signature, json.dumps(product, ensure_ascii=True,
         separators=(",", ":")), int(original), "staged" if original else "pending", local_path, sha256),
    )
    for variant in product["variants"]:
        db.execute("INSERT INTO skus VALUES(?,?,?)", (variant["sku"], variant["variantId"], ordinal))
    db.execute("INSERT INTO colourways VALUES(?,?)", (product["colourWayId"], ordinal))


def summary(db: sqlite3.Connection) -> dict[str, Any]:
    counts = dict(db.execute("SELECT state,COUNT(*) FROM products GROUP BY state").fetchall())
    return {
        "catalogVersion": VERSION, "productCount": sum(counts.values()),
        "variantCount": db.execute("SELECT COUNT(*) FROM skus").fetchone()[0],
        "states": counts, "imageStorage": "remote-backed; only originals and staging are local",
        "ready": bool(counts) and set(counts) == {"verified"},
    }


def expand(source: Path, root: Path, target: int, seed: int = DEFAULT_SEED,
           image_base_url: str = "https://cdn.example.com/synthetic-products") -> dict[str, Any]:
    source, root = source.resolve(), root.resolve()
    if source == root or root.is_relative_to(source) or source.is_relative_to(root):
        raise ValueError("Source and output must be separate non-overlapping directories")
    if not 1 <= target <= MAX_PRODUCTS or target > capacity():
        raise ValueError("Target must fit the distinct design space and range 1..2,000,000")
    if root.exists() and any(root.iterdir()) and not (root / "catalog.sqlite").exists():
        raise ValueError("Output is not an empty expansion directory")
    root.mkdir(parents=True, exist_ok=True)
    with run_lock(root):
        inventory = source_inventory(source)
        config = {"version": VERSION, "source": str(source), "inventory": inventory, "target": target,
                  "seed": seed, "imageBaseUrl": image_base_url}
        encoded = json.dumps(config, sort_keys=True)
        db = connect(root)
        try:
            previous = db.execute("SELECT value FROM settings WHERE key='expansion'").fetchone()
            if previous and previous[0] != encoded:
                raise ValueError("Expansion inputs changed; use a separate output directory")
            with db:
                db.execute("INSERT OR IGNORE INTO settings VALUES('expansion',?)", (encoded,))
            for name in inventory:
                copy_verified(source / name, root / "original" / name)
                if file_hash(root / "original" / name) != inventory[name]:
                    raise ValueError("Source changed while copying; expansion cannot continue")
            completed = db.execute("SELECT COALESCE(MAX(ordinal),0) FROM products").fetchone()[0]
            original_count = 0
            with (source / "products.jsonl").open(encoding="utf-8") as stream, db:
                for original_count, line in enumerate(stream, 1):
                    product = json.loads(line)
                    if product["productId"] != f"PROD-{original_count:06d}":
                        raise ValueError("Source must have contiguous canonical product IDs in order")
                    path = safe_source_path(source, product["imagePath"])
                    data = path.read_bytes()
                    validate_png(data, 1024, 1024)
                    digest = hashlib.sha256(data).hexdigest()
                    receipt = json.loads((source / "image-generation" /
                                         f"{product['productId'].lower()}.json").read_text())
                    if receipt["productId"] != product["productId"] or receipt["sha256"] != digest:
                        raise ValueError("Source receipt/image integrity mismatch")
                    if original_count > completed:
                        add_product(db, original_count, product, None, True,
                                    "original/" + product["imagePath"], digest)
            if not original_count or target < original_count:
                raise ValueError("Target must include every original product")
            progress = summary(db)
            for start in range(max(completed, original_count) + 1, target + 1, 1000):
                added_variants = 0
                added_products = 0
                with db:
                    for index in range(start, min(start + 1000, target + 1)):
                        product, signature = fashion_product(index, index - original_count - 1,
                                                             seed, image_base_url)
                        add_product(db, index, product, signature, False)
                        added_variants += len(product["variants"])
                        added_products += 1
                progress["productCount"] += added_products
                progress["variantCount"] += added_variants
                progress["states"]["pending"] = progress["states"].get("pending", 0) + added_products
                progress["ready"] = False
                write_json(root / "manifest.json", progress)
            result = summary(db)
            write_json(root / "manifest.json", result)
            return result
        finally:
            db.close()


def export(root: Path, output: Path, *, metadata_only: bool = False) -> dict[str, Any]:
    if output.resolve().is_relative_to((root / "original").resolve()):
        raise ValueError("Export must not overwrite preserved originals")
    with run_lock(root):
        db = connect(root)
        try:
            result = summary(db)
            config = json.loads(db.execute("SELECT value FROM settings WHERE key='expansion'").fetchone()[0])
            if result["productCount"] != config["target"]:
                raise ValueError("Expansion is incomplete")
            if not metadata_only and not result["ready"]:
                raise ValueError("Every image must be verified before publication export")
            output.mkdir(parents=True, exist_ok=True)
            target = output / "products.jsonl"
            temporary = output / "products.jsonl.tmp"
            prompt_temporary = output / "image-prompts.jsonl.tmp"
            digest = hashlib.sha256()
            prompt_digest = hashlib.sha256()
            prompt_count = 0
            with temporary.open("wb") as stream, prompt_temporary.open("wb") as prompts:
                for row in db.execute("SELECT payload,original,spec FROM products ORDER BY ordinal"):
                    line = (row[0] + "\n").encode()
                    digest.update(line)
                    stream.write(line)
                    if not row[1]:
                        product = json.loads(row[0])
                        recorded_spec = json.loads(row[2]) if row[2] else None
                        prompt = {
                            "productId": product["productId"], "targetFile": product["imagePath"],
                            "promptRevision": (
                                recorded_spec["promptRevision"] if recorded_spec else FIDELITY_PROMPT_VERSION
                            ),
                            "prompt": (
                                recorded_spec["payload"]["prompt"] if recorded_spec
                                else build_fashion_prompt(product)
                            ),
                        }
                        encoded_prompt = (json.dumps(prompt, ensure_ascii=True) + "\n").encode()
                        prompts.write(encoded_prompt)
                        prompt_digest.update(encoded_prompt)
                        prompt_count += 1
            temporary.replace(target)
            prompt_temporary.replace(output / "image-prompts.jsonl")
            result.update(contentSha256=digest.hexdigest(), metadataOnly=metadata_only,
                          promptCount=prompt_count, promptsSha256=prompt_digest.hexdigest())
            destination = db.execute("SELECT value FROM settings WHERE key='destination'").fetchone()
            result["imageDestination"] = destination[0] if destination else None
            write_json(output / "manifest.json", result)
            return result
        finally:
            db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data") / "catalog")
    parser.add_argument("--output-dir", type=Path, default=Path("data") / "catalog-expanded")
    parser.add_argument("--target-count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--export", type=Path)
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()
    try:
        result = (export(args.output_dir, args.export, metadata_only=args.metadata_only)
                  if args.export else expand(args.source, args.output_dir, args.target_count, args.seed))
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, sqlite3.Error, KeyError) as error:
        parser.exit(1, f"Catalogue expansion failed: {error}\n")


if __name__ == "__main__":
    main()
