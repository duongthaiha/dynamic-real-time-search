# Azure AI Search primer: what's actually adjustable at query/index time

This POC's core question is: *"Azure AI Search ranking is normally static —
what mechanisms exist to make it react to a live signal?"* Three mechanisms
matter here.

## 1. Scoring profiles (index-time-declared, data-driven at query time)

A [scoring profile](https://learn.microsoft.com/azure/search/index-add-scoring-profiles)
is defined on the index and referenced per-query (`scoringProfile=...`). It
adds a weighted boost on top of the base text-relevance score, using:

- **Weighted fields** — boost matches found in specific fields (e.g., title
  vs. description).
- **Freshness function** — boosts documents based on how recent a
  `DateTimeOffset` field is (e.g., `lastTrendingAt`), with a configurable
  boosting duration/interval.
- **Magnitude function** — boosts documents based on where a numeric field's
  value falls in a range (e.g., `trendingScore` from 0–100, or
  `viewVelocity1h`), with linear or constant interpolation.
- **Distance function** — boosts by geo-proximity (not relevant here).
- **Tag function** — boosts by overlap between a document's tag field and
  tags supplied in the query (`scoringParameter`), e.g. matching a
  `trendingTags` field (`viral`, `celebrity-blue`) against tags passed in at
  query time.

**Key implication:** scoring profiles only work off **fields that already
exist in the index document**. To use them for real-time trend boosting, the
pipeline must **write the live signal value into the index** (e.g.,
`trendingScore`, `viewVelocity1h`, `lastTrendingAt`, `trendingTags`) via
`mergeOrUpload`. This means "real-time" is bounded by how often you're
willing/able to push partial document updates — seconds-to-minutes is
realistic, true sub-second is not (indexing has its own latency + eventual
consistency).

## 2. Incremental document updates (`mergeOrUpload` / `merge`)

Azure AI Search supports partial updates to existing documents via the
Documents - Index REST API (`mergeOrUpload` or `merge` actions), only
touching the fields you send — you don't need to resend the whole document.
This is the mechanism the Fabric pipeline will use to push aggregated
per-product scores into the index cheaply and frequently (e.g., every
30–60s for a "hot set" of a few thousand actively-changing SKUs, rather than
reindexing the whole catalog).

Relevant constraints:
- Each merge is a partial update **keyed by the document key** — the
  pipeline needs to know the product's search-index key (SKU/product ID).
- Batch requests (up to 1,000 docs / ~16 MB per request) are the efficient
  way to push many product score updates at once.
- If a document key doesn't exist yet, `mergeOrUpload` will fail/upsert
  depending on the action used — the products stream should generally
  already exist in the index (this is a *scores* update, not new-product
  ingestion).
- There's a queryable "propagation" delay before updates are guaranteed
  visible to all replicas/searches — good enough for this use case, but
  not appropriate for sub-second personalization.

## 3. Query-time / application-side re-ranking (outside AI Search)

Nothing stops the application layer from:

1. Querying AI Search for a larger-than-displayed candidate set (e.g. top
   100–200 by relevance/vector score).
2. Re-scoring/re-sorting that candidate set in the application tier using
   **any signal available at request time** — including signals that are
   too fresh or too fine-grained to have been written back into the index
   yet (e.g., "this SKU had 40 add-to-bags in the last 90 seconds").
3. Truncating/paging the final blended list to return to the client.

This is the only way to get **true real-time** (sub-second-to-second)
reaction to a signal, because it skips the indexing pipeline entirely and
reads live scores from a fast key-value store (Redis / Cosmos DB) that a
streaming job keeps updated continuously. The trade-off is that this ranking
logic lives in custom application code rather than AI Search's native
scoring profile engine, so it needs its own testing/tuning and doesn't
benefit from AI Search's semantic ranker unless you still start from AI
Search's own ordering as the base signal.

## Semantic ranker note

Azure AI Search's [semantic ranker](https://learn.microsoft.com/azure/search/semantic-search-overview)
reorders the top ~50 BM25 results using a Microsoft-trained relevance model
based on the *query and document text* — it has no notion of "trending" and
cannot be fed live behavioral signals directly. It's complementary (improves
text relevance quality) but is not itself a mechanism for dynamic/real-time
boosting. If used, it typically runs *before* the trending-aware re-rank
step described above (semantic ranker narrows/reorders on textual quality,
then the trending blend nudges within/around that ordering).

## Summary of levers

| Mechanism | Latency | Granularity | Implementation effort | Notes |
|---|---|---|---|---|
| Scoring profile + `mergeOrUpload` | seconds–minutes | per-document field | Low–medium | Native AI Search ranking, works for any client query |
| Application-side re-rank using live signal store | sub-second–seconds | per-document, per-request | Medium–high | Full control, needed for true real time / personalization |
| Semantic ranker | n/a (query-time, stateless) | per-query | Low (config only) | Complementary text-relevance quality, not a trend signal |
