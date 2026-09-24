# Event schema

All events are JSON, sent to Fabric Eventstream (Custom App source, an
Event Hub-compatible endpoint). A common envelope keeps downstream KQL
parsing simple; `payload` varies by `eventType`.

## Common envelope

```json
{
  "eventId": "b2f0c1f0-...-uuid",
  "eventType": "view_product",
  "eventTime": "2026-09-17T15:04:05.123Z",
  "source": "storefront-web",
  "sessionId": "s_9f2e...",
  "userId": "u_1234 (nullable/anonymous)",
  "payload": { }
}
```

## First-party behavioral events

### `search`
```json
{ "query": "blue jacket", "resultsCount": 42, "filters": {"category": "jackets"} }
```

### `view_product`
```json
{ "productId": "SKU-10293", "category": "jackets", "colour": "blue", "position": 3, "sourceQuery": "blue jacket" }
```

### `add_to_bag`
```json
{ "productId": "SKU-10293", "quantity": 1, "price": 89.99 }
```

### `remove_from_bag`
```json
{ "productId": "SKU-10293", "quantity": 1 }
```

### `purchase`
```json
{ "orderId": "O-556677", "items": [{"productId": "SKU-10293", "quantity": 1, "price": 89.99}] }
```

## External / derived "trend" events

These are produced by a social-listening/trend-detection process (simulated
in the POC — see [07-poc-plan.md](07-poc-plan.md)) and are attribute- or
product-level, not tied to a first-party session.

### `external_trend` (attribute-level — the "blue clothing" case)
```json
{
  "eventType": "external_trend",
  "payload": {
    "signalType": "attribute",
    "attributes": { "colour": "blue", "category": "jackets" },
    "confidence": 0.82,
    "magnitude": 0.6,
    "source": "tiktok",
    "sourceRef": "video:7312...",
    "reason": "celebrity_mention",
    "celebrity": "Jane Doe"
  }
}
```

### `external_trend` (product-level — a specific SKU going viral)
```json
{
  "eventType": "external_trend",
  "payload": {
    "signalType": "product",
    "productId": "SKU-10293",
    "confidence": 0.91,
    "magnitude": 0.95,
    "source": "tiktok",
    "sourceRef": "video:8891...",
    "reason": "viral_video"
  }
}
```

Field notes:
- `confidence` (0–1): how sure the upstream detection is that this is a
  genuine trend vs. noise (relevant if a real social-listening/ML service
  is later plugged in).
- `magnitude` (0–1): relative strength of the trend signal, used directly
  as an input to the `trendingScore` formula.
- `attributes` is an open map so new dimensions (brand, material, print)
  can be added without a schema change.

## Eventhouse tables (derived)

| Table | Grain | Purpose |
|---|---|---|
| `RawEvents` | 1 row per event | Full fidelity, source of truth, replay/debug |
| `ProductSignals1Min` / `5Min` | productId × window | Rolling counts: views, add-to-bag, purchases, external product-level trend magnitude |
| `AttributeTrend5Min` | attribute key/value × window | Rolling external trend magnitude per colour/category/brand |
| `ProductTrendingScore` (materialized view) | productId | Final normalized 0–100 `trendingScore`, `lastTrendingAt`, `trendingTags[]` — this is what gets pushed to AI Search / cache |

## `trendingScore` formula (starting point for the POC, to be tuned)

```
behavioral = normalize( w1*viewVelocity + w2*addToBagVelocity + w3*purchaseVelocity )
external   = normalize( max(productLevelExternalMagnitude, attributeLevelExternalMagnitude * confidence) )
trendingScore = clamp( 100 * (alpha*behavioral + (1-alpha)*external), 0, 100 )
```

Suggested starting weights: `w1=1, w2=2, w3=3` (deeper funnel actions count
more), `alpha=0.5` (equal weight to behavioral vs. external until real data
suggests otherwise). This formula is intentionally simple for the POC and
should be validated/replaced with real historical data before any
production consideration.
