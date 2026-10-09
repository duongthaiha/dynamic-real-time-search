# Synthetic product catalog

The catalog generator creates original, deterministic fashion-retail sample
data for the search and trend-ranking POC. Its structure is informed by common
product-detail patterns such as a parent product, colourway, price, gallery,
fit/material details, and purchasable size variants. It does not copy product
descriptions, images, identifiers, or brand data from ASOS.

## Generated assets

For a separate, research-informed set of 1,000 synthetic shopper queries,
see the [fashion search query dataset](research/fashion-search-query-dataset.md).
It covers the existing catalog's categories without changing products or images.

Running the default command produces exactly 1,000 products:

```powershell
python src\load-generator\generate_catalog.py
```

Output is written under `data\catalog\`:

| Path | Purpose |
|---|---|
| `src\load-generator\azure-search-index.json` | Azure AI Search index definition and opt-in trend scoring profile |
| `manifest.json` | Seed, version, counts, and generation settings |
| `products.jsonl` | Complete parent products and their size/SKU variants |
| `images\prod-*.svg` | Original deterministic catalog illustrations |
| `images\prod-*.png` | Successful MAI-generated photographs, when the image workflow has run |
| `image-generation\prod-*.json` | Successful generation receipts and `.blocked.json` service-block records |
| `image-prompts.jsonl` | Optional prompts for replacing SVGs with generated photographs |
| `azure-search-batches\batch-*.json` | Azure AI Search indexing request bodies, 100 documents per batch |

Generation is reproducible. The defaults use seed `20260924`, catalog version
`synthetic-fashion-v1`, GBP prices, and a fixed timestamp so repeated runs
produce byte-identical data. Override the count, seed, image URL, or index
batch size when needed:

```powershell
python src\load-generator\generate_catalog.py `
  --count 1000 `
  --seed 20260924 `
  --image-base-url https://your-cdn.example.com/products `
  --batch-size 100
```

`imageUrl` is intentionally based on a configurable public URL while
`imagePath` points to the local generated SVG. Upload `data\catalog\images\`
to the configured static host before displaying search results.

## Product shape

For the approved Cosmos keyword POC, use the separate
[Cosmos catalogue importer](../src/search-api/README.md#catalogue-export-and-import)
against the existing products JSONL. It exports parent-plus-variant documents
with integer minor-unit prices and an English full-text index policy. It does
not regenerate products, rewrite Search batches, alter images or invoke image
generation. The legacy Azure AI Search workflow below is not used by this POC.
The active image-hosted snapshot uses `--image-container product-images` to
store relative blob paths in Cosmos. Storage origin selection happens through
the API's `CATALOG_IMAGE_BASE_URL`, so changing the dev/test/prod storage account
does not rewrite product documents. The source catalogue itself retains its
original image references and generation state.

Each product contains:

- stable `productId` and `colourWayId`;
- synthetic title, description, brand, department, category, and product type;
- normalized colour plus display name and hex value;
- fit, material, care, tags, price, and currency;
- searchable and stock eligibility flags;
- local and hosted image references with accessible alt text;
- variants with stable SKU, size, price, stock quantity, and availability; and
- initialized trend fields required by the hybrid design.

The index batches flatten the parent record to fields useful to Azure AI
Search. `availableSizes` and `variantSkus` are collections, while the complete
variant inventory remains in `products.jsonl`. `trendStateVersion` is emitted
as a fixed-width sortable string to avoid signed integer compatibility issues.

Create the `products` index from
`src\load-generator\azure-search-index.json`, then submit each generated batch
to the index documents endpoint using a supported stable Azure AI Search API
version. Authenticate with Microsoft Entra ID where possible and do not put an
admin key in this repository. The `trend-magnitude` scoring profile is opt-in,
so baseline queries cannot apply trend boosting accidentally.

The index definition follows Azure AI Search field constraints: collections
are not marked sortable, and the scoring function targets the filterable
numeric `trendingScore` field. See the official documentation for
[creating an index](https://learn.microsoft.com/azure/search/search-how-to-create-search-index)
and [scoring profiles](https://learn.microsoft.com/azure/search/index-add-scoring-profiles).

The generated batch bodies use `@search.action: upload` because they seed full
documents. Subsequent trend-only publication must use `merge`, as required by
the architecture.

## MAI-Image-2.6 photographs

The SVGs remain as original offline illustrations and backups. The separate
[image generator](../src/load-generator/generate_images.py) uses an **existing**
MAI-Image-2.6 deployment to create 1024 x 1024 PNG product photographs. It builds
prompts directly from each current product's description, type, fit, material,
and colour. It requests a single product view without people, logos or text.
It does not consume the older optional `image-prompts.jsonl` (whose WebP target
names are suggestions, not the MAI output format).

Python 3.11+ and a signed-in Azure CLI with inference access are required. No
additional Python packages, stored keys, resource provisioning, or role
assignment changes are needed. Generation consumes billable model quota.

```powershell
python src\load-generator\generate_images.py `
  --project-endpoint https://foundry-eastus-hd.services.ai.azure.com/api/projects/firework-default `
  --deployment MAI-Image-2.6 `
  --model-version 2026-07-31 `
  --limit 1000 `
  --workers 4 `
  --requests-per-minute 6
```

Use `--limit 1 --workers 1` for a sample before the full run. `--limit` selects
the first N catalog products, including already completed images. Rerunning the
same command resumes validated results without charging for them again. Do not
run two copies concurrently. A lock prevents simultaneous catalog writes; after
a hard process termination, verify the old process has stopped before manually
removing `data\catalog\image-generation\run.lock`.

The project URL is normalized to the resource-level
`/mai/v1/images/generations` endpoint. Entra tokens are obtained from Azure CLI,
kept in memory, and refreshed before expiry. Model web grounding is disabled;
no retailer images are downloaded or sent. The model version flag records the
version verified on the deployment; it does not pin or change that deployment.
Do not change deployment versions during a run.

Each successful image has a corresponding receipt under `image-generation\`
with the prompt, deployment/version, timestamp, input fingerprint and image
SHA-256. PNG dimensions and chunk checksums are checked before publication.
The generator updates `imagePath`, `imageUrl`, matching gallery URLs, all local
Search batch image references, and `manifest.json`'s `photographicImageCount`.
Other product fields, inventory and Search trend scores are preserved. Files
are replaced atomically one at a time; rerunning repairs interrupted reference
synchronization. Unchanged files are not rewritten. Transient Windows file
locks use bounded replacement retries (six attempts) without another model
call. Receipts with changed inputs, missing images or corrupted
images fail explicitly rather than silently consuming more quota.

The deployment reported a limit of **6 requests per 60 seconds** on
24 September 2026. At that rate, 1,000 images require at least about 2 hours
47 minutes, plus inference time and throttling. HTTP 429 is automatically
retried, at most four times per request. HTTP 401 triggers one token
reacquisition and retry, within the same five-attempt cap. Content-safety blocks
and confirmed pre-send connection failures are handled separately: HTTP 499 is
retried within that cap only when the service explicitly reports
`client_connection_closed` **before request was sent**. Content-safety blocks
are recorded as `image-generation\prod-*.blocked.json`, retain the existing SVG,
and are skipped without another API call on resume. The final summary and
`manifest.json`'s `blockedImageCount` explicitly identify these incomplete
replacements. They need manual review; the pipeline does not bypass filters.
Persistent auth, server and
ambiguous timeout failures stop new submissions; in-flight requests finish and
successful results are checkpointed. Check the error before resuming, because
an uncertain request might have incurred a charge without returning an image.
Model/content filters are not bypassed.

Do not rerun `generate_catalog.py` against a catalog with image-generation
state: it now rejects that operation to protect paid images and their
references. Use a different `--output-dir` for a new seed.

Generated images are nondeterministic and should be disclosed as AI-generated.
Automated file validation is not visual quality approval: review images before
publishing. The script does **not** upload to a CDN or mutate an Azure Search
index. Hosted URLs still use the configured placeholder base until you publish
the PNGs to a real host and update that base in the catalog and indexing data.

API and authentication reference:
[Use MAI image models in Foundry](https://learn.microsoft.com/azure/foundry/foundry-models/how-to/use-foundry-models-mai-image).

### Completed catalog run

The original MAI-Image-2.6 (`2026-07-31`) run produced 856 photographs and
144 service content-safety blocks. The reviewed pass completed on
25 September 2026 and successfully generated all 144 missing photographs:

- **1,000** validated 1024 x 1024 PNGs (about 1,043 MiB total).
- **0** missing photographs and **0** new safety blocks in the reviewed pass.
- **0** unattempted products; no background image worker remains.
- All 1,000 product records and Search documents have matching image references.
- All original 1,000 SVGs are retained as backups.
- The original 856 photographs and 1,000 receipt/block records are unchanged,
  verified against pre-pass SHA-256 snapshots.
- Product descriptions, variants and all non-image fields are unchanged.

Counts are recorded in [the catalog manifest](../data/catalog/manifest.json).
Per-product failure reasons and request IDs are in
[the generation receipts](../data/catalog/image-generation/).
Historical block records remain for provenance; they do not represent missing
images in the completed catalog. Each replacement has its own success receipt.

### Reviewed missing-image pass

After reviewing the benign product requests, the user authorized a single new
attempt with shorter category-specific prompts. Add `--reviewed-missing` to
the image command above to run this fixed `reviewed-product-v2` revision.
It selects only products with an original block record, leaving the original
successful photographs untouched. `--limit 3 --workers 1` selects three of
these products for a sample; rerun with `--limit 1000` for the full selection.

The revised prompt uses product type, fit, material and colour, with footwear,
accessory or flat-lay garment presentation as appropriate. Catalog descriptions
are not changed. All service safety checks remain enabled. This is not a
prompt-search loop or a guarantee of acceptance.

Original block records are retained unchanged. New attempt and block records
are stored under `image-generation\reviewed-product-v2\`. A new safety block
is not retried on resume; an attempt with no known result requires manual
reconciliation. Successful results retain their exact prompt revision and
fingerprint in the usual product receipt. Use the same `--reviewed-missing`
command to resume this pass, rather than the original prompt command.
`blockedImageCount` counts unresolved products, excluding those with a
successful replacement even though their historical block record is retained.

## Validation

Run the unittest suite after installing the catalogue environment described below:

```powershell
.\.venv-catalog\Scripts\python.exe -m unittest discover -s src\load-generator -p "test_*.py"
```

The tests verify deterministic catalog output, product and image counts, unique
product IDs, variants, stock and trend initialization, index schema/batches,
PNG validation, resume and input-change checks, bounded throttling retries,
failure handling, protection against reseeding, and image-reference updates
without changes to product data or existing Search trend scores. The reviewed
pass also has tests for category-specific prompts, preserving original block
history, resumability, and refusing duplicate submissions after a new block
or uncertain outcome.

## Large catalogue expansion

**Current authorized image target: 10,000 total products.** The two-million-row
metadata dataset remains offline scale evidence, not the active paid-image run.
The active run is `data\catalog-expanded-10000\`, containing 43,155 variants,
the original 1,000 photographs and the preserved `PROD-001001` calibration.
The user authorized at most 8,999 additional model HTTP attempts, including
retries, at 6 RPM. Existing originals have been uploaded and verified with a
zero-inference allowance. Cosmos publication and demo cutover are not part of
this image-run authorization.

The active request allowance is `catalog-10000-images-001`. Resume with this
same approval ID and allowance; never replace the ID to evade an exhausted cap:

```powershell
.\.venv-catalog\Scripts\python.exe src\load-generator\image_pipeline.py `
  --catalog-dir data\catalog-expanded-10000 `
  --project-endpoint https://hdfoundrytszg.services.ai.azure.com/api/projects/agentprojtszg `
  --deployment MAI-Image-2.6-Flash --model-version 2026-07-31 `
  --requests-per-minute 6 --workers 2 `
  --start-id 1002 --end-id 10000 --max-products 8999 `
  --storage-account strezolvefrv3w6fiiwjwi --image-container product-images-scale-001 `
  --approval-id catalog-10000-images-001 --max-requests 8999 `
  --execute --confirm-storage strezolvefrv3w6fiiwjwi/product-images-scale-001
```

One primary image per product is retained. Blocks and uncertain outcomes can
leave fewer successful images than attempted requests and require explicit
review; the allowance is not a guaranteed completion count or monetary cap.
Do not run the older two-million-product pipeline concurrently against the same
image destination. Never regenerate the preserved calibration on resume.

### Pending-only resume after a stopped run

The user authorized continuing only the 6,516 unsubmitted products after the
run stopped with 3,246 verified, 237 blocked and one uncertain outcome
(`PROD-003475`). The existing 8,999-attempt approval has already used 2,483;
reuse it without increasing the limit or creating a new allowance.

`--pending-only` explicitly excludes blocked/uncertain/staged jobs and any job
with a recorded specification, fingerprint or HTTP-attempt history. Their
records remain unchanged and unresolved totals remain visible in the summary.
The default resume path is unchanged for separately reviewed recovery.

New unsubmitted prompts use `product-focused-v3`: concise product facts, visible
pattern requirements, complete everyday outfits for fictional adult models,
and category-specific framing. Gender presentations, product-only categories
and one-primary-image cardinality are retained. Recorded v1/v2 specifications
are immutable. This revision is not a bypass of service safety filters and
does not establish the cause of prior blocks or promise their elimination.

```powershell
.\.venv-catalog\Scripts\python.exe src\load-generator\image_pipeline.py `
  --catalog-dir data\catalog-expanded-10000 `
  --project-endpoint https://hdfoundrytszg.services.ai.azure.com/api/projects/agentprojtszg `
  --deployment MAI-Image-2.6-Flash --model-version 2026-07-31 `
  --requests-per-minute 6 --workers 2 `
  --start-id 1002 --end-id 10000 --max-products 6516 --pending-only `
  --storage-account strezolvefrv3w6fiiwjwi --image-container product-images-scale-001 `
  --approval-id catalog-10000-images-001 --max-requests 8999 `
  --execute --confirm-storage strezolvefrv3w6fiiwjwi/product-images-scale-001
```

This can progress the remaining work but cannot make the full catalogue ready
while any blocked or uncertain image remains. Cosmos publication stays gated.

This separately approved workflow retains the existing 1,000 products and their
original images/history, and adds up to 1,999,000 products for **2,000,000 total
parent products**. Variants are additional records inside each parent, not part
of that target. It does not reseed or modify `data\catalog`.

The v2 taxonomy contains 27 category-specific product types across the existing
ten fictional brands. It includes trousers, clothing, footwear, bags, hats,
scarves, belts, gloves, socks, sunglasses, necklaces, bracelets, earrings,
wallets and pouches. Category-valid design combinations are deterministically
enumerated rather than making duplicates unique only by changing an ID.
Canonical IDs expand naturally from `PROD-999999` to `PROD-1000000` through
`PROD-2000000`; size variants retain distinct SKUs.

New clothing and wearable accessories use fictional adult models with balanced
women, men and non-binary presentation per category, varied skin tones and body
types. Wallets/pouches use product-only photography. Product departments are
separate from model presentation. Original photographs are not regenerated.
Prompts describe the actual product, colour, material, pattern, detailing and
framing; generated output still needs human visual review.
The `product-fidelity-v2` prompt revision explicitly requires visible pattern
geometry, palette, material and construction. For example, wide stripes must
be broad repeating fabric bands rather than seams, shadows or a single side
panel. Each request still produces **one primary image per product**, not a
gallery or alternative designs.

The photography presentation policy remains `adult-fashion-v1`; prompt revision
is recorded separately in each image specification/receipt. Pending jobs without
a submitted specification use the new fidelity prompt. Jobs with a recorded
specification resume that exact specification, and already verified images are
skipped. Refining prompts neither overwrites completed images nor authorizes
regeneration. Prompt export preserves recorded prompts and uses the new revision
for unsubmitted jobs.

### Runtime and offline generation

Python 3.11+ is retained. The metadata generator uses the standard library;
the new image/upload workflow additionally uses Azure Identity, Azure Blob
Storage and Pillow, declared in
[`requirements-images.txt`](../src/load-generator/requirements-images.txt).
Use a separate environment, not the Search API or shared machine installation:

```powershell
python -m venv .venv-catalog
.\.venv-catalog\Scripts\python.exe -m pip install -r src\load-generator\requirements-images.txt

# Offline only; no model, upload or Cosmos calls.
.\.venv-catalog\Scripts\python.exe src\load-generator\expand_catalog.py `
  --source data\catalog --output-dir data\catalog-expanded-v2 `
  --target-count 2000000

# Metadata-only export for capacity analysis, NOT a publishable image catalogue.
.\.venv-catalog\Scripts\python.exe src\load-generator\expand_catalog.py `
  --output-dir data\catalog-expanded-v2 `
  --export data\catalog-expanded-v2\metadata --metadata-only
```

Choose the target once; identical commands resume, while changed source hashes,
seed, target or schema/prompt policy require a separate run. The source must
contain contiguous canonical IDs and completed PNGs with matching receipts.
The tool verifies copied bytes under `original\`. Retain that source independently.

`catalog.sqlite` stores products, disk-backed unique IDs/SKUs/design signatures,
image states and approved request allowances. Transactions checkpoint bounded
groups of products; this avoids filesystem shards plus duplicate checkpoint logic.
Product JSONL and matching new-product `image-prompts.jsonl` are streamed on
explicit export, not rewritten after each image. Prompt export uses the same
builder as generation and excludes already photographed originals. New
SVGs and legacy Azure AI Search batches are not emitted. `manifest.json`
reports completed/pending states and never labels pending photographs ready.
The expanded `imagePath` is an asset key, not a promise that all image bytes
remain on local disk.

The operation lock prevents competing catalogue commands. After an unclean
termination, confirm the owning process stopped before removing only the
specific run's `run.lock`. Do not remove the SQLite/WAL files. For a consistent
checkpoint backup, stop writers and use SQLite's backup API rather than copying
an active database file alone.

### Paid generation and upload gate

The user selected deployment name `MAI-Image-2.6-Flash` in the supplied Foundry
project and reported **6 RPM**. Verify the actual model version and regional
pricing before execution. A project URL is not proof of deployment permission.
The version records provenance; it does not pin or update the deployed model.
Do not change the deployment during a run.

Use the existing Storage account with a **new versioned image container**, for
example `product-images-scale-001`. The
[additive snapshot template](../infra/catalog-snapshot.bicep) creates only new
containers and scoped roles against existing accounts. It must be reviewed and
explicitly authorized before deployment. Keep `product-images` and the active
Cosmos container unchanged. Do not put receipts, prompts or checkpoints in a
public image container.

The following is a **dry run by default**, for the first 81 new products:
three presentation cycles across all 27 product types. Set the model version
from verified deployment metadata, not from a guess.

```powershell
$imageArgs = @(
  '--catalog-dir', 'data\catalog-expanded-v2',
  '--project-endpoint', 'https://hdfoundrytszg.services.ai.azure.com/api/projects/agentprojtszg',
  '--deployment', 'MAI-Image-2.6-Flash',
  '--model-version', '<verified-deployment-version>',
  '--requests-per-minute', '6', '--workers', '2',
  '--start-id', '1001', '--end-id', '1081', '--max-products', '81',
  '--storage-account', 'strezolvefrv3w6fiiwjwi',
  '--image-container', 'product-images-scale-001',
  '--approval-id', '<approved-batch-id>', '--max-requests', '81'
)
.\.venv-catalog\Scripts\python.exe src\load-generator\image_pipeline.py @imageArgs

# Only after explicit paid-pilot AND upload authorization:
# .\.venv-catalog\Scripts\python.exe src\load-generator\image_pipeline.py @imageArgs `
#   --execute --confirm-storage strezolvefrv3w6fiiwjwi/product-images-scale-001
```

The allowance counts **HTTP attempts, including retries**, not successful images.
It persists across resumes. Raising an existing allowance is rejected; a new
batch needs a new approval. It is not a monetary billing cap. Actual model
charges depend on billed token usage; inspect recorded response usage/request
IDs and the provider bill before estimating a larger batch. Missing usage
is unknown cost evidence, not zero cost.
For an approved upload-only pass over IDs 1-1000, use a zero request allowance;
this forbids inference even if an unexpected pending job is encountered.

Known completed images are skipped. Submission intent is committed before a
billable request. An ambiguous timeout or response loss is not automatically
retried, including after restart. Reconcile it explicitly; provider idempotency
is not assumed. Safety blocks and exact duplicate images are quarantined, not
automatically re-prompted or reported as completed.

PNG checksums, dimensions and decoded pixels are validated. A staged image and
its recovery receipt survive upload errors. Conditional blob creation never
overwrites differing content; length, SHA-256 metadata, stored MD5 and PNG MIME
must match. Staging bytes are removed only after verified upload and a durable
commit. Original copied assets remain local. If upload fails, resume upload
without calling the model again. Exact byte uniqueness is not proof of visual
distinctiveness; review a stratified pilot before expanding.

### Measured offline expansion

The local expanded dataset has been generated and validated with:

| Check | Result |
|---|---|
| Parent products | 2,000,000 |
| Variants | 8,224,250 |
| Preserved original photographs | 1,000, unchanged |
| New distinct design signatures and canonical prompts | 1,999,000 |
| New categories | 27 |
| Planned modelled / product-only photographs | 1,850,926 / 148,074 |
| Gender-presentation allocation | Balanced within one per new category |
| Generator/export and Cosmos validation peak process working set | Each below 40 MiB |
| Normalized Cosmos document bytes | 4,585,142,967, excluding indexes |
| New model calls / Azure data writes during validation | 0 / 0 |

Evidence is saved locally under `data\catalog-expanded-v2\` as
`scale-evidence.json`, `diversity-evidence.json` and `cosmos-preflight.json`.
Products, prompts and checkpoint data are ignored by Git. Full-scale metadata
validation is not evidence of image quality, live Cosmos performance, inference
success or a deployed two-million-product catalogue.

Read-only CLI inspection verified the existing MAI-Image-2.6-Flash deployment
as version `2026-07-31`, Global Standard, with six requests per 60 seconds.
The public Azure retail API lists Sweden Central Global Standard Flash meters
at USD 1.75 per million text-input tokens and USD 19 per million image-output
tokens. These are **token rates, not per-image prices**; actual usage and any
subscription-specific agreement must be checked before extrapolating model cost.
Source: [Azure Retail Prices API](https://prices.azure.com/api/retail/prices).

An optional separately approved single-request calibration can precede the
81-product diversity pilot. Provision only the versioned image container
(`includeCatalog=false` in the snapshot template), verify upload with one
preserved original, then allow one new image request. Capture returned usage
and inspect that result before approving more requests. This is not approval
for that calibration or any cloud mutation.

### Authorized single-request calibration evidence

The user subsequently authorized and completed that calibration:

- Only `product-images-scale-001` and its container-scoped uploader role were
  created in the existing Storage account. No Cosmos resource or demo change.
- One preserved original image was uploaded to verify Entra access, with a
  zero-model-request allowance.
- `PROD-001001` generated successfully with exactly one HTTP request using
  MAI-Image-2.6-Flash `2026-07-31`. The 1024 x 1024 PNG is 1,210,077 bytes.
- Anonymous image download matched the saved SHA-256 and PNG MIME type;
  anonymous container listing was denied. Local staging was removed only after
  verified upload. Repeating the completed command made no additional model call.
- Returned usage: 207 text-input tokens, 1,024 output-image tokens, no image
  input. At the retrieved retail meters, this is approximately USD 0.01981825
  for model inference, not an invoice or an inclusive cloud cost.
- At identical usage, 80 more successful images would be approximately USD 1.59;
  all 1,999,000 new images would be approximately USD 39,616.68 before
  retries, changed token usage, storage, operations, egress or account discounts.
  No large-batch spending has been authorized.
- Visual inspection shows a fully framed adult model wearing dusty-pink baggy
  jeans, but the requested wide-stripe pattern is not clearly represented.
  This image is technically verified, **not human-approved product fidelity**.

Local evidence is in `data\catalog-expanded-v2\calibration-evidence.json`.
The initial photo does not establish gender/category coverage across outputs;
that requires a separately approved, reviewed diversity pilot. The remaining
new photographs and live catalogue publication are still pending.

### Publication, capacity and rollback

After every required image, including the original 1,000, has been uploaded and
verified, export without `--metadata-only`:

```powershell
.\.venv-catalog\Scripts\python.exe src\load-generator\expand_catalog.py `
  --output-dir data\catalog-expanded-v2 --export data\catalog-expanded-v2\publish
```

The manifest binds the exact source bytes, complete image count and destination.
See the [Search runbook](../src/search-api/README.md#large-catalogue-imports) for
streaming Cosmos validation and separately approved writes. `/scopeId` remains
an explicitly conditional POC layout: normalized document data must remain below
the conservative 10 GiB planning ceiling, and actual service storage/index
headroom, RU, throttling, count and ranked-query tests must pass. Passing an
offline byte check alone is not capacity or performance proof.

Do not switch the live demo until a fresh immutable container is ready and
real API/browser checks pass. Keep the previous container, image assets and
configuration for rollback. Model generation, uploads, large Cosmos ingestion
and cutover require their own approved scope; the tooling does not authorize them.
