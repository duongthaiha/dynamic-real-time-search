# Cosmos catalogue Search POC

Python/FastAPI implements [`POST /v1/search`](../../docs/api/search.openapi.json)
over Cosmos DB for NoSQL native English full-text/BM25. It is a bounded synthetic
catalogue POC, not Google AI Commerce parity. See the
[gap analysis/product backlog](../../docs/architecture/cosmos-search-poc-backlog.md).
The approved synthetic import, real HTTP API and bounded concurrent Cosmos
queries have passed live validation; see the
[measured evidence](../../infra/README.md#deployment-and-live-verification-evidence).

## Runtime and installation

Python 3.11+; development verification uses Python 3.13. Dependencies are
declared in [pyproject.toml](pyproject.toml). The verified environment uses
FastAPI 0.141.1, Pydantic 2.13.5, azure-cosmos 4.17.1, azure-identity 1.26.0
and uvicorn 0.54.0. Cosmos uses the async SDK with aiohttp and a single client
per API lifespan. Public client-key authentication is separate from Entra
authentication to Cosmos.

Run from the repository root in PowerShell:

```powershell
python -m venv .venv-search
.\.venv-search\Scripts\python.exe -m pip install -e "src\search-api[dev]"
.\.venv-search\Scripts\python.exe -m unittest discover -s src\search-api\tests -p "test_*.py"
.\.venv-search\Scripts\python.exe -m ruff check src\search-api
.\.venv-search\Scripts\python.exe -m pyright --project src\search-api\pyproject.toml --pythonpath .venv-search\Scripts\python.exe
# After installing the separate catalogue environment from docs/catalog-data.md:
.\.venv-catalog\Scripts\python.exe -m unittest discover -s src\load-generator -p "test_*.py"
```

Unit tests use injected fixtures/mocks, never Cosmos or model calls. There is
no runtime fake/in-memory fallback. API startup without the required
configuration, Cosmos access, index or ready import fails explicitly.

## Catalogue export and import

Reuse `data\catalog\products.jsonl`; do not reseed a catalogue with image state.
The default synthetic source contains 1,000 parent products and 6,136 variants.
Export is offline and validates the complete input before any writes:

```powershell
.\.venv-search\Scripts\catalog-import.exe `
  --epoch catalog-images-001 --image-container product-images --output data\cosmos-poc\relative-catalog
```

The output contains normalized Cosmos documents and a container policy:

- `/scopeId` partition key, `id=productId`, complete correlated variants;
- integer minor-unit GBP prices, public `attributes.color` mapping;
- normalized `searchText` from title, description, brand, category, attributes,
  and tags; English full-text policy/index;
- source timestamps, schema version and immutable import epoch;
- no profiles, embeddings, trend boosts or local image-generation receipts.

Display labels and variant sizes are preserved. Comparisons normalize
case/whitespace. `--image-container` publishes schema v2: Cosmos stores
`imagePath: "product-images/prod-000001.png"` and gallery `path` entries, with
no storage hostname or image URL. Source products, image receipts and batch
files are untouched. Omitting the flag retains the legacy v1 absolute-URL
format for old snapshots; it is not the current deployment format.

`CATALOG_IMAGE_BASE_URL` supplies the HTTPS storage/CDN origin at runtime.
For example, the same Cosmos path resolves to either
`https://devimages.blob.core.windows.net/product-images/prod-000001.png` or
`https://prodimages.blob.core.windows.net/product-images/prod-000001.png`.
Only configuration changes between environments; documents do not.
The public API still returns an absolute `imageUrl` as required by its contract.
Relative snapshots fail readiness explicitly if the base URL is missing.

### Large-catalogue imports

The CLI now validates up to 2,000,000 products using a disk-backed SQLite snapshot
and streaming hashes/export; it does not materialize the full catalogue in RAM.
The legacy `load_catalog` helper remains bounded to 1,000 records for existing
small-catalogue callers. Prices, UTC timestamps, per-item byte limits, global
product/colourway/variant/SKU uniqueness and correlated variants remain validated.

Start with the [offline expansion workflow](../../docs/catalog-data.md#large-catalogue-expansion).
Its metadata-only output is suitable for this **offline** size preflight, not
cloud publication:

```powershell
.\.venv-search\Scripts\python.exe -m catalog_search.importer `
  --source data\catalog-expanded-v2\metadata\products.jsonl `
  --epoch catalog-scale-001 --image-container product-images-scale-001
```

The report includes normalized document bytes, maximum document size, counts and
hashes. A conservative 10 GiB document-data planning ceiling is enforced before
any cloud write. Index overhead is **not** included: verify actual logical-partition
headroom and serverless throughput, then measure broad/narrow queries and exact
counts at staged sizes. Stop for a partition/retrieval redesign if approved
capacity, RU or query budgets fail. Do not hide failures by widening deadlines,
approximating counts or silently dropping eligibility predicates.

Large writes additionally require:

- A complete image-verified export manifest matching the exact input hash and
  selected image container. Metadata-only, partial or changed exports are rejected.
- A dedicated fresh Cosmos container and immutable epoch, provisioned through the
  [additive snapshot template](../../infra/catalog-snapshot.bicep) after approval.
- `--capacity-reviewed`, an explicitly approved `--max-request-units` allowance,
  and the existing exact `--confirm-container`/epoch checks.
- Bounded import workers (1 by default, at most 8). Every stored document is
  verified; the ready marker appears only after complete count verification.

The RU allowance stops new operations at the **observed** threshold; already
submitted operations can exceed it. It is not an Azure billing cap. Resume using
identical input and a newly approved allowance where needed; never repair a
published ready catalogue in place.

After approval, set the new container/epoch in the importer process only. Use
the image-complete `publish\products.jsonl`, not `metadata\products.jsonl`:

```powershell
# $approvedImportRu must be agreed before execution; all cloud calls are billable.
# .\.venv-search\Scripts\python.exe -m catalog_search.importer `
#   --source data\catalog-expanded-v2\publish\products.jsonl `
#   --epoch catalog-scale-001 --image-container product-images-scale-001 `
#   --workers 4 --capacity-reviewed --max-request-units $approvedImportRu `
#   --write --confirm-container catalog-scale-001
```

Validate a separately configured API instance against the new snapshot before
changing the active demo's container/epoch. Check seven-digit product IDs/SKUs,
categories, same-variant size/price/stock filters, exact totals, paging, hosted
images and readiness in real HTTP/browser tests. Retain the current configuration
and old containers for rollback. Catalogue size does not change the existing
page-size maximum of 100 or the 1,000-result ranked window.

### Live prerequisites

The separately approved backend deployment is reproducible through
[infra/main.bicep](../../infra/main.bicep) and
[infra/cosmos.bicep](../../infra/cosmos.bicep). See the
[infrastructure runbook](../../infra/README.md) for resource-group creation,
Entra data-plane role scope and restricted-network configuration. Infrastructure
deployment is not proof of a successful import or query.

Cloud calls and writes need explicit authorization. Choose an existing account,
database and **dedicated fresh container** with `/scopeId`, the exported
full-text/index policies and no TTL. The importer does not create accounts,
databases, containers, roles or throughput. Verify account/region full-text
availability and policy support with the official
[full-text documentation](https://learn.microsoft.com/azure/cosmos-db/gen-ai/full-text-search).

Use Entra/managed identity. For local development, an authorized `az login`
can supply DefaultAzureCredential. Assign the API only the necessary Cosmos
data read/query permissions scoped to the POC container; use a separately
authorized import identity with write permissions. Resource management roles
alone do not establish Cosmos data-plane access.

```powershell
$env:COSMOS_ENDPOINT = "https://<account>.documents.azure.com:443/"
$env:COSMOS_DATABASE = "<existing-database>"
$env:COSMOS_CONTAINER = "<dedicated-existing-container>"
$env:CATALOG_IMPORT_EPOCH = "catalog-images-001"
$env:CATALOG_IMAGE_BASE_URL = "https://<storage-account>.blob.core.windows.net"

# Only after explicit upload authorization:
.\.venv-search\Scripts\catalog-import.exe --epoch catalog-images-001 `
  --image-container product-images `
  --write --confirm-container $env:COSMOS_CONTAINER
```

The importer creates an `__catalog_import__` control document with the expected
content hash, then creates/verifies every product. A ready marker is published
only after all items and the parent count verify. Resume with identical input;
different input/epoch, unexpected products or changed stored products fail
explicitly. A ready import is not edited in place. Use a fresh versioned
container for replacement data and switch API configuration only after it is
verified. Do not mutate this static import while testing count/paging.

## Client configuration and startup

Create a high-entropy server-side client key; do not commit it, paste it into
logs or put it in storefront JavaScript. Store only its SHA-256 hash in a
configuration file readable only by the service account. For local development,
the grant file may live at `.local\search-clients.json` (ignored by Git), or at
an external private path. Do not commit actual grants or raw credentials.
That file contains a JSON array:

```json
[
  {
    "key_sha256": "<64-lowercase-hex-SHA256-of-your-client-key>",
    "scope_id": "demo-store",
    "areas": ["storefront"],
    "collections": ["products"],
    "diagnostics": false
  }
]
```

Scope comes from this grant, not session/visitor IDs. Use a separate grant for
authorized diagnostics; do not broaden a public credential.

```powershell
$env:SEARCH_CLIENTS_FILE = ".local\search-clients.json"
.\.venv-search\Scripts\python.exe -m uvicorn catalog_search.app:create_app `
  --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Startup validates partition/index configuration, the ready import epoch and
an actual keyword query. `/health/live` checks the process; `/health/ready`
checks Cosmos and the import. Both are internal operational endpoints, not
extensions of the public Search API. Restrict their network exposure.

Send a request from an authorized BFF/server caller:

```powershell
# Set SEARCH_CLIENT_KEY securely in your local process; do not commit its value.
$headers = @{
  Authorization = "client-key $env:SEARCH_CLIENT_KEY"
  "x-customer-id" = "demo-store"
}
$body = @{
  area = "storefront"; collection = "products"; query = "green jeans"
  skip = 0; pageSize = 20
  refinements = @(
    @{ navigationName = "attributes.color"; type = "Value"; value = "green" }
    @{ navigationName = "price"; type = "Range"; low = 20; high = 60 }
  )
} | ConvertTo-Json -Depth 6
Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/search" `
  -Method Post -Headers $headers -ContentType "application/json" -Body $body
```

## Local browser demo

The optional test page is available at `http://127.0.0.1:8000/demo`.
It shows live product cards/images, exact totals, response timing and request
IDs, with keyword/identifier search, colour/category/size/price filters and
bounded previous/next paging. It does not implement facets, recommendations,
checkout or exposure capture.

Enable it explicitly after configuring Cosmos, the image origin and client
grants as above:

```powershell
$env:SEARCH_DEMO_ENABLED = "true"
$env:SEARCH_DEMO_CLIENT_KEY_FILE = "<private-file-containing-the-scoped-client-key>"
.\.venv-search\Scripts\python.exe -m uvicorn catalog_search.app:create_app `
  --factory --host 127.0.0.1 --port 8000 --no-access-log
```

The private key must match a grant authorized for `storefront` / `products`;
customer scope is derived server-side from that grant. The browser never receives
the key. `/demo/search` is a local BFF proxy calling the same authenticated
`POST /v1/search` implementation, with no fake results or alternate ranking.
It rejects client scope/diagnostic overrides and shares the API's budgets,
validation and explicit errors.

Demo routes are disabled by default, accept only loopback clients and literal
loopback hostnames, and reject cross-origin/cross-site requests. Bind to
`127.0.0.1`; do not expose this developer proxy through public ingress. A hosted
storefront requires a separate identity/authorization design. Set
`SEARCH_DEMO_ENABLED=false` to disable the demo without changing the public API.

Try `green jeans`, `jeans`, `PROD-000001`, or `SYN-000001-01`.
Price filtering requires both finite bounds. Category/colour choices are curated
for this synthetic catalogue, not dynamically generated facet counts.

## Debugging locally in VS Code

The repository includes two [F5 configurations](../../.vscode/launch.json):
**Search API: local Cosmos demo** and **Search API: offline tests**.
They explicitly use `.venv-search`, without changing the workspace's selected
Python interpreter or the existing image-generator environment.

### Prepare the API debugger

1. Open the repository root folder in VS Code. Install/enable the Microsoft
   **Python** and **Python Debugger** extensions.
2. Complete the runtime installation above and sign in with an authorized
   `az login`. The launch configuration prepends `.venv-azure\Scripts` to PATH
   when that isolated CLI exists; otherwise the normal installed CLI is used.
3. Create an ignored local environment file from the
   [nonsecret template](../../.env.local.example):

   ```powershell
   Copy-Item .env.local.example .env.local
   ```

   Replace the placeholder account names and private file paths. Use the
   endpoint/database/container/image origin from the approved Bicep outputs.
   The grant file can use the ignored `.local\search-clients.json` location;
   keep the raw demo key file outside the repository. Never put the raw
   client key, an Entra token, a SAS token or a storage key into the template.
   `.env.local` is ignored by Git and is not packaged into the image.
4. In **Run and Debug**, select **Search API: local Cosmos demo** and press **F5**.
   Wait for `Application startup complete` in the Integrated Terminal, then open
   `http://127.0.0.1:8001/demo`.

The debug profile uses port **8001**, so the normal demo on port **8000** can
remain running. It deliberately omits `--reload` and multiple workers:
breakpoints stay in the process managed by VS Code. Use **Shift+F5** to stop and
**Ctrl+Shift+F5** to restart after edits; stopping this profile does not stop
the ordinary 8000 listener.

### Useful breakpoints and stepping

Set breakpoints with **F9**, submit a synthetic search in the debug page, then
inspect only nonsecret application values:

Startup also performs a `jeans` readiness query. A breakpoint in retrieval can
hit before the listener is ready; continue through that probe first, then submit
your own search to inspect the request path.

| Location | What to inspect |
|---|---|
| [demo.py](catalog_search/demo.py), `proxy` | Browser query/refinements, fixed area/collection and downstream status |
| [app.py](catalog_search/app.py), `search` | Validated request, skip/pageSize, authorization outcome and response mapping |
| [query.py](catalog_search/query.py), `build_query` | Parameterized predicates, AND/OR grouping and correlated variant eligibility |
| [cosmos.py](catalog_search/cosmos.py), `search` | Exact count, bounded ranked prefix, document versions and request charge |
| [app.py](catalog_search/app.py), `public_product` | Eligible variants and the absolute URL resolved from relative image paths |

Use **F10** to step over, **F11** to step into and **F5** to continue. Use
conditional breakpoints for one product/query or logpoints for timing; do not
print credentials or real shopper identifiers. Avoid expanding the demo key
or SDK authorization/token internals when sharing debugger screenshots.

The API's 10-second dependency deadline and browser's 15-second abort timer
remain active while the process is paused. Long breakpoint pauses can therefore
produce an expected timeout rather than a query defect. Resume quickly around
awaited SDK calls, or use the offline-test profile for lengthy inspection;
do not relax production budgets to mask a debug pause.

### Debug tests without Azure

Select **Search API: offline tests** and press **F5**. It runs the existing
unittest suite with fixture repositories and mocked SDK calls: no Azure account,
local environment file, uploads or paid queries are needed.
Put breakpoints in the test or application function under test. For one case,
duplicate this local configuration and replace the discovery args with the
chosen unittest module/method; do not add cloud calls to unit tests.

### Debug the browser and diagnose startup

- Open browser Developer Tools (**F12**) at the 8001 demo. **Network** shows
  `/demo/search`, status codes, response JSON and request IDs; **Sources** shows
  `demo.js`. The private key is injected server-side, never by JavaScript.
- A hollow/unbound breakpoint usually means the wrong interpreter/process or
  that you started the non-debug 8000 server. Use the named F5 profile and check
  `.venv-search` exists and the editable package was installed.
- `/demo` returning 404: verify `SEARCH_DEMO_ENABLED=true` in `.env.local`.
- Configuration/startup failure: verify all required file paths, the ready
  catalogue epoch, `CATALOG_IMAGE_BASE_URL`, Entra sign-in/data-plane permissions
  and Cosmos network allowlist. Do not fall back to keys or fabricated results.
- Port 8001 in use: stop only your known debug process, or change the profile
  to another local port. Do not kill unrelated processes by name.
- `debug: true` in the public Search request is an authorized RU diagnostic
  option, **not** a switch that enables the Python debugger.

For the debugger's general controls and configuration syntax, see the
[official Python debugging guide](https://code.visualstudio.com/docs/python/debugging).

## Supported behavior and limits

| Area | POC behavior |
|---|---|
| Matching | Nonempty normalized terms; FullTextContainsAll matching, BM25 ordering |
| Identifier lookup | Exact case-normalized product IDs/SKUs with six digits, or seven digits through 2000000; no fuzzy substitution |
| Value refinements | attributes.color, attributes.size, category, brand, department, productType, attributes.fit, attributes.material |
| Range refinements | price, inclusive GBP range, finite endpoints with magnitude <= 1e12 |
| Combination | AND across fields; OR within a field by default, AND with or=false; mixed modes are 400 |
| Eligibility | Searchable parent and one same variant satisfying size, price, stock and exact SKU when supplied |
| Product price | Minimum price among variants satisfying all request eligibility constraints |
| Count | Exact matching eligible parent count before paging, not candidate/page length |
| Page | Default 20, maximum 100; skip + pageSize <= 1000; bounded ranked prefix then slice |
| Budgets | 64 KiB body, 512 query characters, 32 terms, 32 refinements; 10-second dependency deadline |
| Admission | 16 concurrent searches, 120 accepted searches/minute per configured credential per process |
| Retry | SDK bounded to 3 retry attempts per policy; honors Cosmos retry-after, within the application deadline |
| Cache | None; Cache-Control: no-store. Authorized bypass is a no-cache operation |
| Debug | Requires diagnostics grant; exposes only request RU response header, not SQL, keys or source documents |
| Unknown request fields | Accepted without a defined effect; not permission to bypass validation |
| Unsupported | Topsort=true, any sponsorship object, unsupported fields/limits return 422 |
| Correlation | Independent server UUID; optional attribution token omitted |
| Failure | Contract Error body; 400/401/403/422/429/500/503; local admission 429 has Retry-After |

Settings are finite, validated values in `config.py`; defaults above are the
published POC limits. Database identity/epoch and grants come from environment
configuration. Rate/admission controls are process-local, not distributed;
run a single worker for this POC. TLS termination, production CORS, public
identity/edge controls and cross-process rate limiting need separate design.

Count and records are separate reads, not an atomic Cosmos snapshot. The
published catalogue must be frozen; inconsistent count/prefix results fail
503 rather than inventing a total. BM25 ties and ordering across repeated
requests remain service-dependent; no stable snapshot/global paging claim.
SDK pages are fully consumed within the bounded prefix, not mistaken for a
complete query. FullTextScore is not selected/projected.

Cosmos outages or exhausted throttling return 503, never empty success.
There are no optional live factors, so successful baseline responses have
degraded=false. Search does not emit views, cart events or Beacon exposures.
Telemetry logs correlation, mode, epoch, timing and successful query RU only;
do not enable raw SDK HTTP logging or record keys/query/session/visitor data.

## Evaluation and live feasibility

Validate supplied cases offline:

```powershell
.\.venv-search\Scripts\catalog-evaluate.exe `
  --cases src\search-api\evaluation-cases.json
```

After authorizing Cosmos reads and importing the pinned dataset:

```powershell
.\.venv-search\Scripts\catalog-evaluate.exe --live `
  --cases src\search-api\evaluation-cases.json --repeat 3 --concurrency 4 `
  --output data\cosmos-poc\evaluation.json
```

The report identifies live vs offline evidence, exact ID/range/stock assertions,
NDCG@10 over supplied judgments, Recall@20 only for exhaustive judgments,
zero-result rate, p50/p95 adapter latency and RU for count plus ranked-prefix
reads. It exits nonzero on failed assertions or dependency errors. Failed
operation charges may be unavailable; this is not a complete billing estimate.
The latency excludes HTTP transport and initial readiness checks.

The included fashion-keyword judgments are intentionally incomplete; add
retailer-reviewed judgments before drawing relevance conclusions. Offsets,
typos, missing products and multiple terms are explicit cases. Synthetic
tests do not prove Google parity, revenue uplift or production performance.
No Google API calls are made. Thresholds and a provider comparison require
owner-approved workloads and separately authorized evidence.

## Container

Build the OCI image from the service directory:

```powershell
docker build -t cosmos-catalog-search:0.1.0 src\search-api
```

If corporate networking blocks public PyPI, use an approved HTTPS package feed
with `--build-arg PIP_INDEX_URL=<approved-feed-url>`. Do not disable TLS verification
or put credentials in build arguments; authenticated feeds require a separate
build-secret setup.

The image runs as a non-root user. Supply the four Cosmos environment variables
and `CATALOG_IMAGE_BASE_URL` for the relative-image snapshot,
and mount the private grants file read-only; set SEARCH_CLIENTS_FILE to that
mounted path. Container Entra credentials need an explicitly configured
workload/managed identity or approved development credential mechanism; host
`az login` is not automatically available inside the image. No secrets are
baked in and no infrastructure is provisioned. Docker build/runtime verification
requires a running Docker engine; offline Python checks are not a container test.

## Optional hybrid experiment

Not enabled in this implementation. The backlog gates it on embedding
provider/version/dimensions and paid-call approval, vector-container policy,
plus a reviewed definition of semantic matching and exact totalRecords.
Do not expose a hybrid mode until these decisions are resolved. Nonzero hybrid
skip remains unsupported; do not return a top-k count as the catalogue total.
