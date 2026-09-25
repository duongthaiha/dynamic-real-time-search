# Problem statement

## Context

The customer runs an e-commerce storefront. Product discovery is powered by
**Azure AI Search**: a catalog of products (title, description, category,
price, images, attributes, maybe vector embeddings for semantic/hybrid
search) is indexed, and search queries are served with relevance ranking
(BM25 / vector similarity / semantic reranker) plus static **scoring
profiles** (e.g., boost by category or a fixed "popularity" field that's
recomputed in a nightly batch job).

## Pain point

Because the popularity/boost signals are recalculated in batch (nightly or
weekly), the search result order does not reflect **what is happening right
now**:

- A product suddenly trending because of a TikTok video or a celebrity
  sighting won't be boosted until the next batch run — by which time the
  moment may have passed.
- Real-time, first-party shopper behavior (a surge of "view product" /
  "add to bag" events for a specific SKU in the last few minutes) isn't
  reflected in ranking at all today.
- External, out-of-band signals (social virality, press mentions, colour/
  style trends) aren't captured or modeled anywhere in the current system.

## Goal

Build a POC that demonstrates **event-driven, near-real-time re-ranking** of
Azure AI Search results, fed by:

1. **First-party behavioral events** streamed from the e-commerce site/app:
   `search`, `view_product`, `add_to_bag`, `purchase`, `remove_from_bag`, etc.
2. **External/derived signals**: e.g., "product X is viral on TikTok" or
   "blue clothing is trending because of Celebrity Y" — modeled as events
   from a social-listening/trend-detection process that map back to
   products/attributes in the catalog (by SKU, tag, colour, category, brand).

The pipeline should continuously compute per-product (and per-attribute,
e.g. per-colour or per-category) "momentum" scores and make them available
to influence search ranking within **seconds to a few minutes**, not
overnight.

## Ingestion design: two separate Eventstreams

Treat the two signal families as independent ingestion pipelines:

1. **First-party behavior Eventstream:** receives normalized storefront and
   commerce-backend events through Beacon/trusted producers. It feeds
   deduplicated activity features such as views, bag additions, and purchases.
2. **External-trend Eventstream:** receives normalized observations from a
   synthetic or approved external adapter, such as TikTok-derived product or
   colour/category trends. It handles provenance, confidence, revisions,
   expiry, and retractions separately from shopper event counts.

Use distinct Fabric items and source connections, not merely two branches
inside one item. Land them in separate Eventhouse tables and combine their
curated features in one versioned scoring snapshot. This enables independent
schema changes, monitoring, and replay; shared Fabric capacity/Eventhouse
remain shared failure and performance dependencies.

The external stream can request work through Activator's **Run Notebook**
action. Behavior initially contributes through periodic runs rather than
launching jobs per shopper event. Both use the same Fabric notebook -> Azure
ML job -> validated publication lifecycle selected in the
[README](../../README.md#architecture). Its freshness is measured in the full
asynchronous pipeline; fast query-time reads do not guarantee seconds-level
score generation.

The POC does not assume a native TikTok connector or permission to scrape.
Use synthetic trend observations until a licensed/permitted provider
integration is explicitly approved.

See the [two-stream ingestion design](../architecture/eventstream-ingestion-design.md)
for topology, event contracts, per-source readiness, security, and acceptance tests.

## Personas

- **Shopper**: sees more relevant, "what's hot" results without doing
  anything differently.
- **Merchandiser/Marketing**: wants trending/viral products to surface
  automatically, and wants visibility (dashboard) into what's driving the
  ranking changes.
- **Platform/Search engineer**: needs a maintainable way to blend a
  real-time signal into Azure AI Search's ranking without destabilizing the
  base relevance model or introducing unacceptable latency/cost.

## Non-goals for this POC

- Building a production-grade recommendation engine or full personalization
  (per-user ranking) — the focus is *aggregate* real-time trend/behavior
  signals, not 1:1 personalization (though the architecture should not
  preclude adding that later).
- Building an actual TikTok/social-media scraper/connector — the POC will
  **simulate** external viral signals as events with the same shape a real
  connector would produce, so the integration pattern is proven without
  depending on a specific third-party API/ToS.
- Replacing Azure AI Search's core relevance engine (BM25/vector/semantic
  ranker) — this POC augments ranking, it doesn't reimplement it.

## Success criteria

- A search for a product/category shows a measurably different order within
  ~1–5 minutes of a synthetic "spike" of events being injected, compared to
  the baseline (no-spike) order.
- The pipeline (Fabric ingestion → aggregation → AI Search/signal store
  update) is observable end-to-end (can trace an event from ingestion to
  its effect on ranking).
- The design distinguishes between signals that are safe to bake into the
  AI Search index (slower cadence) vs. signals that need query-time
  blending (fastest cadence), and documents the trade-off.
