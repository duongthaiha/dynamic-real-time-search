# Architecture options

Three candidate architectures, from simplest/slowest to most complex/fastest.

## Option A — "Index-side boosting only" (batch-lite)

```
E-commerce app ──events──> Fabric Eventstream ──> Eventhouse (KQL rollups)
                                                        │
                                        Fabric notebook/pipeline (scheduled, e.g. every 1-2 min)
                                                        │
                                                mergeOrUpload (trendingScore, lastTrendingAt, trendingTags)
                                                        │
                                                        v
                                              Azure AI Search index
                                                        │
                                        Storefront queries AI Search directly
                                        with a scoring profile (freshness +
                                        magnitude + tag functions)
```

**Pros:** Simplest to build; no new runtime service; every client
(storefront, mobile app, internal tools) automatically benefits because the
boost is baked into the index and used by AI Search's native scoring
profile.

**Cons:** Latency floor = scheduled job cadence (realistically 1–2 min, not
seconds); every polling cycle re-touches potentially thousands of documents
even if nothing changed much (cost/throughput consideration); genuinely
"viral in the last 30 seconds" spikes won't show up until the next cycle.

**Best for:** signals that are inherently "rolling window" in nature anyway
(view velocity over 5–60 minutes, external trend scores that don't need
sub-minute freshness).

## Option B — "Application-side re-ranking only" (fully custom)

```
E-commerce app ──events──> Fabric Eventstream ──> Eventhouse (KQL rollups)
                                   │                      │
                                   │              Fabric Activator (spike detection)
                                   │                      │
                                   └──custom endpoint──>  Azure Function/Container App
                                                                 │
                                                        writes live scores to
                                                        Redis / Cosmos DB (per productId)
                                                                 │
Storefront ──query──> Re-ranking API ──candidates(top 100-200)──> Azure AI Search (base relevance)
                    <──blended, re-sorted results──
                                 │
                    reads live scores from Redis/Cosmos DB at request time
```

**Pros:** True near-real-time (seconds), full control over the blending
formula, natural place to add personalization later (per-user weighting),
no extra load on the AI Search index itself.

**Cons:** All clients must go through the custom re-ranking API to benefit
(AI Search itself, queried directly, still shows the old static order);
more moving parts to build/operate (API, cache store, blending logic,
monitoring); duplicate "ranking" logic exists outside AI Search's scoring
profile engine, which can drift out of sync conceptually.

**Best for:** the truly viral/spike case where the customer wants
reaction within seconds, and where the re-ranking logic will likely evolve
into a broader personalization/ML re-ranker over time anyway.

## Option C — Hybrid (recommended)

Combine A and B: slower-moving/aggregate signals are written into the AI
Search index (Option A path) so that *any* AI Search client gets a
reasonable "trend-aware" baseline; the fastest-moving/most-important
signals (spike detection from Activator, e.g. "viral in the last 5
minutes") are *also* pushed to a fast signal store and applied by a thin
re-ranking API in front of the primary storefront experience for the extra
responsiveness where it matters most.

**Pros:** Best of both — native AI Search boosting works for every
consumer as a solid baseline; the storefront's primary experience gets true
real-time reaction to spikes without waiting for the index update cycle;
Activator's spike detection cleanly maps to "the exceptional/viral case"
while the scheduled pipeline handles "steady-state trend momentum."

**Cons:** Most components to build and operate (still, each component is
individually simple); requires clear ownership of "which signal goes down
which path" to avoid double-boosting the same thing.

**Best for:** this POC — because the *stated* customer requirement is
literally both cases: gradual behavioral trend momentum (add-to-bag/view
velocity — a good fit for Option A cadence) and abrupt external virality
(TikTok/celebrity — the case that most needs Option B's speed).

## Comparison summary

| | Option A: Index-side only | Option B: App-side only | Option C: Hybrid |
|---|---|---|---|
| Reaction latency | 1–2 min | seconds | seconds (spikes) / 1–2 min (baseline) |
| New runtime services | 0 (scheduled job only) | 1–2 (API + cache) | 1–2 (API + cache), reuses scheduled job |
| Benefits all AI Search clients | Yes | No (only re-rank API consumers) | Yes (baseline) + fast path for primary storefront |
| Supports future personalization | Limited | Yes | Yes |
| Build complexity | Low | Medium-High | Medium-High (a superset of B) |
| Risk of "double boosting" | Low | Low | Medium — needs signal ownership rules |

See [05-recommended-architecture.md](05-recommended-architecture.md) for the
detailed hybrid design.
