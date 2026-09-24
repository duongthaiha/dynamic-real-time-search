# Copilot instructions

## Project and source of truth

This repository is a POC for event-driven product re-ranking with Azure AI
Search and Microsoft Fabric Real-Time Intelligence.

Read [README](../README.md) and the relevant research before changing code:

- [Problem and non-goals](../docs/01-problem-statement.md)
- [Search mechanisms](../docs/02-ai-search-primer.md)
- [Fabric components](../docs/03-fabric-primer.md)
- [Architecture trade-offs](../docs/04-architecture-options.md)
- [Hybrid design](../docs/05-recommended-architecture.md)
- [Event contract and scoring](../docs/06-event-schema.md)
- [Implementation phases](../docs/07-poc-plan.md)
- [Azure ML forecasting](../docs/08-azure-ml-forecasting.md)
- [Public API review and mapping](../docs/api/README.md)
- [Search contract](../docs/api/search.openapi.json)
- [Beacon contract](../docs/api/beacon.openapi.json)

Use the README's explicit implementation clarifications when research
examples are ambiguous. Verify platform details against current official
Microsoft documentation and the selected SDK/API versions. Record a
necessary deviation and its evidence; do not silently replace the design.

## Scope and implementation sequence

- Implement Phase 0 foundations, then ingestion/aggregation, index-side MVP,
  fast path, and demonstration/evaluation. Do not build the entire hybrid
  stack before the index-side path is proven.
- Proposed defaults are Azure Functions, Cosmos DB for NoSQL, Bicep for
  supported Azure resources, and Fabric Eventstream/Eventhouse/KQL with a
  notebook/pipeline synchronization experiment.
- No application language, runtime, dependency manager, or test framework
  exists yet. Choose and document these when scaffolding; thereafter follow
  the actual manifests and conventions rather than introducing another stack.
- Use the planned layout in the README, creating only directories needed
  for the current milestone. Keep event generation, signal delivery,
  ranking, and Fabric artifacts separate; share contracts/scoring logic
  where useful, without speculative frameworks.
- Keep all data synthetic. Do not add personalization, social scraping,
  agents, LLMs, embeddings, or semantic search unless the task requires it.
- Do not provision billable resources, change shared cloud configuration,
  or delete resources merely to edit documentation or run unit tests.
  Deploy only within an explicitly authorized scope.

## Contracts and scoring invariants

- Keep Search retrieval and Beacon event capture as separate service
  contracts. The OpenAPI drafts reconstruct an incomplete Postman export;
  responses and inferred validation rules are proposals, not verified
  provider behavior. Confirm them before implementing provider compatibility.
- Preserve public Beacon camelCase event names and normalize them into the
  research's internal event envelope. Keep search IDs, attribution tokens,
  cart IDs, order IDs, and event IDs distinct. See the API mapping notes.
- Beacon's `security: []` reflects the supplied examples, not authorization
  to deploy public unauthenticated ingestion. Resolve ingress trust first.
- Preserve the research event names and envelope. Formalize validation,
  schema versioning, and correlation metadata before adding producers.
- Validate event-type-specific payloads, UTC timestamps, numeric ranges,
  and known product IDs. Treat external metadata as untrusted input.
- Deduplicate by event ID before aggregation or purchase-item expansion.
  Define late-event handling, event-versus-quantity counts, and
  `remove_from_bag` semantics explicitly. Do not invent product attribution
  for query-only search events.
- Preserve conjunctions in attribute trends: blue jackets means blue AND
  jackets, not either attribute independently. Use a documented catalog
  snapshot and handle unknown attributes/products explicitly.
- Maintain one canonical score definition in `[0, 100]`. Start with the
  research's `1:2:3` behavioral weights and `alpha=0.5`; make normalization,
  confidence weighting, empty windows, and decay deterministic and tested.
- Use an injectable clock and seeded scenarios. Ingestion-triggered
  aggregates alone do not expire trends when no new events arrive.

## Search and live-state invariants

- Keep Search relevance and filters authoritative. Re-rank only eligible
  retrieved candidates; never insert a trending product outside that set.
- Keep baseline, index-only, and hybrid modes comparable. Baseline must not
  accidentally apply a default trend scoring profile.
- Use stable document keys and `merge` for score-only writes to existing
  catalog documents. Allow `mergeOrUpload` only for deliberate complete
  product upserts. Respect document-count and byte-size batch limits,
  inspect per-document results, and retry only transient failures with
  bounded backoff.
- Update active products and clear previously boosted products when trends
  expire. Cache TTL does not reset Search fields. Do not refresh
  `lastTrendingAt` merely because a synchronization job ran.
- Store calculation time, version, and expiry alongside live scores.
  Prevent stale scheduled/duplicate/out-of-order writes from replacing newer
  state; do not rely on unconditional last-writer-wins updates.
- Compare live state with indexed values actually returned with candidates,
  not a presumed last successful sync. Index acceptance is not visibility.
- Apply only a capped incremental adjustment. Equal live/indexed snapshots
  must add no boost. Raw trend scores and Search scores are not comparable:
  document and test the blend, cap, negative deltas, and deterministic ties.
- Preserve Search's order with explicit degraded-mode metadata and telemetry
  if the live store is unavailable or stale. Surface Search failures as
  errors, not successful empty results.
- Batch live-state reads. Keep candidate count bounded and start with one
  result page; do not claim globally correct re-ranking or stable pagination.
- If semantic/vector search is added, verify score selection and candidate
  limits for that mode. Semantic scoring profiles can be applied after
  semantic ranking; do not assume `@search.score` is always the final score.

## Fabric, security, and observability

- Validate actual Fabric scheduling/startup latency and action delivery;
  the research cadences are targets, not guaranteed supported schedules.
- Wire the actual input needed by Activator rules. Do not assume that an
  Eventhouse aggregate automatically feeds a rule or that a direct webhook
  action exists. Validate the Power Automate/custom-endpoint route.
- Use supported KQL constructs. Do not assume a materialized view can
  implement every join, rolling window, or clock-driven decay calculation.
- Separate Azure Bicep from supported Fabric APIs and manual setup/export
  steps. Do not invent connectors, resource types, or deployment support.
- Prefer Entra authentication, managed identity, and least-privilege roles.
  Verify Fabric identity support per integration; protect any required
  secrets in an approved secret store. Never commit credentials, connection
  strings, sensitive notebook outputs, or unsanitized exports.
- Validate configuration at startup. Use timeouts, bounded retries,
  authenticated ingress, and explicit failure reporting. Do not swallow
  exceptions or fabricate successful integration responses.
- Trace event/correlation IDs, UTC stage times, product IDs, signal
  versions, indexing results, rank changes, and degradation. Avoid logging
  secrets or personal data.

## Validation and documentation

- There are currently no build/test commands. Do not invent them. Once
  scaffolding exists, maintain verified install/build/test/run/seed/demo/
  teardown instructions in the README and use the actual project tooling.
- Keep unit tests offline. Gate cloud integration tests behind explicit
  configuration; mocks do not prove Fabric-to-Search behavior.
- Test schema rejection, duplicate and late events, purchase expansion,
  compound attribute matching, score bounds/decay, clearing indexed boosts,
  partial indexing failure/retry, stale-write prevention, equal-score
  no-double-boost behavior, ties, filter preservation, and store outages.
- Prove the demo with before/during/after results for the same query and
  filters in all three modes, covering both SKU and attribute spikes.
  Record actual end-to-end latency, p50/p95 with sample counts, expiry,
  error behavior, costs, and any missed targets from the README.
- Run focused tests plus the configured build/type-check/linter for code
  changes. For documentation-only changes, check consistency and local
  links; no application build is required.
- Keep changes scoped. Preserve unrelated work. Update directly affected
  docs and distinguish planned, implemented, and measured behavior.
