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
