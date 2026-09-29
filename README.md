# Dynamic real-time search

An **Azure commerce discovery platform**, built incrementally toward product
search/browse, merchandising, recommendations, consented personalization, and
read-only conversational discovery.

Research and initial design are complete enough to implement. The event-driven
ranking POC is **Stage A**, not the final scope. Start with one retailer and
synthetic data; real-shopper experiments, SaaS onboarding, transactional shopping,
and customer-service agents require separate approval/design. No social scraping.

This README owns current status, delivery order, and selected architecture.
Its explicit decisions override historical research; linked designs provide
detailed contracts, failure handling, and acceptance tests. Planned capabilities
are not claims of implemented Google AI Commerce Search parity.

## Current implementation status

| Area | Status |
|---|---|
| Research and architecture | Capability comparison, platform design, and detailed ingestion/ranking designs documented. |
| Catalog foundation | Python catalog/image generators, offline tests, and a Search index definition exist for 1,000 synthetic products. |
| Search and Beacon | Draft contracts only; services and API runtime/framework are not implemented/selected. |
| Ranking pipeline and later stages | Designed, not implemented or demonstrated end to end. |

**Current milestone:** Stage A / Phase 0 foundations.
**Next:** [A0.1 - baseline Search API](#next-increment-a01---baseline-search-api).

### Next increment: A0.1 - baseline Search API

Deliver one non-trend Search path using the existing catalog/index:

1. Select runtime/SDK/test tooling, the Search contract subset, and scope authorization.
2. Build the Azure Functions handler and Search adapter with query/refinement
   preservation, bounded candidates, no baseline trend boost, and explicit errors.
3. Test requests, refinements, authorization, configuration, profile selection,
   and upstream failures offline; verify setup/run commands.
4. Define a gated smoke test against an explicitly authorized, seeded Search index.

**Exit:** a locally runnable handler with passing contract/error tests and
verified setup/run instructions. Record cloud evidence separately; this does
not complete Phase 0's Azure/Fabric/ML gates. Beacon, ingestion, trend scoring,
ML jobs, live re-ranking, recommendations, and conversation are not in A0.1.

## Existing local tooling

From the repository root, generate the catalog and run its offline tests:

```powershell
python src\load-generator\generate_catalog.py
python -m unittest discover -s src\load-generator -p "test_*.py"
```

Generation writes to `data\catalog\`. **Do not reseed a catalog containing
image-generation state**; use a separate output directory.
See the [catalog guide](docs/catalog-data.md) for options, product/variant shape,
index batches, and image hosting. The optional
[MAI photograph workflow](docs/catalog-data.md#mai-image-26-photographs)
uses an existing deployment and consumes model quota.

These commands cover catalog tooling only. Service install/run/deploy commands
will be added when implemented and verified; there is no platform-wide build yet.

## Architecture

The [platform design](docs/architecture/azure-commerce-search-platform-design.md)
defines the full target. Stage A uses these selected defaults:

| Area | Selected approach |
|---|---|
| Serving | Azure Functions for separate Search/re-ranking and Beacon APIs; Azure AI Search for retrieval. |
| Ingestion | Separate behavior and external-trend Fabric Eventstream items, source connections, and raw/rejection tables; shared Eventhouse curated features. |
| Phase 2 scoring | Eventhouse/KQL deterministic baseline -> scheduled score publisher -> Search. Prove this before ML or live re-ranking. |
| Phase 3 scoring | Activator **Run Notebook** or schedule -> Fabric orchestration notebook -> Azure ML command/pipeline job -> durable reconciliation -> validated publication. |
| Live/control state | Cosmos DB for NoSQL: per-product partitions for versioned live scores with expiry, plus separate durable run/publication control. |
| Deployment | Bicep for supported Azure resources; supported Fabric APIs or documented manual setup/export. |

Behavior starts with periodic runs; external hints/retractions feed Activator
explicitly. Validate source readiness before freezing features. Periodic runs
also drive decay/expiry without new input.

Use score-only `merge` updates and explicit indexed expiry resets. Re-rank only
eligible retrieved candidates with a capped delta against returned indexed state;
equal snapshots add no boost. Preserve filters/sorts, start with 100-200 candidates
and one page, and keep Search errors explicit. Optional-store outages preserve
Search order with diagnostics. The [detailed ranking design](docs/architecture/option-c-hybrid-detailed-design.md)
specifies durable job recovery, version-ordered publication, retries, and tests.

Do not restore the Power Automate/webhook fast path or add a Function solely
to launch ML jobs. Container Apps, Redis, extra brokers, online inference, and
semantic/vector retrieval are separately evaluated alternatives, not defaults.
Notebook/job freshness is not a seconds-level inference guarantee.

### Cloud readiness

Confirm Azure/Fabric capacity, permissions, regions/quotas, network access,
budget, and teardown ownership. Verify Activator availability, notebook-to-ML,
job-to-storage, and publisher-to-Search/Cosmos access separately. Prefer Entra,
managed identity, and least privilege; protect secrets and authenticate ingress
with server-derived scope. Local work does not authorize cloud mutations or paid calls.

## Service API contracts

| Service | Endpoint | Draft |
|---|---|---|
| Search | `POST /v1/search` | [Search OpenAPI](docs/api/search.openapi.json) |
| Beacon | `POST /v2/events` | [Beacon OpenAPI](docs/api/beacon.openapi.json) |

The [API review and mappings](docs/api/README.md) explain the incomplete Postman
source, proposed responses, authentication decisions, and public camelCase-to-
internal event normalization. These drafts do not prove provider compatibility;
Beacon's `security: []` is not approval for unauthenticated deployment.

## Build roadmap

| Stage | Delivery goal |
|---|---|
| A - Ranking foundation | Complete POC phases 0-4 below. |
| B - Commerce search | Variant-correct catalog, browse/sort/facets, suggestions, merchant approval/rollback, and snapshot paging. |
| C - Learning/recommendations | Exposure/outcome data, transparent baselines, then evaluated learned ranking and recommendation tasks. |
| D - Personalization/conversation | Consented profiles and grounded, authorized, read-only discovery. |
| E - Production qualification | Capacity, recovery, operational ownership, security, cost, and SLO evidence. |

Follow the [platform acceptance gates](docs/architecture/azure-commerce-search-platform-design.md#12-phased-delivery-and-acceptance).
Security, correctness, and observability apply at every stage, not only E.

### Stage A phases

These phases supersede the historical research POC plan.

| Phase | Deliverables | Exit gate |
|---|---|---|
| 0 - Foundations | Runtime/configuration, Azure/Fabric/ML setup and environment, catalog/index seed | Baseline queries work; notebook-to-ML permissions and feature/output access verified; setup/cleanup reproducible. |
| 1 - Ingest/aggregate | Event validation, seeded scenarios, Eventstream routing, KQL and scoring tests | Known events yield expected deduplicated scores, including compound attributes. |
| 2 - Index-side MVP | Scoring profile, scheduled writer, partial-failure recovery, expiry/reset | Relevant SKU moves within the 1-5 minute target and settles after expiry; actual cadence and misses recorded. |
| 3 - ML/hybrid | Notebook/job lifecycle, durable ledger, validated publication, live state and re-ranking | Duplicate/uncertain runs reconciled; invalid/stale outputs cannot publish; partial writes recover; equal snapshots add no boost. |
| 4 - Evidence | Three-mode comparison, dashboard, traces, latency/cost report | Repeatable before/during/after results with measured budgets and limitations. |

### Implementation layout

Only catalog tooling currently exists. Create other areas when an increment needs them:

```text
src\load-generator\      Existing catalog/image tooling; event scenarios to add
src\reranking-api\       Planned Search handler and bounded live adjustment
src\beacon-api\          Planned event capture/normalization
src\signal-writer\       Planned validated score publication
src\ml\                 Planned scoring/training scripts and job definitions
src\fabric\             Planned eventstream, eventhouse, and notebooks artifacts
infra\                  Planned Azure Bicep and deployment parameters
tests\                  Planned shared contract/ranking/integration tests
```

### How we deliver

Deliver one bounded increment with acceptance tests and verified commands.
Update status, evidence, blockers, and the next increment before advancing.
Cloud tests require explicit scope/configuration; mocks are not deployment evidence.
Offline increments can finish with cloud gates open; phases cannot.
See [Copilot instructions](.github/copilot-instructions.md) for implementation rules.

## Demonstration and acceptance

For the same seed, query, filters, and result count, compare **baseline**
(no trend profile), **index-side** (indexed trend boost), and **hybrid**
(capped incremental live adjustment) before/during/after SKU and compound
attribute spikes. Keep candidate eligibility authoritative.

Apply the linked designs' failure tests: invalid/duplicate/late/retracted events,
score decay/clearing, stale/partial writes, equal snapshots, ties, outages,
uncertain/failed/cancelled/timed-out jobs, invalid artifacts, and publication recovery.

| Measurement | Target or rule; not a measured guarantee |
|---|---|
| Event emission -> Eventhouse | < 5 seconds |
| Event arrival -> rolling aggregate | < 30 seconds |
| Deterministic sync -> visible Search update | Approximately 1-2 minutes; validate scheduling feasibility. |
| Event injection -> index-side rank change | 1-5 minutes; report misses. |
| Event injection -> ML/hybrid rank change | Measure action delivery, notebook startup, queue/provisioning, execution, reconciliation, publication, and index propagation separately. |
| Added live-read/re-sort API work | < 50 ms |

Record repeated-run sample counts, p50/p95, failures, expiry, candidate limits,
and full workload costs across Search, Fabric, ML, Cosmos, APIs, storage, and
telemetry. Do not silently widen targets or infer revenue lift from synthetic tests.

## Documentation

| Reference | Purpose |
|---|---|
| [Google-to-Azure research](docs/research/09-google-commerce-search-azure-equivalence.md) | Capability comparison, native/custom boundaries, gaps, and official sources. |
| [Commerce platform design](docs/architecture/azure-commerce-search-platform-design.md) | Catalog/merchant controls, learning, privacy, conversation, operations, and acceptance. |
| [Option C detailed design](docs/architecture/option-c-hybrid-detailed-design.md) | Scoring, job lifecycle, publication, live re-ranking, and failure scenarios. |
| [Two-stream ingestion](docs/architecture/eventstream-ingestion-design.md) | Source contracts, revisions/retractions, readiness, and replay. |
| [Event schema/scoring](docs/research/06-event-schema.md) | Internal envelope, initial `[0, 100]` score, `1:2:3` weights, and `alpha=0.5`. |
| [Research archive](docs/research/) | Historical problem, primers, architecture options, POC plan, and forecasting. |

Verify concrete platform/API/SDK/region details against current official
documentation during implementation. Distinguish proposed, implemented, and
measured behavior; historical timings and simplified platform claims are not guarantees.
