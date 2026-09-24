# Microsoft Fabric primer: Real-Time Intelligence components used in this POC

Microsoft Fabric's **Real-Time Intelligence** workload provides an
end-to-end pipeline from event ingestion to analytics to automated action,
which maps very naturally onto "ingest shopper events → compute trend
signals → push updates out."

## Components

### Eventstream

The ingestion/processing layer. Supports many **sources** (Event Hubs,
IoT Hub, Kafka, Azure SQL CDC, custom REST/Custom App producing to an
Event Hub-compatible endpoint, sample data, etc.) and lets you apply
**no-code stream processing** before landing data: filtering, data
cleansing/transformation, **windowed aggregations**, deduplication, and
content-based routing to different destinations based on filters.

Destinations include: **Eventhouse (KQL DB)**, Lakehouse, Fabric
Activator, and a **custom endpoint** (so external apps/services can
consume the processed stream directly, e.g. our re-ranking API could
subscribe rather than poll a store).

For this POC:
- **Source**: a *Custom App* source (an Event Hub-compatible endpoint) that
  the e-commerce backend (or a synthetic load generator) sends
  `search` / `view_product` / `add_to_bag` / `purchase` events to, plus a
  second Custom App source (or the same, tagged by `eventType`) for
  external "viral signal" events.
- **Processing**: light transformation (parse/validate JSON, enrich with a
  `productId` join, maybe a first coarse windowed count) before landing in
  Eventhouse.
- **Destinations**: Eventhouse (for historical + KQL aggregation) and,
  optionally, a **custom endpoint** or **Activator** for the lowest-latency
  path to the signal store.

### Eventhouse (KQL Database)

A managed, high-performance **KQL** (Kusto Query Language) database
optimized for streaming/time-series data. This is where per-product
rolling metrics are computed:

- **Update policies** / **materialized views** continuously roll up raw
  events into aggregate tables, e.g. `ProductSignals5Min` with columns like
  `productId, windowStart, viewCount, addToBagCount, purchaseCount,
  externalTrendScore, computedTrendingScore`.
- A **KQL queryset** can define the "trending score" formula (e.g. z-score
  of recent volume vs. a trailing baseline, or a simple weighted sum of
  recent event counts with time decay) and can be scheduled or queried
  on-demand.
- Real-Time Intelligence unifies KQL, T-SQL (via the SQL analytics
  endpoint), and notebooks over the *same* data without copying it —
  useful because the same Eventhouse tables can be queried by a scheduled
  Fabric notebook (to push updates into AI Search) *and* explored/BI'd by
  analysts/merchandisers in the same workspace.

### Activator

A **no-code event detection / reflex-action engine** layered on top of
Eventstream or Eventhouse data. It continuously watches for conditions
(thresholds, patterns) with low latency (sub-second for stateless rules on
streaming data) and triggers actions — e.g., "notify/act when a product's
5-minute view count exceeds 3x its trailing 1-hour baseline." Actions can
include Teams/Outlook notifications, Power Automate flows, or (relevant
here) triggering a downstream call. This is the natural place to define
"what counts as trending/viral" as a rule, decoupled from writing custom
KQL, and to fan out an action when a spike is detected (e.g., "call this
Power Automate flow / webhook to push the SKU into the fast-boost store
immediately," bypassing the normal aggregation cadence for genuinely
spiky events).

### Notebooks / Data pipelines

Standard Fabric notebooks (PySpark/Spark SQL) or pipelines can run on a
schedule (e.g., every 1–2 minutes) to:

1. Query the latest aggregate signals from the Eventhouse KQL tables.
2. Compute/normalize a `trendingScore` (and related fields) per product.
3. Call the Azure AI Search **Documents - Index (`mergeOrUpload`)** REST
   API to write those fields back into the search index for the "index
   scoring profile" path, and/or write to Cosmos DB/Redis for the
   "application-side re-rank" path.

This is the most flexible integration point (arbitrary code, any SDK) and
is the piece to prototype first, since it doesn't require building a
custom Eventstream destination connector.

## Why Fabric (vs. a bespoke Event Hubs + Stream Analytics/Databricks stack)

- Eventstream's no-code source/transform/destination model gets ingestion
  + basic processing running quickly without hand-rolled stream-processing
  code.
- Eventhouse (KQL) is purpose-built for exactly this kind of "recent window
  rollups over high-volume event data" workload and is what merchandising
  analysts would also use in Power BI/real-time dashboards to *see* why a
  product is trending — a single source of truth for both the automated
  pipeline and human analytics.
- Activator gives a low-code way to encode "what counts as a spike" without
  writing/maintaining custom anomaly-detection code, and to react in
  near-real time to genuinely sudden events (the TikTok/celebrity case).
- All of it lives in one Fabric workspace with unified governance/lineage,
  which matches the customer's stated direction of standardizing on Fabric
  for their event platform.

## Fabric → Azure AI Search integration gap (as of research)

There is **no built-in Fabric-to-AI-Search connector/destination**. The
bridge has to be custom: either a scheduled notebook/pipeline calling the
AI Search REST API, or an Eventstream **custom endpoint** consumed by a
small Azure Function/Container App that performs the `mergeOrUpload`
calls and/or writes to the fast signal store. This is expected and is the
main "glue" component this POC needs to build and validate.
