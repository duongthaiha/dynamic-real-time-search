# Azure commerce search platform: proposed design

**Status:** Proposed expansion blueprint; not implemented or benchmarked

**Reviewed:** 29 September 2026

**Research:** [Google commerce search and Azure equivalence](../research/09-google-commerce-search-azure-equivalence.md)

**Repository guide:** [Selected architecture and local tooling](../../README.md#architecture)

## 1. Decision and boundaries

Build a single-retailer commerce discovery platform using Azure AI Search for
retrieval and Azure/Fabric services for commerce policy, events and ML. Aim for
functional coverage of Google's commerce-search offering through staged
evidence, not API compatibility or identical proprietary model behavior.

This document **does not supersede the README's selected architecture**. It
defines the product roadmap. Recommendations, personalization, embeddings, semantic
retrieval and conversations are future capabilities, not newly implemented
defaults. Cart/checkout actions and customer-service agents remain separate.

### Existing foundations versus proposed work

| Area | Repository evidence | Implication |
|---|---|---|
| Catalog | [Synthetic catalog guide](../catalog-data.md), generator/test files and [index definition](../../src/load-generator/azure-search-index.json). | Reuse the seeded 1,000-product catalog. Its presence does not prove deployed search or end-to-end ranking. |
| Public APIs | [Search and Beacon drafts](../api/README.md). | Preserve public event names and service separation. Responses and provider compatibility remain unverified proposals. |
| Trend pipeline | [Option C detailed design](option-c-hybrid-detailed-design.md). | Keep deterministic index-side first, then notebook/ML jobs, validated publication and incremental live reranking. |
| Source ingestion | [Two-stream design](eventstream-ingestion-design.md). | Separate behavior and external-trend Eventstream items; share curated features, not unrestricted credentials or event counts. |
| Learning | [Forecasting research](../research/08-azure-ml-forecasting.md). | Forecasting is a later experiment, not an implemented recommender or search learning-to-rank system. |
| Full commerce platform | This document. | Merchant controls, recommendations, consented profiles, conversation and production operations require further implementation. |

### Scope

**In scope:** search/browse, product and SKU eligibility, facets/suggestions,
merchant controls, behavioral ranking, recommendation families, experimentation,
read-only conversational discovery, and a route to production.

**Out of current implementation scope:** Google Retail API emulation,
production shopper-data collection, social scraping, checkout/payment tools,
autonomous purchasing, SaaS tenant onboarding, global active-active deployment
and any resource provisioning performed just to create these documents.

Use synthetic data for all current work. Any later real-data experiment needs
separate authorization, privacy review and operational readiness.

## 2. Architecture and component ownership

The default is a composed platform, not an all-LLM search engine. Query serving
must not wait for a Fabric notebook or an Azure ML batch job.

```mermaid
flowchart LR
    subgraph Sources["Retailer sources"]
        CAT["Catalog, price and inventory systems"]
        COM["Sales, margin and inventory facts"]
        SHOP["Storefront or backend-for-frontend"]
        PROF["Consented profile service - later"]
        EXT["Synthetic or approved trend provider"]
        MER["Merchandiser"]
    end
    subgraph Serving["Discovery serving"]
        API["Functions: Search and Browse"]
        REC["Recommendation service - later"]
        CONV["Conversation service - later"]
        IDX[("Azure AI Search")]
        STATE[("Cosmos DB: scoped serving state")]
        LLM["Foundry / Azure OpenAI - optional"]
    end
    subgraph Control["Configuration and catalog control"]
        SYNC["Catalog projection and publisher"]
        ADMIN["Merchant admin and approval - later"]
        CFG[("Versioned policies and audit")]
    end
    subgraph Learning["Asynchronous features and scoring"]
        BEA["Beacon validation"]
        BES["Behavior Eventstream"]
        EXTAD["Approved trend adapter and metadata extraction"]
        XES["External-trend Eventstream"]
        EH[("Eventhouse curated features")]
        ACT["Activator Run Notebook"]
        NB["Fabric orchestration notebook"]
        SCHED["Periodic schedule"]
        SNAP[("Immutable feature artifacts")]
        ML["Azure ML jobs"]
        LEDGER[("Durable run and publication ledger")]
        PUB["Reconcile, validate and publish"]
    end
    CAT --> SYNC
    SYNC --> IDX
    SYNC --> EH
    COM --> EH
    MER --> ADMIN --> CFG
    CFG --> API
    CFG --> REC
    PROF --> API
    SHOP --> API --> IDX
    API --> STATE
    SHOP --> REC
    REC --> STATE
    REC --> IDX
    SHOP --> CONV
    CONV --> LLM
    CONV --> API
    CONV --> REC
    SHOP --> BEA --> BES --> EH
    EXT --> EXTAD --> XES --> EH
    XES --> ACT --> NB
    SCHED --> NB
    EH --> NB --> SNAP --> ML
    NB --> LEDGER
    ML --> PUB
    LEDGER --> PUB
    PUB --> IDX
    PUB --> STATE
```

The ML-to-publication edge represents **durable reconciliation**, not a native
automatic callback or proof of successful completion. The diagram omits
telemetry edges for readability. Emit correlated telemetry at each boundary.

| Component | Native service contribution | Custom responsibility |
|---|---|---|
| Azure AI Search | Keyword/vector retrieval, filters, facets, suggesters, scoring profiles and optional semantic ranker. | Catalog schema, query policy, field mappings, candidate limits and relevance evaluation. |
| Azure Functions | API and background execution hosting. | Search/Beacon adapters, validated policy plans, registered batch factor providers, a factor-independent composer, catalog/score publication and explicit errors. Select hosting plan against latency/network requirements later. |
| Cosmos DB for NoSQL | Serving/configuration storage and concurrency primitives. | Separate containers and schemas for live signals, durable ledgers, serving policies, recommendation lists and optional consented state. TTL is cleanup, not proof of freshness. |
| Fabric Eventstream/Eventhouse | Event routing, raw history and KQL analytics. | Source contracts, deduplication, revisions, catalog joins, watermarks, readiness and feature queries. |
| Commerce fact adapters | No assumption that revenue, margin or inventory systems share one schema or cadence. | Authenticate each source, preserve authoritative revisions/as-of times, normalize only approved aggregates, and keep financial detail and customer identity out of the Search index. |
| External trend adapter/extractor | No native TikTok connector is assumed. An approved provider API supplies permitted content references and engagement observations; a versioned batch extractor may use an approved vision/text model. | Provider authentication and terms, deduplication, minimal media handling, feature extraction, confidence, vocabulary mapping, provenance, revisions/retractions and bounded normalized events. |
| Activator and Fabric notebook | Qualified condition-to-notebook orchestration. | Trigger coalescing, immutable snapshot preparation, ML submission and durable correlation. No Function solely to launch ML jobs. |
| Azure ML | Reproducible jobs and optional model/endpoint lifecycle. | Scoring/training code, task objectives, feature contracts, evaluation, promotion and rollback. |
| Artifact storage | Durable feature/model/output artifacts through an explicitly selected supported storage path. | Snapshot manifest, immutable naming, hashes, access checks, retention and replay. OneLake access is not assumed for the ML identity. |
| Foundry/Azure OpenAI, later | Supported language/embedding/multimodal models and applicable safety features. | Tool authorization, grounding, scoped conversation, quality evaluation, budgets and deterministic recovery. |
| Entra ID, Key Vault, Azure Monitor/Application Insights | Workload identity, protected secrets and observability primitives. | Effective least privilege, consent policy, redaction, alert rules, service ownership and incident response. |
| Merchant/experiment control plane | Cosmos configuration; optional App Configuration/feature-flag telemetry. | Authoring, approvals, factor registry and weight policies, preview, rule compiler, stable assignment, actual exposures and experiment analysis. |

**Not default additions:** Container Apps, Azure Managed Redis, a separate
Event Hubs broker, API Management and Front Door/WAF. Evaluate them when
hosting, ingress, quotas, networking, isolation or measured latency justify
them. Do not add every service to the POC architecture.

Production internet exposure still needs abuse controls and a justified edge
design. "Not default" does not mean production security is optional.

### Options considered

| Option | Assessment |
|---|---|
| Azure AI Search alone | Good retrieval baseline; insufficient for a managed commerce learning loop, recommendation catalog or merchant workbench. |
| Search plus the existing Fabric/ML composition | **Selected.** Reuses POC foundations and makes custom capability ownership explicit. |
| Online ML for every request from the start | Defer. Adds availability, feature freshness and compute-cost dependencies before the batch baseline is proven. |
| LLM generates or orders every product result | Reject as the core path. Hard eligibility, exact identifiers and deterministic serving should not depend on free-form generation. |
| Azure AI Personalizer | Exclude: Microsoft's documented retirement date has passed. See the [research boundary analysis](../research/09-google-commerce-search-azure-equivalence.md#important-azure-boundaries). |

## 3. Logical contracts and authoritative data

These are logical records to formalize when implementing each stage, not new
OpenAPI schemas or claims that existing drafts already support them.

| Record | Key/version information | Invariants |
|---|---|---|
| Catalog projection | Authorized retailer/collection, product ID, SKU/variant IDs, source revision, catalog/schema version and observation time. | Stable keys; declared market/currency; current searchable/stock eligibility; tombstones for removals. |
| Serving policy | Scope, immutable policy ID/version, activation time and referenced index/model/rule/factor versions. | One validated active bundle per context; explicit rollback; no client-selected privileged configuration. |
| Ranking factor definition | Stable factor ID/version, registered provider/version, typed feature references, normalizer, privacy class, freshness and contribution ceiling. | Immutable meaning; allow-listed implementation; weight belongs to a serving policy, not source data. See section 3.5. |
| Product factor snapshot | Scope, product/variant ID, factor-set ID, factor/source revisions, value at its as-of time, expiry and evidence reference. | Point-in-time reproducible; no customer identity; retain unavailable status rather than inventing a measured zero. |
| Customer preference state, later | Authorized profile key, consent purpose/version, explicit or inferred preferences, confidence, source time and expiry. | Never copied to the shared Search index; request-scoped use only; withdrawal/deletion enforced; selected filters override inferred preferences. |
| Behavior event | Existing event envelope plus scoped event ID, schema version, occurrence/receipt times and known correlation. | Deduplicate before purchase expansion. Search, exposure, order and attribution identities are distinct. |
| External trend observation | Scope, stable signal/content reference, provider revision, observed/published/expiry times, extractor and vocabulary versions, compound normalized attributes, confidence, magnitude and provenance. | Approved or synthetic source only; latest revision wins; retractions remain effective; finite bounded values; no raw social identity or media is required downstream. |
| Exposure, later | Serving decision, displayed product/panel IDs, positions, filters, experiment assignment and purpose-limited visitor context. | A response is not an exposure. Capture what the UI actually displays under a documented exposure definition. |
| Feature snapshot | Scope/window/correction, catalog version, input-set identity, source readiness and artifact reference/hash. | Immutable, point-in-time valid and readable by the job identity. |
| Product trend | Existing canonical score/version/state/window/expiry and evidence references. | Finite `[0,100]`; preserve the existing version order and publication contract. |
| Recommendation list | Scope, task, seed item or authorized profile key, model/policy/catalog versions, ordered candidate IDs and expiry. | Candidates are not guaranteed currently eligible; revalidate before serving. Never reuse lists across unauthorized identities. |
| Training/model manifest | Task/objective, feature and label versions, dataset split, model asset, metrics and promotion decision. | No future labels in features; no automatic production promotion solely because a job succeeded. |
| Conversation state, later | Authorized session, consent/purpose, validated constraints, product references, policy version and expiry. | History is not authorization; model-generated IDs/filters cannot bypass validation. |

### 3.1 Catalog and variant projection

The retailer's product/inventory/pricing systems remain authoritative.
Azure AI Search is a discovery projection. The synthetic catalog uses parent
products, colourways and purchasable size variants; preserve their distinction.

For Stage B, propose a parent-result projection with correlated variant
attributes sufficient for the promised filters. For example, size, stock and
price must refer to the **same variant**, not independent flattened collections.
Validate a supported complex-collection/filter representation and document-size
limits before changing the index. If a catalog exceeds those limits, evaluate
variant documents and explicit parent grouping as a separate schema decision.

The current flattened `availableSizes` and `isInStock` fields are not proof
that a requested size is in stock at a particular price. Test a parent with
one cheap unavailable variant and one expensive available variant to catch
cross-variant false matches.

Define:

- Parent, colourway and SKU display/deduplication rules.
- Localized searchable text and market-specific price/currency selection.
- Attribute vocabulary, category hierarchy and normalized filter values.
- Inventory/promotion freshness policy and authoritative hydration where the
  experience promises current availability or pricing.
- Full import, incremental revision, tombstone and source-reconciliation flows.
- Catalog ownership of product fields versus score ownership of trend fields.

Do not allow an independent full-document catalog upload to reset newer trend
state. Route writes through coordinated publication ownership or reconstruct
the complete desired document before replacement. Trend writes remain
score-only `merge` operations; reserve full upserts for deliberate catalog
changes. Use one action per document in an indexing batch and handle individual
results. [Search indexing semantics](https://learn.microsoft.com/azure/search/search-how-to-load-search-index)

For schema rebuilds, prepare a new versioned index, catch up catalog changes,
apply the latest valid signals, validate queries and then switch the
application's active index configuration. Preserve rollback data and reconcile
deletions before activation. Do not claim an atomic transaction across index,
policy, feature artifacts and Cosmos containers.

### 3.2 Event and attribution evolution

Keep `POST /v1/search` and `POST /v2/events` separate. Keep public `autoSearch`,
`viewProduct`, `addToCart` and `order` payloads mapped through the existing
[normalization adapter design](../api/README.md#mapping-to-the-pocs-internal-events).

Before learned ranking, propose versioned exposure, filter-selection,
recommendation-panel and authoritative order-outcome extensions. Resolve:

- Actual display definition and whether an impression is viewable or rendered.
- Cart deltas versus snapshots, event counts versus quantities, and returns.
- Attribution window, competing exposures, duplicate orders and missing context.
- Browser versus trusted backend ownership; client-reported prices/orders are
  not proof of financial outcomes.
- Consent state and retention at ingestion, training and serving time.

A proposed opaque serving-decision token links to bounded server-side context
and must be scoped, integrity-protected and expiring. It is not an event ID or
authorization credential. Log unresolved attribution explicitly; never assign
a query-only search event to every retrieved product.

This Azure-native policy is not a claim to resolve the
[Google attribution-documentation inconsistency](../research/09-google-commerce-search-azure-equivalence.md#attribution-and-privacy)
for provider-compatible clients.

### 3.3 Viral-content metadata extraction and catalog matching

The TikTok-like use case is an **external aggregate trend**, not shopper
personalization. The POC uses synthetic content observations. A real source
must be an approved/licensed provider API or permitted TikTok integration with
verified fields, rights, retention and quotas. Do not scrape public URLs, infer
that a URL grants reuse rights, or assume Fabric has a native TikTok connector.

Use this asynchronous flow:

1. The external adapter receives a provider content ID, revision/cursor,
   permitted caption/hashtag text, permitted media or provider-derived labels,
   publish time and aggregate engagement observations. It authenticates the
   source, rate-limits collection and persists its checkpoint only after the
   normalized observation is acknowledged or durably buffered.
2. Deduplicate by provider and stable content ID before extraction. A content
   update creates a new revision; deletion, provider withdrawal or a failed
   trust review creates a retraction. Reprocessing the same revision is
   idempotent and does not refresh trend age.
3. A versioned batch extractor derives only approved commerce features. Start
   with caption/hashtag normalization and, if permitted, sampled video frames
   through an evaluated vision model. Candidate dimensions can include
   `colour`, `category`, `productType`, `fit`, `material`, `style`, `pattern`
   and `occasion`, but enable only fields represented in the versioned catalog
   projection. Store per-value confidence and evidence type, not an
   unqualified free-text label. OCR, faces, creator identity and audio are
   excluded unless separately justified and approved.
4. Map candidates to the retailer's versioned catalog vocabulary. For example,
   provider labels `navy`, `midnight blue` and `dark-blue` may map to catalog
   colour `blue` under a recorded mapping version. Unknown values remain
   reviewable evidence but contribute no score. Extraction and mapping
   confidence are calibrated separately.
5. Build one compound predicate from co-occurring evidence, such as
   `colour=blue AND fit=oversized AND category=jackets`. Do not split this
   into three independent trends. Require configured minimum confidence,
   source trust and engagement/velocity evidence before emitting an eligible
   `external_trend`; popularity alone does not prove an attribute.
6. Resolve that predicate against the immutable catalog projection in
   Eventhouse. Only exact normalized matches in the same catalog version
   receive an external contribution. Record the matched product IDs and
   catalog version in the feature snapshot so replay is deterministic.
7. Feed confidence-weighted magnitude into the existing canonical `[0,100]`
   score, then publish the validated per-product score through `merge` to
   Search and conditionally to live state. Retraction, expiry or a corrected
   predicate recomputes affected products and clears obsolete boosts.

Example normalized payload after extraction and vocabulary mapping:

```json
{
  "signalId": "tiktok-video-7312",
  "revision": 4,
  "operation": "upsert",
  "signalType": "attribute",
  "attributes": {
    "colour": "blue",
    "fit": "oversized",
    "category": "jackets"
  },
  "attributeConfidence": {
    "colour": 0.94,
    "fit": 0.81,
    "category": 0.96
  },
  "confidence": 0.83,
  "magnitude": 0.62,
  "source": "tiktok",
  "sourceRef": "provider-content:7312",
  "sourcePublishedAt": "2026-09-29T12:00:00Z",
  "observedAt": "2026-09-29T12:05:00Z",
  "validUntil": "2026-09-29T12:35:00Z",
  "extractorVersion": "fashion-attributes-v1",
  "vocabularyVersion": "catalog-fashion-v3"
}
```

The schema above extends the existing external observation payload; formalize
it in the source-family schema before implementation. Treat all strings and
model output as untrusted input. Bound arrays and lengths, reject non-finite
numbers, allow-list attribute keys, and keep provider credentials and raw
licensed payloads out of Eventhouse and logs.

Do not implement compound matching by passing the individual values to an
Azure AI Search tag scoring function. The documented tag function boosts when
**any** item in a string collection matches, which changes the intended AND
semantics. Resolve membership before publication and use the numeric
`trendingScore` magnitude profile. A canonical compound token could be
evaluated later, but it still needs versioned vocabulary and expiry handling.
[Azure AI Search scoring profiles](https://learn.microsoft.com/azure/search/index-add-scoring-profiles)
are selected per query and can boost numeric fields or string collections;
the baseline query must continue to omit the trend profile.

### 3.4 Generalized multi-factor ranking policy

Treat viral momentum as one factor in a governed ranking policy, not as the
universal score for every business objective. Keep factor values separate
through ingestion, storage, diagnostics and evaluation so a policy can change
weights without rewriting source history or pretending that revenue, stock
and customer affinity have the same meaning.

A **dimension** is a business concept such as season, stock or customer fit;
a **feature** is its typed source measurement; a **factor** turns permitted
features into one bounded ranking contribution; a **policy** selects factors
and their weights. Registering a dimension must not implicitly enable it.
Sections 3.4-3.5 are a proposed Stage B/D extension, not an implementation or a
replacement for Stage A's canonical trend score and three-mode benchmark.

#### Factor classes

| Factor | Example normalized meaning | Scope and freshness | Required guardrail |
|---|---|---|---|
| `viralTrend` | External-only momentum from `0` to `1` | Product; minutes | Preserve revision, expiry and compound attribute matching; do not include first-party behavior here. |
| `behaviorMomentum` | Recent first-party activity relative to a comparable baseline from `0` to `1` | Product; minutes | Deduplicate first; do not turn search impressions into product actions. |
| `canonicalTrend` | Existing versioned `trendingScore / 100` from `0` to `1` | Product; existing trend expiry | Compatibility adapter; cannot be enabled with its `viralTrend` or `behaviorMomentum` constituents. |
| `inventoryPressure` | Approved sell-through objective from `-1` to `1`; positive can favor safe excess stock and negative can suppress shortage risk | Product or correlated variant; near-real-time policy | Out-of-stock and selected-size availability remain hard constraints, never boosts. |
| `revenueVelocity` | Category/price-band-normalized recognized revenue velocity from `0` to `1` | Product; declared trailing window | Use authoritative completed-order facts, handle returns, and prevent rich-get-richer feedback from becoming an unreviewed objective. |
| `commercialValue` | Approved normalized margin, promotion or strategic value from `-1` to `1` | Product/market; policy window | Do not substitute revenue for margin or expose confidential values in results or diagnostics. |
| `profileColourAffinity` | Confidence-weighted match to a consented colour preference from `0` to `1` | Request/profile; expiring | Shared index stores no profile data; explicit query/filter choice wins. |
| `profileSizeAvailability` | Preferred size is currently available on the same eligible variant from `0` to `1` | Request/profile plus current inventory | Never infer that an uncorrelated parent-level size and stock flag describe the same variant. |
| `profileCategoryAffinity` | Consented category preference match from `0` to `1` | Request/profile; expiring | Apply support thresholds and provide an unpersonalized path. |
| `merchantPriority` | Approved campaign or strategic adjustment from `-1` to `1` | Product/rule/market; activation window | Version, approve and audit; cannot bypass eligibility or explicit sort. |

This registry is extensible, but adding a factor is a contract change. Define
its owner, source of truth, units, time window, normalizer, confidence,
freshness, privacy class, missing/stale behavior, allowed contexts and
evaluation before it can receive a nonzero weight. For example, raw stock
count, revenue in currency and trend magnitude must never enter one weighted
sum without separate, versioned normalization.

Keep the canonical `trendingScore` and its `alpha=0.5` policy unchanged for
Stage A. Independently weighting external and behavioral components requires
separate versioned outputs in the later factor path, not reverse-engineering
them from that combined score. Declare evidence lineage and mutually exclusive
composites in the registry. The validator rejects composite-plus-constituent
use; correlated objectives such as purchase momentum and revenue require
explicit overlap review and ablation, not a claim of independent evidence.

#### Policy model

An immutable policy selects enabled factors and their relative influence.
Weights are nonnegative influence strengths. Each provider returns a finite
`effectiveValue` in `[-1,1]` at the pinned request time, **after** its versioned
normalization, confidence and decay policy. The composer does not apply
confidence or decay again. In particular, the `canonicalTrend` adapter does
not discount the already confidence-weighted, decayed score twice: it retains
the published value until a validated update or expiry. It cannot reconstruct
the components' different decay curves from one combined score.

Let `E` be the configured enabled factors with positive weights. The weight
denominator is fixed for the policy, including factors unavailable on this
request. Missing, denied, stale, timed-out or invalid factors contribute zero
with their explicit status; they do not donate their weight to other factors.
Disabling a factor or rebalancing weights is a new policy version:

```text
weightTotal = sum(weight_i for i in E)

rawContribution_i = 0 if result_i.status != valid, otherwise:
    maxFactorAdjustment
  * (weight_i / weightTotal)
  * result_i.effectiveValue

factorContribution_i =
  clamp(
    rawContribution_i,
    -maxContribution_i,
    maxContribution_i
  )

factorAdjustment =
  clamp(
    sum(factorContribution_i),
    -maxFactorAdjustment,
    maxFactorAdjustment
  )

normalizedSearchRelevance =
  1 - (originalRank - 1) / max(candidateCount - 1, 1)

finalScore = normalizedSearchRelevance + factorAdjustment
```

Reject non-finite/out-of-range provider values rather than using clamping to
hide a contract failure. The clamps above enforce contribution budgets only.
Start `maxFactorAdjustment` no higher than the existing `0.20` normalized
relevance cap and enforce the configured maximum rank movement and relevance
floor. A multi-factor policy with no positive weights fails validation before
division; an explicit `baseline` policy with no factors is valid and preserves
Search order. A valid policy whose factors are all unavailable also preserves
Search order, with degradation metadata, rather than dividing by available
weight. Zero/one eligible candidate requires no reordering.

Sort by final score, original Search rank, then product key. Apply the
relevance floor to positive adjustments and enforce absolute rank movement on
the resulting permutation, not by independently clamping item positions
(which can collide). If the constrained sorter cannot produce a verified
permutation, retain Search order with a guardrail diagnostic. These rank-based
limits are not guarantees of semantic relevance; evaluate on judged queries.

Keep execution modes explicit; the formula above is for `policy-hybrid` only:

- **`policy-hybrid`:** Search retrieves without an optional business/trend
  profile or such a default profile. The API applies the complete factor
  policy once to a bounded candidate window. This is the preferred extension
  for dynamic weights and request-specific dimensions, not native vector
  hybrid retrieval and not Option C's indexed/live trend delta.
- **`index-policy`:** one named profile applies only explicitly supported
  nonpersonal factors. Its versioned mapping must validate field types,
  direction, ranges and expiry clearing; reject unsupported definitions
  rather than approximating them silently. Native profile scoring is not
  numerically equivalent to the formula and cannot enforce an API rank cap.
  Do not add generic live factor deltas in this mode.
- **Existing trend modes:** preserve Option C's separately evaluated
  `trendingScore` profile and delta-only algorithm, comparing actual indexed
  values returned by Search. Equal snapshots add no incremental boost.

Azure AI Search supports multiple functions inside a scoring profile, but only
one profile can be selected per query. Profile definitions and numeric boosts
are index configuration, not a general per-request factor-weight API. Do not generate an
unbounded profile for every customer or rely on preview-only function
aggregation without explicit approval.
[Azure AI Search scoring profile rules](https://learn.microsoft.com/azure/search/index-add-scoring-profiles#rules-for-scoring-profiles)

Example policy emphasizing viral momentum:

```json
{
  "schemaVersion": "ranking-policy-v1",
  "policyId": "fashion-viral-led",
  "version": "2026-09-29.1",
  "factorSetId": "fashion-factors-v1",
  "mode": "policy-hybrid",
  "candidateWindow": 100,
  "maxFactorAdjustment": 0.15,
  "maxRankMovement": 12,
  "positiveAdjustmentRelevanceFloor": 0.25,
  "factors": [
    { "id": "viralTrend", "version": "v1", "weight": 0.50, "maxContribution": 0.08 },
    { "id": "revenueVelocity", "version": "v1", "weight": 0.15, "maxContribution": 0.03 },
    { "id": "inventoryPressure", "version": "v1", "weight": 0.15, "maxContribution": 0.03 },
    { "id": "profileColourAffinity", "version": "v1", "weight": 0.10, "maxContribution": 0.02 },
    { "id": "profileSizeAvailability", "version": "v1", "weight": 0.10, "maxContribution": 0.02 }
  ]
}
```

For a revenue-led variant, use weights `0.15 / 0.45 / 0.20 / 0.10 / 0.10` in
the same factor order, with approved contribution caps
`0.03 / 0.08 / 0.03 / 0.02 / 0.02`; the global cap stays `0.15`. With every
effective value equal to `1`, viral's contribution changes from `0.075` to
`0.0225`, and revenue's from `0.0225` to `0.0675`. Raising only revenue's weight
while keeping a binding `0.03` cap would limit the intended change. Percent
weights are shares of a bounded adjustment budget, not percentages of rank
movement or expected revenue.

`factorSetId` pins exact factor/provider/feature/normalizer versions and
compatible serving data. Policy validation rejects unknown/duplicate factors,
invalid numbers, caps above factor/platform ceilings, unsupported modes,
conflicting evidence and missing consent requirements. Policies are scoped by
authorized collection, market and activation window. Resolve one approved
bundle before the request; tie-breaking between campaigns/experiments is
explicit. Shoppers cannot submit weights, provider references or privileged
policy IDs. Activation uses the existing approval and rollback lifecycle.

#### Customer preference handling

Explicit request intent has higher authority than inferred profile state. A
shopper filtering for red must not receive a blue preference boost, and a
selected size is a hard same-variant availability constraint. Favorite colour,
size or category can be a soft factor only when consent, purpose, confidence,
freshness and profile scope are valid.

Fetch profile state in one authorized bounded read, calculate matches only for
the retrieved candidates, and do not emit raw preferences in response
diagnostics or metric dimensions. If consent is absent, withdrawn, stale or
unavailable, personalized factors contribute zero without renormalizing the
remaining weights. The response identifies an allowed unpersonalized mode
without revealing why to another caller.
Policy and experiment cache keys include the authorized profile/consent
context; shared result caches cannot contain personalized order.

### 3.5 Adding a dimension without changing the ranking core

**Extension boundary:** the composer knows the result contract, weights and
guardrails, not a switch statement for TikTok, revenue or the next dimension.
Use a small registry of reviewed provider implementations inside the existing
publisher/Search service. Do not build a dynamic plugin host, arbitrary formula
language, new microservice per factor, or runtime-loaded scripts.

| Change | Required work | Ranking core / Search schema |
|---|---|---|
| Change an existing factor's weight, cap or activation schedule | New immutable policy; preview and approval | Neither changes |
| Add a dimension using an existing provider and supported features | New factor definition, fixtures and factor-set/policy versions | Neither changes in `policy-hybrid` |
| Add a genuinely new source or calculation | Authorized ingestion adapter/feature contract and, if needed, a reviewed provider implementation with tests | Composer unchanged if the result contract still fits |
| Use a new catalog property | Populate/version the catalog projection and missing-value policy; revalidate compound/variant matching | Search schema changes only if retrieval, filters or an index profile need the property |
| Add a hard eligibility rule or incompatible result type | Separate contract/design and migration review | Not disguised as a boost factor |

#### Definition and evaluation contracts

The following proposed contracts must be formalized with the chosen runtime;
they do not imply that providers or a registry already exist:

| Definition field group | Required semantics |
|---|---|
| Identity | `schemaVersion`, stable `factorId`, immutable `version`, owner and description. Never change the meaning of a published version. |
| Inputs | Registered `providerRef`, exact typed `featureRefs` and `normalizationRef`. Each feature declares source, units/currency, grain, vocabulary/catalog version, scope and source-time semantics. No implicit type/variant coercion. |
| Evaluation | `evaluationScope` (`product` or `request`), supported serving modes and `effective-signed-v1` result contract. Product factors are batch-prepared; request factors use already hydrated bounded features. |
| Quality | Freshness/decay reference, maximum age and expiry rules; normalization, confidence and decay have one provider owner. A later query evaluates remaining decay from the snapshot's recorded as-of time, never refreshes age or compounds the same discount twice. |
| Privacy and evidence | Nonpersonal versus consented profile class, confidentiality classification, required purpose, evidence families and mutually exclusive composites. Derived features inherit the most restrictive input classification; nonpersonal does not mean publicly disclosable. |
| Limits and failure | Contribution ceiling, bounded input/result sizes, allowed request contexts and `omit-with-diagnostic` for optional signals. Mandatory eligibility checks stay outside this contract. |

Keep input adapters separate from factor evaluators. A new raw source may
need its own schema, rejection route, credentials and approval; a generic
curated factor table is not permission to mix financial data into the existing
behavior/external Eventstreams.

The serving coordinator pins policy, scope, catalog/feature references and an
injectable `requestAsOf`, hydrates shared inputs once, and calls a conceptual
`evaluateBatch(definitions, candidates, authorizedContext, requestAsOf)`.
Providers cannot call one external service per product, launch a scoring job,
return new candidates, or invoke each other recursively. Compose dependencies
as declared upstream features; validate the feature graph for cycles, versions,
readiness and privacy before activation. New model inference on the request
path still requires the separate online-serving design.

For every requested factor/candidate pair, return:

| Result field | Contract |
|---|---|
| Identity | Exact product/variant key and factor/version requested; authorized scope and input-set reference. |
| `status` | `valid`, `missing`, `stale`, `notApplicable`, `denied` or `error`; include a bounded reason code. |
| `effectiveValue` | Finite `[-1,1]` only for `valid`; otherwise `null`. A known no-match is `valid` with `0`, not a source outage. |
| Time and lineage | UTC `sourceAsOf`, `evaluatedAt`, `validUntil` and source revision; catalog, provider and normalizer versions are pinned by input/factor-set references. Source metadata may be null for unavailable inputs, never fabricated. A valid value must be unexpired at `requestAsOf`; expiry is the earliest dependency/age deadline. |

Validate outputs before composition. Unknown/duplicate candidate keys, omitted
pairs, incompatible versions and invalid numeric values are provider contract
failures, not successful empty results. Omit the affected factor batch and
surface diagnostics; never insert a provider-supplied product into Search
results. Do not fetch profile features without current authorization/consent,
even if a provider would later return `denied`.

Use one bounded candidate page and batch feature reads. As proposed starting
limits, enable at most 16 factors over at most 100 candidates, with at most four
concurrent provider batches. Require explicit per-provider and overall
optional-evaluation deadlines in the serving bundle; select their values from
the query-latency budget before deployment. These are application limits, not
Azure quotas. Timeout contributes zero with a reason and no request-path retry
storm. A core optional-state-store outage preserves Search order as required
by the README; isolated factor failures leave other valid shares unchanged.

#### Storage, versions and rollout

Use a long-form **curated** analytical representation keyed by scope,
product/variant, factor/version and source-window/correction. Source raw tables
remain independent. Store compact nonpersonal product bundles in Cosmos keyed
by scope, product and `factorSetId`, not a single unversioned `current` map.
Bound bundle size and read only the factor set pinned by the request.

Within a bundle, compare source-window/correction ordering per factor and
conditionally merge changed entries with ETag retry; an inventory update
cannot overwrite newer revenue/trend entries. Identical-version conflicting
content is rejected. Publish explicit unavailable/retracted states and retain
durable high-water marks so old replays cannot resurrect them. Keep old/new
factor sets side by side during rollout and rollback; no transaction across
Cosmos and Search is assumed.

Add dedicated normalized Search fields only for approved `index-policy`
projections. Such a mapping declares its exact compatible profile, validation,
version diagnostics and indexed clearing behavior. Fields/profiles use a
validated rollout; pure `policy-hybrid` factors need no Search schema update.
Private/request-dependent results never enter global bundles or shared indexes.

The compiler validates a proposed policy against registered capabilities and
produces an immutable execution plan: factors, providers, data references,
budgets, privacy requirements, mode and index/profile identity. No weight
change requires recomputing source facts when definitions remain compatible.
Deploy provider readers first, prepare/backfill versioned inputs, verify
readiness, then shadow-evaluate before activating the plan. Activate the
scope-bound pointer conditionally and pin it once per request.

Rollback selects the previous still-valid plan **and** its compatible data,
not just old weights against a new normalizer. Retire a factor by activating a
policy that omits it; retain its definitions/data until referencing policies,
in-flight requests and any ranking cursors expire. Then stop production and
clean up authorized projections. Emergency revocation overrides cached plans:
disable its contribution without redistributing weight, record the revocation
version, and invalidate affected ranking snapshots/caches.

#### Worked extension: seasonal affinity

After the framework exists, add a nonpersonal `seasonalAffinity` dimension
without editing the composer. Illustrative definition (not a deployed schema):

```json
{
  "schemaVersion": "factor-definition-v1",
  "factorId": "seasonalAffinity",
  "version": "v1",
  "owner": "commerce-search",
  "description": "Match approved catalog season tags to the retailer season.",
  "providerRef": "catalog-tag-match/v1",
  "featureRefs": ["catalog.seasonTags/v1", "context.retailSeason/v1"],
  "normalizationRef": "binary-membership/v1",
  "evaluationScope": "request",
  "servingModes": ["policy-hybrid"],
  "resultContract": "effective-signed-v1",
  "privacyClass": "nonpersonal",
  "evidenceFamilies": ["catalog-season"],
  "excludes": [],
  "freshnessPolicyRef": "valid-until/v1",
  "maxAgeSeconds": 86400,
  "maxContributionCeiling": 0.03,
  "failurePolicy": "omit-with-diagnostic"
}
```

1. Populate approved season labels in the versioned catalog projection and a
   server-derived retail calendar for the authorized market. Neither feature
   nor `catalog-tag-match/v1` is implemented today; introduce the evaluator
   once with tests, then reuse it for supported tag-match dimensions.
2. Normalize both vocabularies. Return `1` for a match and `0` for a known
   non-match; absent catalog/calendar data returns `missing` with `null`.
   The binary provider has no additional confidence/decay multiplier; expiry
   is the earlier of input validity and the configured age limit. No shopper
   location or per-customer data is required.
3. Register a new immutable factor set containing this definition and the
   prior factors. Clone the viral-led policy into a new version, pin the new
   `factorSetId`, set `viralTrend` weight to `0.40` and append the entry below,
   keeping weight total `1.00` and the global cap `0.15`. Scope, effective dates
   and approval belong to the policy bundle.

```json
{
  "id": "seasonalAffinity",
  "version": "v1",
  "weight": 0.10,
  "maxContribution": 0.02
}
```

4. With `effectiveValue=1`, the seasonal contribution is `0.015`; no-match or
   missing contributes zero, with different statuses. Shadow-test the new
   bundle against the old one, canary the approved policy, then promote or
   roll back. Registry addition alone must leave existing results unchanged.
   No Search schema, public Search/Beacon contract or core composer change
   is required for this request-time factor.

## 4. Search and browse serving

### 4.1 Configuration dimensions

Keep these independent:

| Dimension | Initial value | Later alternatives |
|---|---|---|
| Retrieval | Keyword search. | Keyword/vector hybrid, optional semantic reranking, exact-identifier path. |
| Trend mode | Baseline, index-only or index/live hybrid comparison. | Same validated signal lifecycle under expanded retrieval modes. |
| Factor policy | Trend-only while Stage A is proven. | Versioned index-policy or policy-hybrid bundles combining viral, behavior, inventory, revenue/commercial and merchant factors. |
| Commerce policy | Required eligibility only for controlled POC comparisons. | Merchant controls, browse policy and explicit sort. |
| Learned/personal mode | Disabled. | Evaluated task-specific ranking and request-scoped consented preference factors. |
| Interface | Direct product results. | Guided facets or conversational wrapper using the same authorized APIs. |

Native hybrid retrieval uses reciprocal rank fusion; it is not the live-store
hybrid. Semantic ranking considers only the top 50 candidates and needs
appropriate text. Do not blend semantic scores for 50 products with unrelated
unreranked scores for another 150 as if they were one calibrated score family.
Initially restrict a semantic reranking experiment to its evaluated semantic
candidate set.

When semantic scoring profiles apply, use the effective response order and
configured score selection, including `@search.rerankerBoostedScore` where
applicable. Agentic retrieval is not a transparent replacement for direct
index queries with these scoring profiles.
[Hybrid retrieval](https://learn.microsoft.com/azure/search/hybrid-search-overview);
[semantic ranking](https://learn.microsoft.com/azure/search/semantic-search-overview);
[scoring-profile behavior](https://learn.microsoft.com/azure/search/semantic-how-to-enable-scoring-profiles).

### 4.2 Request sequence

```mermaid
sequenceDiagram
    participant UI as Storefront
    participant API as Commerce API
    participant Policy as Active policy
    participant Search as Azure AI Search
    participant State as Serving state
    participant Beacon as Beacon
    UI->>API: Query or category, refinements, caller context
    API->>API: Authenticate, authorize scope, validate constraints
    API->>Policy: Resolve immutable active bundle
    Policy-->>API: Index, rules, factors, weights and experiment versions
    API->>Search: Authorized filters and bounded retrieval
    Search-->>API: Candidates, facets, order and indexed factor versions
    opt Factor policy or live/learned mode enabled
        API->>State: Bounded batch read
        State-->>API: Versioned values or explicit failure
    end
    API->>API: Validate eligibility, versions and ordering policy
    API-->>UI: Results, attribution and degraded-mode metadata
    UI->>Beacon: Actual exposures and subsequent interactions
```

Detailed ordering:

1. Authenticate caller and authorize retailer/collection. Derive effective
   scope from server-side identity, not an untrusted body/header alone.
2. Validate the query, allowed refinement fields, market/currency, size and
   request limits. Translate a validated filter structure; never concatenate
   arbitrary client/model text into an unrestricted filter expression.
3. Resolve an immutable compiled serving plan and stable experiment assignment.
   Pin its versions, authorized context and request time; check revocations.
   Apply authorized linguistic controls.
4. Apply mandatory catalog, policy, stock/market and user-selected constraints
   in Search retrieval. Validate redirect rules separately; an invalid or
   disallowed redirect must not become an open redirect.
5. Retrieve a bounded candidate set and needed indexed factor metadata.
   Search failure is an error, not successful empty results.
6. If enabled, batch-read compatible live product factors and authorized
   consented profile state. Validate scope, factor/normalizer versions, finite
   bounds, source times, freshness and expiry. Evaluate registered providers
   within the plan's batch/deadline budgets and validate their result contracts.
7. Revalidate any current commerce facts promised by this experience.
   Remove now-ineligible candidates; do not insert products that Search did
   not return. Return fewer results with explicit metadata if needed.
8. Combine the providers' effective values once under the selected policy and
   caps, then apply eligible pin constraints when allowed. Preserve original
   order and product key for deterministic ties. Use the separate delta-only
   algorithm instead when the plan selects an existing trend mode.
9. Return products, facet/count semantics, configuration version, scoped
   attribution and permitted degradation metadata. Do not expose raw profiles
   or internal score evidence to unauthorized clients.
10. Record actual displayed exposures separately through Beacon.

### 4.3 Ranking and factor guardrails

For Stage A and existing trend modes, retain the
[existing ranking specification](option-c-hybrid-detailed-design.md#9-search-and-re-ranking-algorithm):
the canonical `[0,100]` trend score, `1:2:3` behavioral starting weights,
`alpha=0.5`, compatible state versions and bounded incremental adjustment.
Compare live state with indexed values **returned by Search**, not the last
accepted write. Equal snapshots add no trend boost; negative deltas support
decay. The rank-based heuristic does not algebraically undo Search boosting.

Do not add raw trend, model probabilities or recommendation scores to BM25,
RRF or semantic scores. New models need a separately versioned/calibrated
ordering policy and evaluation. Audit feature ownership so a learned model
does not consume trend features and then unintentionally apply the same trend
again through a profile and live adjustment.

For the three-mode benchmark, hold eligibility, query, catalog, candidate
budget and non-ranking configuration constant. Baseline disables optional
trend, personalized and merchant ranking boosts; no default scoring profile
may accidentally activate them. Diagnostic metadata is required for degraded
responses.

"Slight boost" is an evaluation constraint, not a fixed multiplier claim.
Keep the magnitude scoring profile opt-in, start with a low configured lift,
and tune it against a frozen judged query set. Record rank deltas by query
cohort and reject a policy that lets trend routinely displace clearly more
relevant products. The API-side live delta remains capped; explicit sorts,
filters, stock, policy and candidate eligibility always win. Index-only
profile tuning and API-side caps are separate controls and must be evaluated
independently.

For multi-factor policies, use the
[bounded composition](#34-generalized-multi-factor-ranking-policy) and
[extension contract](#35-adding-a-dimension-without-changing-the-ranking-core).
Never combine the full API factor policy with an indexed profile or the
legacy delta algorithm. Keep per-factor and combined caps, relevance floor and
maximum rank movement independently configurable within approved ceilings.
A missing optional factor contributes zero with diagnostics and no weight
redistribution; missing mandatory eligibility data follows its failure policy.

### 4.4 Browse, facets, suggestions and pagination

- **Browse:** use a category/collection-constrained query and a documented
  deterministic business order first. Add measured aggregate/learned browse
  ranking later. Do not invent text relevance for a match-all query.
- **Explicit sort:** price/date/user-selected field order takes precedence
  over optional ranking. Disable all optional factor adjustments and pins that
  would contradict it; retain mandatory exclusions and stable key ties.
- **Facets:** initially use Search's query-dependent buckets with a declared
  scope. Label them as retrieval counts; downstream current-stock validation
  can make displayed-result counts differ. Do not promise exact current
  availability counts unless computed with the same eligibility snapshot.
  OR within a selected attribute and AND across attributes is a proposed
  native-platform convention, not a reinterpretation of the legacy draft.
- **Learned facets:** learn which permitted fields/questions to present from
  actual usage, while native Search still computes eligible bucket values.
  Start with configured one-level facets; preview advanced facets are optional.
- **Suggestions:** native product-prefix completion first; a later separate
  query-suggestion index contains curated, sufficiently supported historical
  queries, locale, popularity and validity. Exclude PII, unsafe/rare queries
  and queries with no eligible results. Preserve prefix fallback when the
  learned dataset is absent, with its source identified.
- **Pagination:** keep the POC single-page. Stage B multi-page custom ordering
  requires a fixed ranking snapshot and opaque signed cursor bound to
  scope/query/filters/policy, with expiry and current-eligibility rechecks.
  No fresh independent rerank for each offset page. Expired snapshots produce
  an explicit restart response; do not silently substitute new ordering.

Current facts and exact-price promises require an available authoritative
source or a validated freshness policy. If that condition cannot be met, do
not label products as confirmed purchasable or fabricate a price.

## 5. Merchant policy and administration

Treat the merchant workbench as a first-class **custom** capability. An Azure
portal and a collection of scoring profiles do not provide it.

### 5.1 Rule precedence

Proposed Stage B precedence, evaluated against one policy version:

1. Authorization, legal/catalog exclusions and current eligibility.
2. User refinements, category/market scope and validated linguistic policy.
3. Approved redirect, if allowed for this query/context.
4. Explicit user sort, when supplied.
5. Otherwise the configured relevance/browse/learned ordering with bounded
   business, trend and consented-profile contributions.
6. Eligible pin placement, only when compatible with the chosen sort mode.

No boost/pin may undo an exclusion, widen a selected filter or create a
product outside the retrieved candidate set. A missing pinned product is a
visible rule non-application reason, not an invitation to fetch an unrelated
item. This is a deliberate limit versus broader pinning expectations.

Reject conflicting pins or invalid ranges at policy publication. Resolve
overlapping nonconflicting rules by explicit priority and stable rule ID.
Do not rely on database enumeration order. Limit compiled rule size and
candidate operations; the exact limits must be configured and load-tested.

### 5.2 Lifecycle

`Draft -> Validated -> Previewed -> Approved -> Active -> Retired`

- Merchandiser authors synonyms, facet choices, factor weights/caps, boosts,
  exclusions, pins, redirect targets, time windows and approved clarification
  questions.
- Validator checks referenced catalog fields/products, allowed actions,
  registered factor/provider/feature versions, weight/cap and execution bounds,
  dependency cycles, evidence overlap, consent requirements, conflicting pins,
  redirect hosts and effective market/scope. Unknown definitions or unsupported
  execution modes block activation, even when a compiler could ignore them.
- Preview runs a judged query set against the draft and current policy and
  shows changed ranks, factor contributions, constraints and reason codes
  without exposing confidential values or personal preferences.
- A separately authorized approver activates an immutable policy bundle.
  Record actor, reason, version and activation/audit evidence.
- Reject activation until required indexes/models/artifacts are available.
  Use the reader-first, versioned-data rollout in section 3.5. Roll back the
  active pointer to a still-valid compatible plan and data on failure.
- Cached configuration has a validity deadline. A last-known-good version
  may be used only while valid; unknown mandatory eligibility policy fails
  closed. Do not silently use an empty ruleset.

Native synonym maps are referenced by index fields, not arbitrary per-request
policy bundles. If an experiment requires incompatible synonym maps, plan
separate index configurations or an explicitly tested application rewrite
strategy; do not pretend version metadata makes mutable shared maps isolated.

## 6. Event, feature and score lifecycle

Retain [Option C](option-c-hybrid-detailed-design.md) and the
[two-stream contract](eventstream-ingestion-design.md), including:

1. Source-specific validation/rejection, behavior event deduplication before
   item expansion, and external latest-revision resolution before eligibility.
2. Whole attribute predicates: blue AND jackets, not independent boosts for
   blue products and jackets.
3. Per-source readiness and watermarks. Idle external input is not failure;
   missing behavior is not a zero-activity feature. New inputs for a previous
   window require a correction/input-set revision.
4. Coalesced scheduled/Activator triggers by scope, window and scoring policy;
   cooldown/concurrency limits, not one notebook or job per click.
5. Immutable feature artifacts and an explicit ML-identity read check.
6. Durable submission intent and stable job identity; reconcile an ambiguous
   submission before retrying.
7. Scheduled terminal-state reconciliation. Success, failure, cancellation,
   timeout and unknown status have explicit outcomes; the notebook need not
   remain running.
8. Artifact validation and independent Search/live-store publication results.
   Retry publication from the artifact without recomputing the ML job.
9. Ordering by feature window and correction/policy semantics, not job finish
   time. Cosmos uses conditional ownership/writes; Search publishing is
   serialized/coordinated with latest-desired-state repair after ambiguous
   outcomes, not assumed per-document compare-and-set.
10. Clock-driven expiry and clearing of previously boosted Search documents.
    Do not refresh `lastTrendingAt` merely because a job ran.

Extend the same version/readiness discipline to aggregate product factors
without mixing their semantics. Revenue, commercial value and inventory each
retain their own source watermark, correction version, normalization window
and expiry. Publish a factor snapshot only when its required sources are ready;
do not turn a missing revenue feed into zero revenue or stale inventory into a
current signal. Personalized factors are calculated at serving time from
authorized profile state and are not added to shared feature artifacts.
Use the per-factor conditional publication and side-by-side factor sets in
section 3.5; do not replace the whole serving map when one new source updates.

Activator's Run Notebook action is documented; parameter passing is preview.
Validate actual parameter types and values at notebook entry. Use fixed,
validated configuration plus the durable ledger or the periodic route if
preview parameters are not approved. No guessed alert payloads or silent
numeric/boolean defaults.
[Official action guidance](https://learn.microsoft.com/fabric/real-time-intelligence/data-activator/activator-trigger-fabric-items)

Behavior starts with periodic feature runs. External qualified hints can
trigger the notebook but must wait for corresponding Eventhouse readiness.
An Eventhouse aggregate does not automatically feed an Activator rule:
explicitly configure the selected feed/query path and measure its cadence.

Training is a separate workload from routine scoring. Admit training only
after readiness checks and evaluation definitions exist. Keep its compute and
concurrency budget from starving score publication.

## 7. Recommendation and learned-ranking extensions

### 7.1 Batch-first architecture

Begin with reproducible non-personalized lists and transparent baselines:
catalog-similar products, sufficiently supported co-view/co-purchase lists and
category popularity. Azure ML jobs can later train task-specific models and
publish versioned outputs to a **separate recommendation container**, not the
canonical product-trend field.

For query-conditioned learned ranking, Search still retrieves candidates.
A custom model operates only on those eligible candidates under an explicit
feature/ordering contract. Precomputed global scores alone do not reproduce
query-conditioned ranking.

For a standalone recommendation endpoint, the approved task defines its own
candidate generator. Batch-hydrate/filter those candidate IDs through the
catalog/Search eligibility path. This is not permission to inject recommended
products into an unrelated Search result.

```mermaid
flowchart LR
    HIST["Consented, deduplicated history and catalog"]
    DATA["Point-in-time training/evaluation datasets"]
    TRAIN["Azure ML task-specific training"]
    EVAL["Quality, safety and coverage gates"]
    REG["Approved immutable model/policy"]
    SCORE["Batch candidate generation and scoring"]
    LISTS[("Versioned recommendation lists")]
    REQ["Authorized recommendation request"]
    CHECK["Current eligibility and deduplication"]
    OUT["Products, task/version and fallback reason"]
    HIST --> DATA --> TRAIN --> EVAL --> REG --> SCORE --> LISTS
    REQ --> LISTS --> CHECK --> OUT
```

This diagram describes custom orchestration, not a prebuilt Azure recommender.
Training success does not activate a model. Validate outputs and use the
durable publication/recovery discipline from the POC.

### 7.2 Task-specific progression

| Task | Baseline | Later learned capability / key gate |
|---|---|---|
| Similar products | Catalog attribute similarity. | Evaluated embeddings/multimodal similarity; compatible model/vector versions and relevance judgments. |
| Others you may like | Co-view lists with support thresholds. | Context/sequence models; next-item metrics without time leakage. |
| Frequently bought together | Deduplicated basket associations. | Complement ranking; exclude duplicate variants and account for order reversals. |
| Recommended for you | Explicit non-personalized fallback. | Consented profile/session modeling with sufficient support and privacy checks. |
| Buy again | Eligible purchase-history rules. | Recurrence model for suitable products; never assume every fashion item is replenishable. |
| On-sale | Promotion-valid category lists. | Consented promotion ranking; authoritative price/market/date checks. |
| Recently viewed | Bounded ordered history. | No model necessary; profile scope, expiry and deletion tests. |
| Panel orchestration | Fixed panels, duplicate suppression. | Evaluated panel selection/order; actual panel exposures and bounded fan-out. |

Define each objective independently: next click, purchase, complement
relevance or repeat purchase. Do not interpret a click probability as expected
revenue or optimize margin without an approved business policy.

Use temporal train/validation/test separation, point-in-time catalog and
features, exposure-aware negatives and cohort support reports. Treat position
bias, feedback loops, bots and missing events as model-quality risks. A more
complex model is promoted only when it improves declared metrics without
violating eligibility, diversity or serving-cost guardrails.

### 7.3 Fallback and optional online serving

Missing/expired model lists may use an explicitly configured, eligible
non-personalized baseline with `fallbackReason`. A valid list with no eligible
products can yield an explicitly empty recommendation panel; a dependency
failure is not silently classified as "no products."

Do not manufacture "because you liked..." explanations on fallback.
Recommendations must not prevent core search from serving when their optional
dependency fails.

Introduce an Azure ML online endpoint only if batch/context features miss a
measured requirement. Design feature retrieval, capacity, request deadline,
circuit breaking, shadow evaluation and fallback separately.
[Online versus batch inference](https://learn.microsoft.com/azure/machine-learning/concept-endpoints?view=azureml-api-2)

## 8. Governed conversational discovery

Use the existing Search/Recommendation APIs as validated tools rather than
granting an LLM direct database queries or broad catalog mutation permissions.
Start with approved facet questions before generating free-form conversations.

Proposed interaction:

1. Authenticate/scope the session and load only permitted, unexpired context.
2. Extract a proposed intent and structured constraints from the shopper text.
3. Validate constraint names/types/ranges against a catalog vocabulary;
   preserve explicit shopper restrictions and clarify conflicting constraints.
4. Call the same authorized Search/Browse or Recommendation API. A model cannot
   invent a retailer scope, bypass stock/market restrictions or widen filters
   without a clear shopper decision.
5. Generate an answer using only returned product IDs and current validated
   facts. Comparisons link back to catalog products and evidence fields.
6. Validate generated product references and material claims. Reject invented
   prices, discounts, stock, attributes or product IDs.
7. If facts are insufficient, ask a grounded clarification or show the
   deterministic result list with an explicit generation failure/degradation.
   If Search itself fails, surface the error rather than a fabricated answer.

Use structured output/tool schemas where the selected model/API supports
them. Schema validation is not factual validation. Treat descriptions,
supplier text, reviews, external signals and tool responses as untrusted
content, not instructions. Evaluate prompt injection, harmful text, irrelevant
answers and unauthorized tool requests with application-level enforcement
plus supported safety features.
[Structured outputs](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/structured-outputs);
[Prompt Shields](https://learn.microsoft.com/azure/ai-foundry/openai/concepts/content-filter-prompt-shields).

Set explicit configurable limits on turns retained, tokens, tool fan-out,
candidate payload, request time and cost. Select the exact model/version,
API, deployment type, region and retention settings before implementation;
preview models/features need a separate approval and exit path.

Optional image-led discovery requires a validated model and versioned catalog
image representations. Do not infer searchable image embeddings from the
existing optional image-generation workflow.

**No transactional tools:** no add-to-cart, payment, checkout, loyalty mutation
or purchase commitment in this design. A later extension needs explicit user
confirmation, backend authorization, idempotency and transaction audit.

## 9. API evolution and client behavior

| Surface | Proposed evolution | Compatibility boundary |
|---|---|---|
| Search | Existing endpoint plus a separately reviewed versioned capability plan for browse, policy and diagnostic metadata. | Do not silently change provider-facing response names or refinement semantics. |
| Beacon | Existing event names normalized internally; future exposure/panel/filter/outcome schemas. | Distinguish client observations from backend-confirmed orders; explicitly negotiate new event versions. |
| Suggestions | Separate read operation for prefix/product or curated-query suggestions. | Return suggestion type and safe filter intent; selecting a suggestion is not proof of purchase intent. |
| Recommendations | Separate task/context operation with bounded result count and scoped attribution. | Recommendation candidates do not replace the Search candidate contract. |
| Merchant administration | Authenticated draft/preview/approve/publish/rollback operations. | Never expose administrative credentials or rules mutation to shopper clients. |
| Conversation | Separate session/turn interface wrapping discovery tools. | Preserve direct non-generative search; session IDs are not authority. |

These are conceptual surfaces, not new committed endpoint paths. Extend the
OpenAPI drafts only in a dedicated contract task once behavior, defaults,
limits, ingress trust and client migration are agreed.

Browser clients must not receive backend keys, Fabric source credentials,
Search administrative credentials or model credentials. Resolve CORS and
browser event transport deliberately; the service name Beacon does not
guarantee compatibility with `navigator.sendBeacon()`.

## 10. Identity, privacy and future tenant isolation

### Single-retailer starting point

- Separate development/test/production resources and synthetic fixtures.
- Use Entra identities and least-privilege roles where supported. Validate
  notebook-to-ML, ML-to-artifact, publisher-to-Search/Cosmos and producer-to-
  Eventstream access independently.
- Separate source credentials and restrict writes by component ownership.
  Prefer managed identity; approved unavoidable secrets live in Key Vault.
- Resolve authorized collection/market scope server-side. Public customer IDs
  and anonymous visitor IDs are claims, not access control.
- Enforce browser abuse controls and trusted-backend validation for events
  used as financial or recommendation labels.
- Treat pseudonymous histories as privacy-sensitive. No secrets, raw personal
  queries or unnecessary profiles in logs or notebook outputs.

### Consented state

Before enabling personalization, define lawful basis, purpose and retention
with the retailer. Provide an unpersonalized path; withdrawal disables use of
profile features at serving and ingestion, not just in the UI.

Track deletion/withdrawal through raw events, features, history stores,
recommendation lists, conversation state and retained training artifacts.
Document how already-trained models are handled, including retraining or
unlearning decisions where required; do not promise instant removal from
weights. Legal retention exceptions require an explicit policy.

Treat favorite colour, size, category and inferred affinity as profile data,
not harmless catalog metadata. Record whether each preference was explicit or
inferred, its confidence, purpose, source time and expiry. Do not infer a
sensitive trait from fashion preferences, use profile factors outside their
consented purpose, or persist per-customer factor contributions in Search,
Eventhouse aggregate tables, shared caches or general telemetry.

An Entra OAuth consent grant authorizes API access; it is not sufficient
evidence of shopper tracking/personalization consent.

### Future SaaS boundary, not an onboarding implementation

Carry authorized retailer/collection scope through keys, ledgers, artifacts,
policies, quotas, caches and diagnostics now. Later compare index-per-tenant
with service-per-tenant isolation, limits, noisy-neighbor exposure and cost.
[Microsoft multitenant Search patterns](https://learn.microsoft.com/azure/search/search-modeling-multitenant-saas-applications)

Do not silently convert the POC to a shared multi-tenant index. Shared
resources require tested enforcement; separate indexes alone do not grant
shoppers authorization. Training data, model artifacts and serving lists must
not mix merchants unless separately authorized.

Cache keys must include effective scope, locale/market, query/filters, policy,
retrieval mode and relevant consent/profile context. Disable shared
personalized-response caching; never replay another visitor's attribution
token. Aggregate caches also need freshness/version and invalidation rules.

## 11. Failure handling and operations

| Condition | Required serving or pipeline outcome |
|---|---|
| Search unavailable/timed out | Explicit service error; no fabricated empty success or LLM-invented products. |
| Core optional state store unavailable | Preserve returned Search ordering without optional re-ranking; report degraded mode and age/reason. |
| Unknown/incompatible indexed or live version | Skip optional adjustment with a diagnostic; do not guess the indexed score. |
| Mandatory policy unavailable/expired | Fail closed; a still-valid approved bundle may be used with explicit version/degradation. |
| Price/stock authority unavailable | Apply the declared freshness policy; suppress unsupported current-fact claims or fail the operation if current eligibility is mandatory. |
| ML submission uncertain | Reconcile durable submission/job identity before creating another attempt. |
| Job failed/cancelled/timed out | Mark ineligible for publication; retain prior valid output only until its own expiry. |
| Invalid artifact or older completion | Reject/quarantine with reason; never publish because completion was recent. |
| Partial Search/Cosmos publication | Track destinations independently and retry from validated artifacts under latest-state ownership. |
| External signal idle or retracted | Distinguish healthy idleness from outage; resolve latest revision and clear affected boosts. |
| Individual optional factor stale/unavailable | Set only its contribution to zero with a reason; keep the configured denominator and other valid shares unchanged. Never reuse it beyond expiry. |
| Required stock/eligibility authority stale or unavailable | Fail or suppress current-availability claims according to the mandatory freshness policy; never reinterpret it as an optional factor outage. |
| Profile absent, stale, unauthorized or consent withdrawn | Zero personal contributions without redistributing their weights; prevent personalized cache reuse and do not reveal profile existence or preference values. |
| Factor/policy/normalizer version mismatch | Skip the incompatible optional contribution and emit diagnostics; reject policy activation if the incompatibility is known in advance. |
| New provider returns invalid values/keys or exceeds its deadline | Omit the affected factor batch with an explicit contract/timeout reason; do not silently repair values or retry per candidate. |
| Factor revoked or rollout fails | Enforce revocation on cached plans; invalidate affected snapshots and roll back to a compatible approved plan/data set. Do not redistribute the disabled factor's share. |
| Recommendation list absent/expired | Declared eligible baseline or explicit unavailable panel; record fallback, not synthetic personalization. |
| Learned suggestions absent | Labeled product-prefix completion if its dependency is healthy. |
| Conversation/model failure | Explicit deterministic discovery fallback if Search succeeded; otherwise a real error. |
| Rate/capacity pressure | Bounded backoff and admission control; shed optional work before core search and never retry indefinitely. |

### Telemetry and recovery

Trace authorized scope, correlation/event IDs, catalog/feature/policy/model
versions, job IDs/status, destination outcomes and sampled rank changes.
Record:

- Event occurrence to ingestion and Eventhouse visibility.
- Feature-window readiness and notebook queue/startup.
- ML queue/provisioning, execution and reconciliation delay.
- Publication acceptance and actual query visibility.
- Search, state reads, hydration, reranking, recommendation and conversation
  latency separately, with p50/p95 and sample counts.
- Active policy/factor/normalizer versions, per-factor availability and
  freshness, provider latency/budget violations and cap/relevance-floor
  reasons. Sample nonpersonal contributions and pre/post rank only under the
  declared diagnostic privacy policy; do not log personal contributions,
  customer preference values or confidential revenue/margin facts.
- Source health, stale-state ratios, invalid artifacts, fallback/error rates,
  cost drivers and retry amplification.

Use bounded-cardinality metrics and sampled redacted traces. Keep an auditable
control history without turning raw shopper text into metric dimensions.

Rehearse rebuilding indexes/live lists from durable catalog and validated
artifacts, restoring run/publication ledgers, replaying events without double
counting, and rolling back model/policy versions. Define RPO/RTO with the
retailer before production; none is established by this blueprint.

### Deployment feasibility

Before deployment, choose and record:

- Region/residency, data retention, supported model and non-preview/approved
  preview features.
- Search tier, Functions hosting/networking, Cosmos capacity/partitioning,
  Fabric capacity and ML compute quotas.
- Identity and network connectivity for each integration; private endpoints
  do not automatically make cross-service notebook access work.
- Owner, budget, environment boundaries, recovery and teardown procedures.

Bicep covers supported Azure resources. Use supported Fabric APIs or explicit
manual setup/exports for Fabric items; do not invent ARM types or deployment
support. No resources are authorized by this design document alone.

## 12. Phased delivery and acceptance

Delivery planning and acceptance gates live here, not in the repository guide.

| Stage | Dependencies and deliverables | Exit evidence |
|---|---|---|
| **A: prove the existing POC** | Catalog/index setup, validated two-stream ingestion, synthetic TikTok-like metadata extraction and vocabulary mapping, deterministic aggregation, index-side expiry, then ML lifecycle and live delta. Verify notebook-to-ML permissions, feature/output access, and reproducible setup/cleanup. | Same query/filters/catalog before/during/after SKU and compound-attribute spikes in all three modes; extraction fixtures, conjunction matching, deduplication, score bounds, stale-job prevention, partial-write recovery and outage behavior verified. Report actual latency against existing targets. |
| **B: commerce search foundation** | A provides a trusted baseline. Add variant-correct catalog projection, browse/sort/facets, native suggestions, the factor/provider contracts, nonpersonal revenue/inventory factors, merchant weight/cap controls and contract evolution. | Judged retrieval set; zero hard-filter/variant violations; extension tests in section 12.3 including a new dimension without composer changes; viral-led/revenue-led preview comparison; safe redirects; compatible policy/data rollback and stable paging within a bounded snapshot. |
| **C: learning and recommendations** | B plus exposure/outcome schemas, readiness dashboard and point-in-time data. Build transparent recommendations, learned suggestions/facet selection, then evaluated recommendation/query-ranking models. | Task-specific held-out metrics beat the registered baseline without violating coverage/eligibility/cost guardrails; no future-data leakage; cold-start and partial-publication tests pass. Synthetic evaluation is labeled synthetic. |
| **D: personalization and conversation** | C plus privacy/consent/deletion policy, sufficient authorized histories and exact supported model/API selection. Add request-scoped preference factors, scoped profiles, guided discovery and grounded conversations. | Explicit filters override preferences; same-variant size checks, unpersonalized fallback, no unauthorized cross-profile use and withdrawal are verified; generated product/fact validation, prompt-injection and model-outage tests pass; deterministic search remains independently available. |
| **E: production hardening and expansion** | Prior capability gates plus real workload, region/SLO and budget decisions. Load/soak tests, edge/network controls, operational ownership, recovery and optional SaaS architecture. | Measured peak/steady latency and costs, incident/restore/rollback exercises, agreed SLOs and documented residual gaps. Multi-tenant onboarding or transactional agents require separate design approval. |

Operational correctness must be built with each stage; Stage E is production
qualification, not permission to defer authentication or data correctness.
Semantic/vector and image experiments fit B/D only after keyword baselines
exist and have an evaluation need. Model complexity is not itself an exit gate.

### 12.1 Evaluation protocol

Maintain immutable evaluation manifests: catalog seed/version, query set,
labels, event scenarios, policy/model versions, request counts and run identity.
Include exact SKUs, head/tail queries, synonyms/typos, compound attributes,
category browse, price/size constraints, no-result queries and supported
locale examples.

| Area | Proposed measurement | Acceptance rule |
|---|---|---|
| Retrieval | Recall@50 for the semantic candidate experiment; NDCG@10 for judged first-page ranking, with counts and query cohorts. | Register baseline and non-regression threshold before tuning. Do not claim superiority without identical eligible data and a frozen holdout. |
| Hard correctness | Product/variant filter checks, authorization, price/market consistency, duplicate IDs and expired-state use. | Zero violations in the acceptance fixtures; investigate every production violation rather than averaging it into relevance. |
| Trend POC | Before/during/after movement, equal-state no-double-boost, expiry, ties and duplicate/late/retracted events. | Preserve current deterministic invariants and report misses against the README targets. |
| Multi-factor policy | Normalization/freshness/availability, weight/cap sensitivity, rank movement, relevance loss and stock/revenue cohort metrics. | Verify expected individual contributions before caps, saturation at caps and fixed-denominator failure behavior; do not promise monotonic final rank under competing factors. No double application or constraint breach; commercial lift requires a controlled real experiment. |
| Personal factors | Explicit-versus-inferred preference conflicts, consent/withdrawal, profile outage, same-variant size availability, cache separation and cohort quality. | Explicit intent always wins; unauthorized/stale state contributes zero; zero cross-profile/cache leakage in fixtures; report quality and coverage by consented cohort. |
| Recommendations | Recall@10/NDCG@10 by task, catalog coverage, diversity, valid-list rate and cold-start cohorts. | Improve the declared task baseline without introducing ineligible items or unsupported personalized claims. |
| Conversation | Valid product-ID rate, grounded price/attribute checks, clarification/task completion, refusal/error/fallback rate and adversarial scenarios. | Zero invented IDs/prices in the release fixtures; all unauthorized tool attempts denied; report measured grounding failures, not a blanket safety guarantee. |
| Latency/freshness | End-to-end and per-stage p50/p95, sample count, errors and cold/warm cases. | POC retains its 1-5 minute index-side target and other existing budgets. Production SLOs require workload approval; job freshness is not online latency. |
| Economics | Full infrastructure cost per 1,000 completed discovery requests, plus training and engineering cost reported separately. | Budget agreed before deployment; include idle capacity, optional model calls, retries and peak-load headroom. |

Metrics with a cutoff use fewer results when the eligible set is smaller;
record that denominator and the fraction of affected cases. An empty judged
set is not a perfect score.

### 12.2 Experiments and commercial evidence

Use stable, scope-bound assignment at the chosen shopper/session unit. Record
assignment, actual exposure, policy/model version and outcomes separately.
Feature-flag evaluation telemetry alone does not prove that a recommendation
was seen.
[Feature-flag telemetry](https://learn.microsoft.com/azure/azure-app-configuration/howto-telemetry)

Before a real experiment, preregister its primary metric, attribution window,
sample-size/power assumptions, stopping rule and guardrails. Inspect assignment
imbalance, bot traffic, novelty effects, page latency and category cohorts.
Do not stop at the first positive result or substitute revenue forecasts for
observed incremental revenue.

The synthetic POC can validate experiment plumbing, not conversion or revenue
lift. A Google comparison needs an authorized comparable test environment,
identical catalog/query eligibility and documented configuration/readiness
differences; no provider resources are assumed available here.

### 12.3 Dimension-extension acceptance tests

Implement these as offline contract and golden-ranking tests when scaffolding
the factor path; they are design requirements, not tests already in the
repository. Use a seeded catalog, fixed clock and immutable input manifests.

| Scenario | Required evidence |
|---|---|
| Add a registered dimension with an existing provider | Add `seasonalAffinity` through definition/data/policy only; no edits to the composer, Search index schema or public API. An unused registry entry changes no existing result. |
| Unsupported extension | Unknown factor/provider, unsupported mode/result version, missing typed feature, dependency cycle or excessive factor/batch budget blocks activation with a reason. No arbitrary code or URL in a policy is executable. |
| Weight, cap and missing-data arithmetic | Reproduce the viral/revenue and seasonal contribution examples in section 3.4-3.5. Missing season gives `0`, not a larger revenue share; a tighter contribution cap saturates even when weight increases. |
| Distinguish absence from zero | Known no-match is `valid/0`; absent input is `missing/null`; non-finite/out-of-range values, duplicate keys and omitted pairs yield a contract error. No stale or invalid output is treated as a successful measurement. |
| Confidence, decay and evidence counted once | Fixed-time fixtures prove one quality/decay application; `canonicalTrend` cannot coexist with either constituent. No Search profile plus full-factor application; equal legacy indexed/live snapshots still add no delta. |
| Concurrent publishers and schema evolution | Inventory update leaves newer revenue intact; older corrections and equal-version conflicts cannot win. Old and new factor sets coexist; rollback reads the matching normalizer/data rather than relabeling new data. |
| Availability and bounds | All factors unavailable preserves Search order with diagnostics; one failed factor does not redistribute weight. Core optional-store outage preserves order. Provider timeouts respect budgets and cause no per-product retry fan-out. |
| Membership, ties and movement | Zero/one/many candidates, ties, signed contributions, relevance floor and both rank-movement directions; output is a permutation of eligible candidates with no duplicates/cap breach. Explicit sort disables conflicting adjustments. |
| Profile/variant isolation | Missing consent prevents profile fetch/use; explicit colour/size wins; matching size and stock refer to the same eligible variant. Derived personal factors cannot be reclassified as global or cached across callers. |
| Activation, withdrawal and removal | Requests pin one plan during pointer changes. A never-enabled factor is inert; removal stops its use; emergency revocation overrides cached plans/cursors. Only unreferenced retired projections are cleaned up. |

Shadow and canary reports must include judged relevance, feature coverage,
factor timeouts, p50/p95 with sample counts, and policy/factor-set identity.
Enabling a new dimension is gated on those results; synthetic tests prove
mechanics, not sales lift or a cloud latency guarantee.

## 13. Cost model and open decisions

Estimate the composition, not only Azure AI Search. Use the
[research economics model](../research/09-google-commerce-search-azure-equivalence.md#economics-and-operating-comparison)
to capture:

- Search capacity and enabled semantic/vector-related processing/storage.
- Fabric capacity, event retention and always-active query/aggregation cost.
- ML training/scoring and optional online endpoint idle capacity.
- Functions, Cosmos reads/writes/storage, artifacts and telemetry.
- Optional embeddings/conversations, safety/evaluation, ingress and networking.
- Merchant UI/model lifecycle implementation and on-call ownership.

Report a workload-based range rather than choosing the cheapest isolated
service price. Existing enterprise capacity is not automatically free:
distinguish marginal spend from consumed capacity and opportunity cost.
The costing baseline is a supported Dedicated Search tier. The documented
Serverless Developer tier is preview with different compute/storage billing
and no preview SLA; it is not a production-default shortcut around capacity
planning. See [Search cost guidance](https://learn.microsoft.com/azure/search/search-sku-manage-costs).

| Open decision | Owner / evidence needed before implementation |
|---|---|
| Retailer catalog/market scope and peak workload | Product/platform owner; product/variant counts, QPS, update rates, locales and payloads. |
| Runtime/SDKs and hosting plan | Engineering; preserve existing generator tooling but choose service stack from supported versions and deployment needs. |
| Ingress trust and real event collection | Security/commerce owner; authenticated backend/browser design and authoritative outcome source. |
| Latency, freshness, availability, RPO/RTO | Product/SRE; measured POC and explicit production commitments. |
| Price/stock freshness and variant schema | Commerce/search owner; correlated eligibility fixtures and authoritative-source availability. |
| Consent, retention and deletion/model policy | Retailer privacy owner; purpose and lifecycle obligations, including later real-data use. |
| ML objective, features, model and promotion thresholds | Search/ML owner; readiness and frozen evaluations, not model-name preference. |
| Commercial ranking objectives and factor weights | Commerce/search owner; approved definitions for revenue, margin, inventory pressure, conflicts and experiment guardrails. |
| Generative model/API/region and preview appetite | Platform/security owner; supported capability matrix, evaluations and data terms. |
| Production edge, capacity and budget | Platform/SRE/finance; load measurements and dated regional pricing. |
| SaaS or transactional expansion | Separate product/security decision; not implicitly approved by this blueprint. |

## 14. Documentation and implementation handoff

Engineering tasks should follow the user's requested scope, formalize affected
contracts, and add implementation/tests using the repository's actual tooling.
Use the delivery guidance above when planning; do not scaffold all stages at once.

For capability evidence and known Google/Azure gaps, use the
[comparison and source register](../research/09-google-commerce-search-azure-equivalence.md#source-register).
For low-level trend, ingestion and publication contracts, use the existing
[Option C](option-c-hybrid-detailed-design.md) and
[two-stream](eventstream-ingestion-design.md) designs.

Keep proposed, implemented and measured status separate as work progresses.
Update install/run/test/demo/recovery instructions only when commands and
behavior exist and have been verified.
