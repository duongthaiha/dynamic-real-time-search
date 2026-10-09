# Dynamic real-time search

Commerce discovery using Azure Cosmos DB as the canonical data store and
portable, containerized application components. The target includes keyword
search/browse, merchandising, deterministic recommendations, consented
rule-based preferences and guided discovery without AI services.

## Repository contents

- [src/load-generator](src/load-generator/): Python catalog/image generators,
  offline unit tests, a legacy Search index definition, and a resumable expansion
  pipeline for up to 2,000,000 synthetic products.
- [src/search-api](src/search-api/): Python/FastAPI Cosmos keyword-search POC,
  local browser demo, offline tests, safe catalogue importer and opt-in evaluation runner.
- [docs](docs/): research, architecture, API drafts, and operating instructions.
- [.github/copilot-instructions.md](.github/copilot-instructions.md): agent working rules.

The Search keyword POC is implemented and verified over the synthetic catalogue
against the authorized Azure Cosmos backend through real HTTP requests.
See the [live verification evidence](infra/README.md#deployment-and-live-verification-evidence).
Beacon, merchant APIs and the end-to-end ranking pipeline remain designs.
There is no platform-wide build or production/Google-parity claim.

## Local commands

Run from the repository root using the Python environment for this repository:

```powershell
python src\load-generator\generate_catalog.py
# Full generator tests include the optional image pipeline dependencies:
python -m venv .venv-catalog
.\.venv-catalog\Scripts\python.exe -m pip install -r src\load-generator\requirements-images.txt
.\.venv-catalog\Scripts\python.exe -m unittest discover -s src\load-generator -p "test_*.py"
```

Generation writes to `data\catalog\`. **Do not reseed a catalog containing
image-generation state**; use a separate output directory. See the
[catalog guide](docs/catalog-data.md) for options, data shape, indexing, and
image hosting. The approved [large-catalogue workflow](docs/catalog-data.md#large-catalogue-expansion)
preserves that source in a separate output, streams metadata into disk-backed
checkpoints, and uploads generated images incrementally instead of retaining
millions of photographs locally.

For the Cosmos Search POC, use the separate [Search runbook](src/search-api/README.md)
for installation, offline tests, dry-run export, scoped credentials and startup.
The [local browser demo](src/search-api/README.md#local-browser-demo) provides a
simple test page with live images, filters and paging; server-side credentials
remain out of browser JavaScript.
The [local debugging guide](src/search-api/README.md#debugging-locally-in-vs-code)
covers F5 profiles, safe environment setup, breakpoints and browser diagnostics.
Do not upload data or provision resources without explicit authorization.
The approved isolated Azure backend is defined by
[subscription-level Bicep](infra/main.bicep) and the
[Cosmos module](infra/cosmos.bicep); see the [infrastructure runbook](infra/README.md).
The [image Storage module](infra/storage.bicep) hosts the synthetic assets.
The active Cosmos snapshot stores relative image paths; the API resolves their
origin through `CATALOG_IMAGE_BASE_URL`, keeping dev/test/prod account names out
of catalogue documents.

## Architecture

These are selected design choices, not deployed-resource claims:

| Area | Approach |
|---|---|
| APIs | Separate containerized Discovery, Beacon and Merchant Admin services with OpenAPI contracts. |
| Canonical data | Azure Cosmos DB for NoSQL for catalog, events, policies, factors, recommendation lists, optional profiles and durable control state. |
| Retrieval | OpenSearch keyword retrieval as a rebuildable projection of Cosmos data; no semantic, vector or generated-query path. |
| Ingestion | Portable HTTP/source adapters write validated, deduplicated records to Cosmos; change-feed workers process them asynchronously. |
| Deterministic scoring | Containerized workers compute versioned factors; the API applies a bounded factor policy to retrieved eligible candidates. |
| Recommendations | Deterministic catalog, co-view, co-purchase, popularity and history rules only. |
| Deployment | OCI images and standard Kubernetes/Helm on AKS initially; Bicep provisions supported Azure dependencies. |

**Approved POC exception:** the [Cosmos Search backlog](docs/architecture/cosmos-search-poc-backlog.md)
uses a dedicated Cosmos container for keyword/BM25 retrieval instead of
OpenSearch, serving the existing Search contract over synthetic data. It uses
Python 3.11+ / FastAPI and Entra Cosmos access. An optional vector/hybrid
experiment is separately gated and not enabled or implemented in the baseline.
The exception does not change the broader platform's service choices.

Do not introduce Azure AI Search, Azure Machine Learning, Microsoft Foundry,
Azure OpenAI, Fabric, embeddings, semantic/vector retrieval, model inference,
generated conversation or learned ranking/recommendations. Historical research
and designs describing those services are not the target architecture.
**Approved offline image exception:** MAI may generate original synthetic catalogue
assets using an existing, explicitly approved deployment. The current expansion
targets MAI-Image-2.6-Flash with a read-only verified 6 RPM allowance. This is not
authorization for uncapped model calls: cost/quota preflight, capped pilot approval,
visual review and separately approved larger batches are required. No inference is
introduced into Search, ranking or the serving application. The POC experiment
above and this offline asset workflow are narrowly scoped exceptions.

Re-rank only eligible retrieved candidates, preserving filters and explicit
sorts. Start with one bounded result page. Hydrate authoritative product state
from Cosmos, reject stale/incompatible factors and clear expired projection
fields explicitly. Search failures are errors; optional factor failures
preserve OpenSearch order with explicit diagnostics.

Measure event-to-Cosmos, aggregation and Cosmos-to-OpenSearch visibility
separately. No latency or freshness target is a measured platform guarantee.

## Contracts and references

Read only the documents relevant to the work:

| Reference | Use |
|---|---|
| [API review and mappings](docs/api/README.md) | Draft limitations, authentication decisions, and event normalization. |
| [Search OpenAPI](docs/api/search.openapi.json) | `POST /v1/search` retrieval contract. |
| [Beacon OpenAPI](docs/api/beacon.openapi.json) | `POST /v2/events` capture contract. |
| [Platform design](docs/architecture/azure-commerce-search-platform-design.md) | **Current target:** Cosmos data design, portable services, keyword retrieval, deterministic ranking/recommendations, privacy and operations. |
| [Ranking/job design](docs/architecture/option-c-hybrid-detailed-design.md) | Historical AI/Fabric design; retain only as prior research. The current platform design overrides it. |
| [Ingestion design](docs/architecture/eventstream-ingestion-design.md) | Historical Fabric design; source isolation and revision concepts are carried into the current platform design. |
| [Event schema/scoring](docs/research/06-event-schema.md) | Internal envelope, score bounds, weights, and decay. |
| [Google-to-Azure research](docs/research/09-google-commerce-search-azure-equivalence.md) | Historical capability research; not the selected service architecture. |

The selected architecture above overrides conflicting historical research.
API drafts do not prove provider compatibility; internal design examples do
not override them. Verify concrete SDK/API details against current official docs.

## Safety and validation

Use synthetic data and one-retailer scope. Real shopper data, SaaS onboarding,
transactional shopping, and customer-service agents need separate approval/design.
Authenticate ingress, derive authorization server-side, prefer managed identity
and least privilege, and never commit credentials or sensitive worker outputs.


Keep unit tests offline; cloud mutations and paid calls need explicit scope
authorization. Run focused tests and configured checks for code changes;
check consistency and links for documentation changes. Mocks do not prove
cloud integration. Distinguish designed, implemented, and measured behavior.
