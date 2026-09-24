# POC implementation plan

## Phase 0 — Foundations (setup)

- Provision (Bicep, per repo convention): Azure AI Search service, a
  Fabric workspace + Eventhouse + Eventstream, Azure Cosmos DB (or Azure
  Cache for Redis) for the live signal store, an Azure Function App (or
  Container App) for the signal writer / re-ranking API, Application
  Insights for observability.
- Use **managed identity** for AI Search ↔ Function App and Function App ↔
  Cosmos DB/Redis wherever supported, per repo conventions.
- Load a small synthetic product catalog (50–200 SKUs across a few
  categories/colours/brands) into Azure AI Search with a baseline schema
  plus the new fields: `trendingScore` (double), `lastTrendingAt`
  (DateTimeOffset), `trendingTags` (Collection(Edm.String)).

## Phase 1 — Event ingestion + aggregation (Fabric)

- Create an Eventstream with two Custom App sources (or one, with an
  `eventType` discriminator): behavioral events and external trend events.
- Land raw events into an Eventhouse `RawEvents` table.
- Build KQL update policies / materialized views for
  `ProductSignals1Min/5Min` and `AttributeTrend5Min`.
- Build a KQL queryset implementing the `trendingScore` formula
  ([06-event-schema.md](06-event-schema.md)) as `ProductTrendingScore`.
- Write a small **load generator** (script) that simulates realistic
  shopper traffic plus periodic injected "spikes" (both product-level and
  attribute/colour-level) so the pipeline can be exercised end-to-end
  without a live storefront.

## Phase 2 — Index-side boosting (Option A path)

- Add a scoring profile to the AI Search index using freshness
  (`lastTrendingAt`), magnitude (`trendingScore`), and tag
  (`trendingTags`) functions.
- Build the scheduled Fabric notebook/pipeline that reads
  `ProductTrendingScore` for the "hot set" (recently active products) and
  calls `mergeOrUpload` against the AI Search index.
- Validate: run the load generator, confirm that a query with the scoring
  profile reorders results within the expected 1–2 minute window, and that
  results settle back down as the injected spike ages out.

## Phase 3 — Fast path (Option B path)

- Add an Activator rule on the Eventhouse stream for spike detection
  (e.g., product-level or attribute-level magnitude/confidence above a
  threshold, or a windowed count z-score).
- Wire the Activator action to call the signal-writer Function/Container
  App (via a webhook/Power Automate step), which writes the live score
  into Cosmos DB/Redis immediately.
- Build the re-ranking API: given a query, call AI Search for `top 100–200`
  candidates (scoring profile already applied), fetch live scores for
  those candidate productIds from the cache, apply the incremental
  blend described in [05-recommended-architecture.md](05-recommended-architecture.md#avoiding-double-boosting),
  return the final trimmed/re-sorted page.
- Validate: inject a sudden spike and confirm the re-ranking API reflects
  it within single-digit seconds, faster than the index-side path alone.

## Phase 4 — Demonstration & evaluation

- Build a small demo UI (or reuse Postman/curl scripts) showing
  side-by-side: (a) raw AI Search query, (b) AI Search + scoring profile
  only, (c) full hybrid via the re-ranking API — for the same query,
  before/during/after an injected spike.
- Add a lightweight Real-Time dashboard (Power BI or Fabric real-time
  dashboard) over the Eventhouse tables so a merchandiser persona can see
  "what's trending and why" alongside the search results changing.
- Capture measured latencies at each stage against the target budget in
  [05-recommended-architecture.md](05-recommended-architecture.md#latency-budget-target).

## Suggested repo layout for implementation (next step, not yet built)

```
aisearch-fabric-realtime-rerank/
  docs/                      <- this research (done)
  infra/                     <- Bicep: AI Search, Cosmos/Redis, Function App, Fabric workspace items (where supported)
  src/
    load-generator/          <- synthetic event producer (behavioral + external trend)
    signal-writer/            <- Azure Function: Activator webhook -> cache
    reranking-api/            <- Azure Function/Container App: candidate fetch + blend
    fabric/
      eventstream/            <- Eventstream definition export
      eventhouse/              <- KQL scripts: tables, update policies, querysets
      notebooks/               <- scheduled notebook: aggregate -> mergeOrUpload + cache
  README.md
```

## Open questions / risks to validate during the POC

- **Fabric-to-Azure auth**: confirm the cleanest way for a Fabric
  notebook/pipeline to call the Azure AI Search REST API and write to
  Cosmos DB/Redis using managed identity / workspace identity rather than
  static keys.
- **Cost of frequent `mergeOrUpload`**: measure actual RU/throughput cost
  of updating the "hot set" every 1–2 minutes at a representative catalog
  size, to size the production SKU tier.
- **Cache consistency window**: decide the TTL/decay strategy so a
  product's boost fades if the pipeline stops emitting updates (avoid
  "stuck trending" products, e.g. after a Fabric outage).
- **Attribute-to-product resolution**: for attribute-level external trends
  (colour/category), decide whether resolution happens in KQL (join
  against a catalog snapshot mirrored into Eventhouse) or via a live AI
  Search filter query from the notebook/API — affects freshness of the
  catalog mapping and cost.
- **Double-boosting governance**: formalize the incremental-blend rule
  (index-baked score vs. live cache score) with real numbers once
  Phase 2 and 3 are both running, rather than leaving it as a POC-time
  guess.
- **External signal source**: this POC simulates `external_trend` events;
  a real integration would need a legitimate, ToS-compliant data source
  (e.g., a licensed social-listening/trend API or an internal marketing
  feed) — evaluate options as a follow-up, out of scope for this POC.
- **Real-time thresholds vs. noise**: validate that Activator's spike
  rules don't false-trigger on normal traffic variance (e.g., a slow
  news day looking like a "drop" is not itself a signal); tune thresholds
  using the load generator's baseline traffic before adding spikes.
