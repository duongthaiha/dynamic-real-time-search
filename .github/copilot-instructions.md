# Copilot instructions

## Direction and source of truth

Build the Azure commerce discovery platform one tested increment at a time.
Research is sufficient to start implementation. The ranking POC is Stage A,
not the final scope; recommendations, personalization, and read-only
conversation are later planned stages.

[README](../README.md) owns current status, the next increment, delivery order,
and selected architecture. Its explicit decisions override research/proposals.
Before editing, read it and only the references relevant to the task:

| Work | Required reference |
|---|---|
| Platform capabilities and acceptance | [Platform design](../docs/architecture/azure-commerce-search-platform-design.md) |
| Search/Beacon APIs | [Contract review and mappings](../docs/api/README.md), [Search](../docs/api/search.openapi.json), [Beacon](../docs/api/beacon.openapi.json) |
| Catalog and existing tooling | [Catalog guide](../docs/catalog-data.md) |
| Events and features | [Ingestion design](../docs/architecture/eventstream-ingestion-design.md), [Event schema/scoring](../docs/research/06-event-schema.md) |
| Ranking, ML jobs, and publication | [Option C detailed design](../docs/architecture/option-c-hybrid-detailed-design.md) |

Apply the relevant design's invariants and failure/acceptance tests; this file
does not replace them. Internal API examples do not override public contracts.

## Implementation workflow

- Implement the requested capability; for "continue implementation", use the
  README's next increment. Review/planning requests remain review/planning.
- Define the increment's contract, dependencies, non-goals, and acceptance
  checks. Resolve blocking behavior, runtime, or authorization decisions first.
- Inspect existing code and reuse its patterns. Python catalog/image tools,
  unit tests, and a Search index definition already exist. Choose/document
  service runtime and SDK versions when scaffolding, then follow manifests.
- Create only what the increment needs in the README's layout. Deliver working
  behavior, not a full-stack scaffold or success-shaped placeholder responses.
- Verify concrete API/SDK/region/preview questions against current official
  documentation. Record necessary deviations; do not restart broad research.
- Preserve unrelated work. On completion, update directly affected docs and
  README status, evidence, and next increment. Do not declare a phase complete
  before its exit gate or advance through unrequested stages.

## Architecture boundaries

- Follow Stage A order: foundations, ingestion/aggregation, deterministic
  index-side MVP, Azure ML jobs, live-store re-ranking, then demonstration.
  Prove the deterministic baseline before learned models or the full hybrid.
- Defaults: Azure Functions, Azure AI Search, Cosmos DB for NoSQL, and Bicep
  for supported Azure resources. Fabric setup uses supported APIs/manual steps.
  Container Apps, Redis, extra brokers, and online inference are not defaults.
- Keep behavior and external trends in separate Fabric Eventstream items,
  connections, and raw/rejection tables; share curated features and scoring.
- Use Activator Run Notebook or a schedule -> Fabric orchestration notebook ->
  Azure ML job -> durable reconciliation -> validated publication. Do not add
  Power Automate/webhooks or a Function solely to launch jobs.
- Start with one retailer and synthetic data. Real shopper data, SaaS
  onboarding, transactional shopping, and customer-service agents need separate
  approval/design. No social scraping; use synthetic or approved adapters.

## Non-negotiable correctness

- **Contracts:** keep Search and Beacon separate. Draft OpenAPI behavior is not
  verified provider compatibility. Preserve public camelCase events, normalize
  to the internal envelope, and keep event/search/attribution/order IDs distinct.
- **Events:** validate payloads, UTC times, ranges, and product IDs. Deduplicate
  before aggregation/purchase expansion; define late/removal semantics. Resolve
  external revisions/retractions and source readiness before freezing features.
- **Scores:** use one deterministic `[0, 100]` definition, initial weights
  `1:2:3`, and `alpha=0.5`. Preserve compound attributes as AND conditions.
  Test normalization/decay with seeded scenarios and an injectable clock.
- **Jobs:** coalesce scope/window/version triggers with cooldown/concurrency
  limits, never one job per event. Use immutable, identity-readable snapshots
  and a durable submission ledger. Reconcile uncertain submissions and terminal
  failures/cancellations/timeouts; submission is not publication success.
- **Publication:** validate keys, finite bounds, freshness, and versions.
  Order writes by feature-window/correction/version, not job completion.
  Prevent stale writes with store concurrency controls/coordinated publication.
  Retry Search/live-store outcomes independently without rerunning scoring.
- **Index updates:** use `merge` for score-only writes; inspect per-document
  results and retry transient failures within batch limits. Coordinate catalog
  writes; clear expired boosts explicitly. TTL does not reset indexed fields.
- **Serving:** baseline has no trend boost. Re-rank only eligible retrieved
  candidates, preserving filters and explicit sorts. Compare live state with
  indexed values returned by Search; equal snapshots add no boost. Use a capped
  delta, not raw-score addition; reject expired/incompatible state. Optional
  store outages preserve Search order with diagnostics; Search failures are errors.
  Bound candidates, batch reads, and start with one page.
- **Commerce:** price/stock/size constraints must match the same variant.
  Search is not authoritative checkout state. Version, validate, preview,
  approve, audit, and support rollback of merchant policies.
- **Later stages:** require task-specific evaluation before model promotion,
  actual exposure labels, and consent/deletion controls before personalization.
  Conversation uses scoped read-only tools and validates product facts; it
  cannot bypass eligibility or authorization. Deterministic search stays usable.

## Security and validation

- Authenticate ingress and derive retailer/collection authority server-side.
  Beacon's `security: []` is not deployment authorization. Prefer Entra,
  managed identity, and least privilege; verify support for each integration.
- Never commit/log secrets, personal data, or sensitive notebook outputs.
  Scope artifacts, caches, and telemetry; never share personalized responses
  or another visitor's attribution token.
- Validate configuration at startup; use timeouts, bounded retries, explicit
  errors, and correlation/version/stage telemetry. Never fabricate integration
  success or silently swallow failures.
- Keep unit tests offline. Use existing tooling and focused tests plus configured
  build/type-check/lint commands. Docs-only changes need consistency/link checks,
  not application builds. Maintain verified run/test/setup instructions.
- Cloud mutations and paid calls require explicit scope authorization. Gate
  integration tests with configuration; mocks do not prove Azure/Fabric behavior.
- Distinguish planned, implemented, and measured results. Apply the referenced
  acceptance scenarios, including expiry, duplicates, stale/partial publication,
  and outages. Measure end-to-end and stage latency with sample counts; notebook
  jobs are not a seconds-level path. Do not claim parity, uplift, or savings
  without evidence covering the full workload.
