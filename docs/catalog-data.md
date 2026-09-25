# Synthetic product catalog

The catalog generator creates original, deterministic fashion-retail sample
data for the search and trend-ranking POC. Its structure is informed by common
product-detail patterns such as a parent product, colourway, price, gallery,
fit/material details, and purchasable size variants. It does not copy product
descriptions, images, identifiers, or brand data from ASOS.

## Generated assets

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

Run the standard-library unit tests:

```powershell
python -m unittest discover -s src\load-generator -p "test_*.py"
```

The tests verify deterministic catalog output, product and image counts, unique
product IDs, variants, stock and trend initialization, index schema/batches,
PNG validation, resume and input-change checks, bounded throttling retries,
failure handling, protection against reseeding, and image-reference updates
without changes to product data or existing Search trend scores. The reviewed
pass also has tests for category-specific prompts, preserving original block
history, resumability, and refusing duplicate submissions after a new block
or uncertain outcome.
