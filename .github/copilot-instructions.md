# Copilot instructions

## Project and source of truth

This repository is a POC for event-driven product re-ranking with Azure AI
Search and Microsoft Fabric Real-Time Intelligence.

Read [README](../README.md) and the relevant research, design, and contracts
before changing code:

- [Problem and non-goals](../docs/research/01-problem-statement.md)
- [Search mechanisms](../docs/research/02-ai-search-primer.md)
- [Fabric components](../docs/research/03-fabric-primer.md)
- [Architecture trade-offs](../docs/research/04-architecture-options.md)
- [Original hybrid recommendation](../docs/research/05-recommended-architecture.md)
- [Option C detailed design](../docs/architecture/option-c-hybrid-detailed-design.md)
- [Two-stream ingestion design](../docs/architecture/eventstream-ingestion-design.md)
- [Event contract and scoring](../docs/research/06-event-schema.md)
- [Implementation phases](../docs/research/07-poc-plan.md)
- [Azure ML forecasting](../docs/research/08-azure-ml-forecasting.md)
- [Public API review and mapping](../docs/api/README.md)
- [Search contract](../docs/api/search.openapi.json)
- [Beacon contract](../docs/api/beacon.openapi.json)

The README's explicit architecture and implementation choices take
precedence over conflicting research and the proposed Option C detailed
design. The revised Option C design documents the selected Run Notebook ->
Azure ML job -> validated publication lifecycle, plus compatible serving
guardrails, observability, failure handling, and test scenarios. Do not
restore the original research's Power Automate/webhook fast path or its
seconds-level targets. Container Apps and Azure Managed Redis remain
measurement-driven alternatives, not defaults. Internal API examples in the
design do not supersede the public OpenAPI drafts.

Verify platform details against current official Microsoft documentation
and the selected SDK/API versions. Record a necessary deviation and its
evidence; do not silently replace the design or treat proposed defaults,
formulas, and SLOs as implemented or measured guarantees.

## Scope and implementation sequence

- Implement Phase 0 foundations, then ingestion/aggregation, index-side MVP,
  Azure ML job-based score generation, live-store re-ranking, and
  demonstration/evaluation. Do not build the entire hybrid stack before
  the index-side path is proven.
- Proposed defaults are Azure Functions, Cosmos DB for NoSQL, Bicep for
  supported Azure resources, and Fabric Eventstream/Eventhouse/KQL.
  Activator's native Run Notebook action or a periodic schedule invokes a
  Fabric orchestration notebook, which submits Azure ML command/pipeline
  jobs. Do not add Power Automate or a Function solely to launch those jobs.
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

## Notebook and Azure ML job lifecycle

- Activator targets a Fabric notebook, not an interactive Azure ML notebook.
  Validate action availability and permissions in the target tenant.
- Prove the deterministic baseline through the index-side MVP first, then
  run the same versioned baseline in an Azure ML job before introducing a
  learned model. Package automated scoring as scripts/components with
  pinned environments; do not depend on interactive notebook state.
- Coalesce triggers by customer/collection, feature window, and scoring
  version. Apply cooldown and concurrency limits; never submit one notebook
  or job per shopper event.
- Prepare an immutable feature snapshot with its watermark and schema
  version. Verify that the job identity can read it; do not assume automatic
  access to Eventhouse or OneLake.
- Persist submission keys and Azure ML job IDs in a durable run ledger.
  Reconcile uncertain submissions before retrying. Submission success is
  not scoring or publication success.
- Track terminal success, failure, cancellation, and timeout through durable
  scheduled reconciliation, not a notebook session kept alive indefinitely.
  Surface failures and retain previous valid scores only until expiry.
- Validate successful output artifacts for product keys, finite score
  bounds, freshness, and scoring/model version before publication. Track
  Search and live-store outcomes independently and retry partial publication
  without recomputing the job.
- Order state by feature-window/version semantics, not job completion time:
  an older window must not overwrite a newer one just because it finishes
  later. Scheduled and event-triggered runs use the same scoring policy.
- Notebook startup, compute provisioning, job queues, and publication bound
  signal freshness. Fast query-time reads do not make this a seconds-level
  inference path. An Azure ML online endpoint is an optional, separately
  designed and validated extension, not part of the default job lifecycle.

## Contracts and scoring invariants

- Use separate behavior and external-trend Eventstream items, source
  connections, and raw/rejection tables. Share curated features and the
  notebook/ML lifecycle, not unrestricted source credentials.
- External observations come through a synthetic or approved provider
  adapter, not a presumed native TikTok connector or scraper. Resolve the
  latest signal revision before expiry/eligibility checks; preserve
  retractions and never count cumulative social snapshots as shopper events.
- Validate per-source readiness and health before freezing features. Idle
  external input is not an outage; missing behavior is not zero activity.
  New input in an existing window needs a correction/input-set version.
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
  state using the selected store's conditional-write/concurrency mechanism;
  do not rely on unconditional last-writer-wins updates. Live state is
  reconstructable, not the only durable record.
- Compare live state with indexed values actually returned with candidates,
  not a presumed last successful sync. Index acceptance is not visibility.
- Apply only a capped incremental adjustment. Equal live/indexed snapshots
  must add no boost. Raw trend scores and Search scores are not comparable:
  document and test the blend, cap, negative deltas, and deterministic ties.
  Reject expired/non-finite state and skip live adjustments for incompatible
  scoring/model versions with explicit diagnostics. Do not assume a
  rank-normalized delta exactly reverses Search's scoring-profile boost.
- Preserve Search's order with explicit degraded-mode metadata and telemetry
  if the live store is unavailable or stale. Surface Search failures as
  errors, not successful empty results.
- Batch live-state reads. Keep candidate count bounded and start with one
  result page; do not claim globally correct re-ranking or stable pagination.
  If pagination is requested, use the detailed design's fixed ranking
  snapshot and opaque signed cursor approach, bind it to query/filters and
  caller scope, and define expiry and current-eligibility checks.
- If semantic/vector search is added, verify score selection and candidate
  limits for that mode. Semantic scoring profiles can be applied after
  semantic ranking; do not assume `@search.score` is always the final score.

## Fabric, security, and observability

- Validate actual Fabric scheduling/startup latency and action delivery;
  the research cadences are targets, not guaranteed supported schedules.
- Wire the actual input needed by Activator rules. Do not assume that an
  Eventhouse aggregate automatically feeds a rule or that a direct webhook
  action exists. Use the selected Run Notebook route; begin with explicit
  synthetic external-trend events and verify feature-window readiness before
  submitting the scoring job.
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
  versions, feature snapshots, Azure ML job IDs/status, publication outcomes,
  indexing results, rank changes, and degradation. Measure queue/startup,
  execution, publication, and query latency separately. Avoid logging
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
  Include duplicate/uncertain submissions, failed/cancelled/timed-out jobs,
  out-of-order completions, invalid artifacts, version mismatches, and
  publication recovery without rerunning scoring.
- Prove the demo with before/during/after results for the same query and
  filters in all three modes, covering both SKU and attribute spikes.
  Record actual end-to-end latency, p50/p95 with sample counts, expiry,
  error behavior, costs, and any missed targets from the README.
- Run focused tests plus the configured build/type-check/linter for code
  changes. For documentation-only changes, check consistency and local
  links; no application build is required.
- Keep changes scoped. Preserve unrelated work. Update directly affected
  docs and distinguish planned, implemented, and measured behavior.
