"""Generate resumable MAI product photographs without reseeding the catalog."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import struct
import subprocess
import threading
import time
import zlib
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def image_endpoint(project_endpoint: str) -> str:
    url = urlsplit(project_endpoint)
    if (
        url.scheme != "https"
        or not url.hostname
        or not url.hostname.endswith(".services.ai.azure.com")
        or url.username
        or url.password
        or url.port
        or url.query
        or url.fragment
    ):
        raise ValueError("Expected an HTTPS Foundry services.ai.azure.com endpoint")
    return f"https://{url.hostname}/mai/v1/images/generations"


def build_prompt(product: dict[str, Any]) -> str:
    return (
        "Create one original photorealistic ecommerce product photograph. "
        f"Product description: {product['description']} "
        f"Product type: {product['productType']}. Fit/style: {product['fit']}. "
        f"Material: {product['material']}. Colour: {product['colourName']} "
        f"(reference colour {product['colourHex']}). "
        "A SINGLE camera view of ONE complete product only, fully visible, centered with generous margins "
        "on a warm light-grey seamless background. Use soft diffused studio lighting, "
        "realistic texture and construction, front-facing flat-lay or upright product "
        "presentation as appropriate. No collage, montage, split panels, extra views, "
        "detail cutouts, detached garment parts, repeated items, or multiple angles. "
        "Trousers have exactly two attached legs in a single complete garment. "
        "Footwear should be a matching pair in a single camera view. "
        "No people, mannequins, props, logos, brand names, text, labels, or watermarks. "
        "This is a fictional unbranded product, not a reproduction of any retailer's photo."
    )


def validate_png(data: bytes, width: int, height: int) -> None:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Response is not a PNG")
    offset = 8
    seen_header = False
    seen_data = False
    while offset + 12 <= len(data):
        size = struct.unpack(">I", data[offset:offset + 4])[0]
        end = offset + size + 12
        if end > len(data):
            raise ValueError("Truncated PNG")
        kind = data[offset + 4:offset + 8]
        chunk = data[offset + 8:end - 4]
        crc = struct.unpack(">I", data[end - 4:end])[0]
        if zlib.crc32(kind + chunk) & 0xFFFFFFFF != crc:
            raise ValueError("PNG checksum mismatch")
        if not seen_header:
            if kind != b"IHDR" or size != 13:
                raise ValueError("Missing PNG header")
            if struct.unpack(">II", chunk[:8]) != (width, height):
                raise ValueError("Unexpected PNG dimensions")
            seen_header = True
        seen_data = seen_data or kind == b"IDAT"
        if kind == b"IEND":
            if not seen_data or size or end != len(data):
                raise ValueError("Invalid PNG ending")
            return
        offset = end
    raise ValueError("Incomplete PNG")


def atomic_write(path: Path, data: bytes) -> None:
    if path.exists() and path.read_bytes() == data:
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    for attempt in range(6):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 5:
                raise
            print(f"File temporarily locked: {path.name}; retrying replacement", flush=True)
            time.sleep(0.25 * 2 ** attempt)


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode())


class ContentBlocked(RuntimeError):
    pass


class AzureCliToken:
    def __init__(self) -> None:
        self.command = shutil.which("az")
        if not self.command:
            raise RuntimeError("Azure CLI is required; sign in with az login before running")
        self.lock = threading.Lock()
        self.token = ""
        self.expires = 0.0

    def invalidate(self) -> None:
        with self.lock:
            self.expires = 0.0

    def get(self) -> str:
        with self.lock:
            if time.time() >= self.expires - 300:
                result = subprocess.run(
                    [self.command, "account", "get-access-token", "--resource",
                     "https://cognitiveservices.azure.com", "-o", "json"],
                    capture_output=True, text=True, timeout=60, check=False,
                )
                if result.returncode:
                    raise RuntimeError("Azure CLI token acquisition failed; check az login")
                credentials = json.loads(result.stdout)
                self.token = credentials["accessToken"]
                self.expires = float(credentials["expires_on"])
            return self.token


class MaiClient:
    def __init__(self, endpoint: str, requests_per_minute: int) -> None:
        self.endpoint = image_endpoint(endpoint)
        self.tokens = AzureCliToken()
        self.interval = 60 / requests_per_minute
        self.next_request = 0.0
        self.lock = threading.Lock()

    def generate(self, payload: dict[str, Any]) -> bytes:
        refreshed = False
        for attempt in range(5):
            token = self.tokens.get()
            with self.lock:
                time.sleep(max(0, self.next_request - time.monotonic()))
                self.next_request = time.monotonic() + self.interval
            request = Request(
                self.endpoint, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=240) as response:
                    result = json.load(response)
            except HTTPError as error:
                if error.code == 401 and not refreshed and attempt < 4:
                    self.tokens.invalidate()
                    refreshed = True
                    print("HTTP 401: reacquiring Azure CLI token and retrying once", flush=True)
                    continue
                # Do not retry ambiguous server/time-out failures that may have incurred charges.
                if error.code == 429 and attempt < 4:
                    retry_after = error.headers.get("Retry-After", "")
                    delay = max(2 ** (attempt + 2), float(retry_after) if retry_after.isdigit() else 60)
                    if delay > 300:
                        raise RuntimeError("MAI throttled for over 300 seconds; resume later") from None
                    print(f"Throttled: retrying after {delay:g}s", flush=True)
                    time.sleep(delay)
                    continue
                request_id = error.headers.get("apim-request-id", "unavailable")
                body = error.read(4096).decode("utf-8", errors="replace")
                if (
                    error.code == 499
                    and "client_connection_closed" in body
                    and "before request was sent" in body
                    and attempt < 4
                ):
                    print(f"MAI confirmed request was not sent ({request_id}); retrying", flush=True)
                    time.sleep(2 ** (attempt + 2))
                    continue
                if error.code == 400 and "content_safety_violation" in body:
                    raise ContentBlocked(f"Content safety blocked output; request ID {request_id}") from None
                raise RuntimeError(
                    f"MAI HTTP {error.code}; request ID {request_id}. "
                    f"Inspect deployment access, quota, or content filtering. Response: {body}"
                ) from None
            items = result.get("data", [])
            if len(items) != 1 or not isinstance(items[0].get("b64_json"), str):
                raise ValueError("MAI response did not contain exactly one base64 image")
            data = base64.b64decode(items[0]["b64_json"], validate=True)
            validate_png(data, payload["width"], payload["height"])
            return data
        raise RuntimeError("MAI retry limit exhausted")


def generation_spec(product: dict[str, Any], deployment: str, version: str, endpoint: str) -> dict[str, Any]:
    return {
        "endpoint": image_endpoint(endpoint),
        "modelVersion": version,
        "payload": {
            "model": deployment, "prompt": build_prompt(product),
            "width": 1024, "height": 1024,
            "auto_aspect_ratio": False, "web_grounding": False,
        },
    }


def reviewed_spec(product: dict[str, Any], deployment: str, version: str, endpoint: str) -> dict[str, Any]:
    spec = generation_spec(product, deployment, version, endpoint)
    if product["category"] in {"boots", "trainers"}:
        presentation = "One matching pair of shoes, both fully visible in a single three-quarter view."
    elif product["category"] in {"bags", "accessories"}:
        presentation = "One complete item, fully visible in a single three-quarter view."
    else:
        presentation = "One complete garment laid flat, fully visible in a single front view."
    spec["promptRevision"] = "reviewed-product-v2"
    spec["payload"]["prompt"] = (
        f"Studio product photograph. Item: {product['productType']}. "
        f"Style: {product['fit']}. Material: {product['material']}. "
        f"Colour: {product['colourName']} ({product['colourHex']}). "
        f"{presentation} Plain light-grey background, soft lighting, realistic fabric "
        "and construction. Fictional unbranded product only, without people or text."
    )
    return spec


def generate_one(root: Path, product: dict[str, Any], spec: dict[str, Any], client: MaiClient) -> dict[str, Any]:
    product_id = product["productId"]
    if not re.fullmatch(r"PROD-\d{6}", product_id):
        raise ValueError(f"Unexpected product ID: {product_id}")
    path = root / "images" / f"{product_id.lower()}.png"
    receipt_path = root / "image-generation" / f"{product_id.lower()}.json"
    blocked_path = root / "image-generation" / f"{product_id.lower()}.blocked.json"
    reviewed = spec.get("promptRevision") == "reviewed-product-v2"
    attempt_path = None
    if reviewed:
        if not blocked_path.exists():
            raise ValueError(f"{product_id}: reviewed pass requires an original block record")
        review_dir = root / "image-generation" / "reviewed-product-v2"
        review_dir.mkdir(exist_ok=True)
        blocked_path = review_dir / blocked_path.name
        attempt_path = review_dir / f"{product_id.lower()}.attempt.json"
    if blocked_path.exists():
        raise ContentBlocked(f"{product_id}: previously blocked by service; no retry")
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt["fingerprint"] != fingerprint:
            raise ValueError(f"{product_id}: generation inputs changed; use a separate catalog copy")
        data = path.read_bytes()
        validate_png(data, 1024, 1024)
        if hashlib.sha256(data).hexdigest() != receipt["sha256"]:
            raise ValueError(f"{product_id}: saved image checksum mismatch")
        return receipt
    if path.exists():
        raise ValueError(f"{product_id}: image exists without receipt; reconcile before retrying")
    if attempt_path is not None:
        if attempt_path.exists():
            raise ValueError(f"{product_id}: reviewed attempt has no result; reconcile before retrying")
        write_json(attempt_path, {
            "productId": product_id, "status": "submitted",
            "recordedAt": datetime.now(UTC).isoformat(), "spec": spec,
        })
    try:
        data = client.generate(spec["payload"])
    except ContentBlocked as error:
        write_json(blocked_path, {
            "productId": product_id, "status": "blocked", "reason": str(error),
            "recordedAt": datetime.now(UTC).isoformat(), "spec": spec,
        })
        raise
    receipt = {
        "productId": product_id, "fingerprint": fingerprint,
        "sha256": hashlib.sha256(data).hexdigest(), "imagePath": f"images/{path.name}",
        "generatedAt": datetime.now(UTC).isoformat(), "spec": spec,
    }
    atomic_write(path, data)
    write_json(receipt_path, receipt)
    return receipt


def synchronize(root: Path, products: list[dict[str, Any]], receipts: dict[str, dict[str, Any]]) -> None:
    for product in products:
        receipt = receipts.get(product["productId"])
        if receipt is None:
            continue
        previous_url = product["imageUrl"]
        new_url = previous_url.rsplit("/", 1)[0] + "/" + Path(receipt["imagePath"]).name
        product["imagePath"] = receipt["imagePath"]
        product["imageUrl"] = new_url
        for image in product["images"]:
            if image["url"] == previous_url:
                image["url"] = new_url
    atomic_write(
        root / "products.jsonl",
        "".join(json.dumps(p, ensure_ascii=True, separators=(",", ":")) + "\n" for p in products).encode(),
    )
    by_id = {p["productId"]: p for p in products}
    for path in sorted((root / "azure-search-batches").glob("batch-*.json")):
        batch = json.loads(path.read_text(encoding="utf-8"))
        for document in batch["value"]:
            document["imageUrl"] = by_id[document["productId"]]["imageUrl"]
        write_json(path, batch)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["photographicImageCount"] = sum(p["imagePath"].endswith(".png") for p in products)
    manifest["blockedImageCount"] = sum(
        not p["imagePath"].endswith(".png")
        and (root / "image-generation" / f"{p['productId'].lower()}.blocked.json").exists()
        for p in products
    )
    manifest["files"]["imageGeneration"] = "image-generation/"
    write_json(manifest_path, manifest)


def run(args: argparse.Namespace) -> None:
    root = args.catalog_dir
    if not 1 <= args.workers <= 8 or not 1 <= args.requests_per_minute <= 60 or args.limit < 1:
        raise ValueError("Use 1-8 workers, 1-60 requests per minute, and a positive limit")
    products = [json.loads(line) for line in (root / "products.jsonl").read_text(encoding="utf-8").splitlines()]
    if len({p["productId"] for p in products}) != len(products):
        raise ValueError("Duplicate product IDs")
    client = MaiClient(args.project_endpoint, args.requests_per_minute)
    (root / "image-generation").mkdir(exist_ok=True)
    # Exclusive creation prevents concurrent runs from racing on catalog checkpoints.
    lock = root / "image-generation" / "run.lock"
    with lock.open("x", encoding="utf-8") as handle:
        handle.write(datetime.now(UTC).isoformat())
    receipts: dict[str, dict[str, Any]] = {}
    blocked = 0
    try:
        candidates = products
        if args.reviewed_missing:
            candidates = [
                p for p in products
                if (root / "image-generation" / f"{p['productId'].lower()}.blocked.json").exists()
            ]
        selected = iter(candidates[:args.limit])
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            pending = {}

            def submit_next() -> None:
                product = next(selected, None)
                if product is not None:
                    builder = reviewed_spec if args.reviewed_missing else generation_spec
                    spec = builder(product, args.deployment, args.model_version, args.project_endpoint)
                    pending[executor.submit(generate_one, root, product, spec, client)] = product["productId"]

            for _ in range(args.workers):
                submit_next()
            failed = False
            while pending:
                completed, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in completed:
                    product_id = pending.pop(future)
                    try:
                        receipts[product_id] = future.result()
                    except ContentBlocked as error:
                        blocked += 1
                        print(f"BLOCKED {product_id}: {error}; retaining existing image", flush=True)
                        synchronize(root, products, receipts)
                    except (RuntimeError, ValueError, OSError, KeyError) as error:
                        print(f"FAILED {product_id}: {error}", flush=True)
                        failed = True
                    else:
                        synchronize(root, products, receipts)
                        print(f"Ready {len(receipts)}/{min(args.limit, len(candidates))}: {product_id}", flush=True)
                if not failed:
                    for _ in completed:
                        submit_next()
            if failed:
                raise RuntimeError("Generation stopped after failure; successful images are checkpointed")
        print(
            f"Finished: {len(receipts)} validated images, {blocked} content-blocked products "
            "requiring review; catalog references synchronized.", flush=True,
        )
    finally:
        lock.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-dir", type=Path, default=Path("data") / "catalog")
    parser.add_argument("--project-endpoint", required=True)
    parser.add_argument("--deployment", default="MAI-Image-2.6")
    parser.add_argument("--model-version", required=True, help="Version verified on the existing deployment")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--requests-per-minute", type=int, default=6)
    parser.add_argument(
        "--reviewed-missing", action="store_true",
        help="Explicit one-time reviewed-product-v2 pass over original blocked products; keeps block history",
    )
    run(parser.parse_args())
