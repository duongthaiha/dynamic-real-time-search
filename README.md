# Dynamic real-time search

Azure commerce discovery using Azure AI Search, Microsoft Fabric Real-Time
Intelligence, and Azure Machine Learning. The target includes search/browse,
merchandising, recommendations, consented personalization, and read-only
conversational discovery.

## Repository contents

- [src/load-generator](src/load-generator/): Python catalog/image generators,
  offline unit tests, and a Search index definition for 1,000 synthetic products.
- [docs](docs/): research, architecture, API drafts, and operating instructions.
- [.github/copilot-instructions.md](.github/copilot-instructions.md): agent working rules.

The APIs and end-to-end ranking pipeline are designed, not implemented.
No API service runtime/framework or platform-wide build is configured.

## Local commands

Run from the repository root using the Python environment for this repository:

```powershell
python src\load-generator\generate_catalog.py
python -m unittest discover -s src\load-generator -p "test_*.py"
```

Generation writes to `data\catalog\`. **Do not reseed a catalog containing
image-generation state**; use a separate output directory. See the
[catalog guide](docs/catalog-data.md) for options, data shape, indexing, and
image hosting. Optional MAI image generation consumes model quota.

## Architecture

These are selected design choices, not deployed-resource claims:

| Area | Approach |
|---|---|
| APIs | Separate Search/re-ranking and Beacon services on Azure Functions. |
| Retrieval | Azure AI Search; baseline queries must not apply trend boosting. |
| Ingestion | Separate behavior and external-trend Fabric Eventstream items/connections/raw tables, with shared Eventhouse curated features. |
| Deterministic scoring | Eventhouse/KQL -> scheduled score publication -> Search. |
| Job-based scoring | Activator Run Notebook or schedule -> Fabric notebook -> Azure ML job -> durable reconciliation -> validated publication. |
| State | Cosmos DB for NoSQL for versioned per-product live scores/expiry and separate durable run/publication control. |
| Deployment | Bicep for supported Azure resources; supported Fabric APIs or documented manual setup/export. |

Prove deterministic index-side scoring before learned models or live re-ranking.
Do not restore the Power Automate/webhook fast path or add a Function solely
to launch ML jobs. Container Apps, Redis, online inference, and semantic/vector
retrieval are alternatives requiring evidence, not defaults.

Re-rank only eligible retrieved candidates, preserving filters and explicit
sorts. Start with one bounded result page. Equal indexed/live snapshots add no
boost; expiry must clear indexed fields. Search failures are errors, while
optional live-store failures preserve Search order with explicit diagnostics.

The index-side experiment targets a 1-5 minute response; measure the full
notebook/job path separately. Neither is a measured platform guarantee.

## Contracts and references

Read only the documents relevant to the work:

| Reference | Use |
|---|---|
| [API review and mappings](docs/api/README.md) | Draft limitations, authentication decisions, and event normalization. |
| [Search OpenAPI](docs/api/search.openapi.json) | `POST /v1/search` retrieval contract. |
| [Beacon OpenAPI](docs/api/beacon.openapi.json) | `POST /v2/events` capture contract. |
| [Platform design](docs/architecture/azure-commerce-search-platform-design.md) | Catalog, merchant controls, learning, privacy, and conversation. |
| [Ranking/job design](docs/architecture/option-c-hybrid-detailed-design.md) | Scoring, job lifecycle, publication, re-ranking, and failure tests. |
| [Ingestion design](docs/architecture/eventstream-ingestion-design.md) | Source isolation, revisions/retractions, readiness, and replay. |
| [Event schema/scoring](docs/research/06-event-schema.md) | Internal envelope, score bounds, weights, and decay. |
| [Google-to-Azure research](docs/research/09-google-commerce-search-azure-equivalence.md) | Capability evidence, gaps, and official sources. |

The selected architecture above overrides conflicting historical research.
API drafts do not prove provider compatibility; internal design examples do
not override them. Verify concrete SDK/API details against current official docs.

## Safety and validation

Use synthetic data and one-retailer scope. Real shopper data, SaaS onboarding,
transactional shopping, and customer-service agents need separate approval/design.
Authenticate ingress, derive authorization server-side, prefer managed identity
and least privilege, and never commit credentials or sensitive notebook outputs.


Keep unit tests offline; cloud mutations and paid calls need explicit scope
authorization. Run focused tests and configured checks for code changes;
check consistency and links for documentation changes. Mocks do not prove
cloud integration. Distinguish designed, implemented, and measured behavior.
