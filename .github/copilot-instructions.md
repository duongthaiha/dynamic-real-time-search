# Copilot instructions

## Context

Build an Azure commerce discovery platform, not just a trend-ranking demo.
Read [README](../README.md) for repository contents, commands, and selected
architecture, then the linked designs/contracts relevant to the task.
README decisions override historical research. Detailed designs own behavioral
invariants and failure tests; API examples do not override public contracts.

## Working rules

- Implement the user's requested scope; review/planning requests are not
  permission to build unrelated features. Clarify blocking ambiguity.
- Inspect existing code and reuse its patterns. Catalog/image tooling and tests
  already exist. Document service runtime/SDK choices when introducing services;
  thereafter follow actual manifests and configured tooling.
- Make focused, complete changes with tests and verified usage instructions.
  Preserve unrelated work; avoid speculative scaffolding and placeholder success.
- Use current official docs for concrete API/version questions. Record necessary
  deviations from the design rather than silently changing architecture.
- Update directly affected docs when behavior or commands change. Keep task
  planning and progress tracking out of README and these instructions.

## Correctness

- Keep Search retrieval and Beacon capture separate. Preserve public camelCase events and normalize them into the internal envelope; keep correlation/attribution IDs distinct.
- Validate payloads, UTC times, ranges, and product IDs. Deduplicate before aggregation/purchase expansion. Resolve external revisions/retractions andsource readiness before freezing features; no social scraping.
- Use `merge` for score-only updates, inspect per-document results, and retrypartial publication without rerunning scoring. Explicitly clear expired
  indexed boosts; TTL does not reset Search fields.
- Re-rank only retrieved eligible candidates. Preserve filters/sorts; same-variant price/size/stock eligibility is required. Compare live state to indexed values
  returned by Search; equal snapshots add no boost. Reject expired/incompatible
  state, cap adjustments, and preserve Search order on optional-store failure.
  Surface Search failures as errors, not successful empty results.
- Require evaluation before model promotion and consent/deletion controls before
  personalization. Conversation uses scoped read-only tools and validated product
  facts; it cannot bypass authorization or eligibility.

## Security and verification

- Prefer Entra/managed identity and least 
- Never commit/log secrets, personal data, or sensitive notebook outputs.
  Scope caches, artifacts, and telemetry; never share personalized responses.
- Use timeouts, bounded retries, explicit errors, and correlation/version/timing
  telemetry. Never swallow failures or fabricate integration success.
- Keep unit tests offline; use focused tests plus configured build/type/lint
  checks. For docs-only changes, check consistency and local links.
- Use synthetic data. Cloud mutations, paid calls, and real shopper data require explicit authorization
- Report what was changed, verified, and remains unverified. Apply the relevant design's acceptance tests; do not claim parity, uplift, or latency guarantees from synthetic tests or job submission alone.
