# Google AI Commerce Search: an Azure equivalent

**Status:** Research and proposed expansion, not implemented parity

**Evidence reviewed:** 28 September 2026

**Companion:** [Azure commerce search platform design](../architecture/azure-commerce-search-platform-design.md)

## Executive recommendation

Build a **commerce discovery platform on Azure**, not a wrapper around Azure
AI Search presented as a complete replacement for Google's product.

Google combines catalog ingestion, search/browse, behavioral optimization,
recommendation models, merchandising controls and guided discovery in a managed
commerce offering. Azure supplies strong components, but the reviewed Microsoft
documentation does not establish one managed service with that whole commerce
feature set. The recommendation is:

1. **Azure AI Search** for product retrieval, filters, facets and native ranking
   mechanisms.
2. **Azure Functions and Cosmos DB for NoSQL** for the commerce serving layer,
   governed configuration, recommendation snapshots and existing live signals.
3. **Microsoft Fabric RTI and Azure Machine Learning** for the event-to-feature
   and reproducible training/scoring lifecycle.
4. **Custom commerce engineering** for merchandising policy, learned
   suggestions, recommendation objectives, personalization, experiments and
   merchant administration.
5. **Microsoft Foundry/Azure OpenAI**, only in a later phase, for grounded,
   read-only conversational product discovery.

Compete on demonstrated product discovery quality, control, integration and
operating economics. Do not claim equivalent proprietary models, Google API
compatibility, revenue lift, or lower cost without evidence.

The current [POC](../../README.md) remains the first delivery stage. Its
aggregate trend ranking is one capability in the larger platform, not a
substitute for search learning or personalized recommendations. Preserve its
index-side-first sequence and selected notebook-to-ML lifecycle.

## Scope and evidence method

The target is **one retailer first**, with documented future SaaS isolation
boundaries. This research covers the full commerce-search offering, including
recommendations and conversational discovery. Cart/checkout agents and
contact-center products are separate future extensions.

Sources are official Google and Microsoft documentation, release notes and
pricing material listed in the [source register](#source-register). Statements
about Azure application components below are **design proposals**, not claims
that those components already exist in this repository.

Evidence labels:

- **Native:** documented Azure service primitive; still needs configuration.
- **Composed:** native primitives plus application policy or data integration.
- **Custom:** capability/model/control plane the team must build and operate.
- **Gap:** no demonstrated drop-in match; quality or product behavior must be
  evaluated rather than asserted.
- **Conditional:** preview, allowlist, data readiness or deployment availability
  limits adoption.

Documentation review is not a tenant test, contractual SLA review or benchmark.
No Google or Azure resources were provisioned or invoked for comparison.

### Product names and boundaries

Google's release notes record the rename from **Vertex AI Search for commerce**
to **AI Commerce Search in Gemini Enterprise for Customer Experience** on
29 June 2026. Older URLs, APIs and resource names can retain Retail/Vertex
terminology. This comparison is not about the entire Vertex AI platform. [G07]

| Boundary | Evidence and interpretation |
|---|---|
| Core commerce search | Search, browse and recommendations share catalog and user-event ingestion. [G01], [G02] |
| Guided search | Conversational product filtering uses generated, merchant-controllable questions to refine discovery. It has data-readiness gates. [G06] |
| Conversational Commerce agent | Release history records GA on 3 September 2025. The linked implementation page returned 404 during this review; current API and entitlement details remain unresolved, not presumed preview. [G07] |
| Wider customer-experience suite | The suite markets a separate Shopping agent in preview, as well as customer-service products. Its cart/loyalty/checkout promises must not be counted as verified core search API features. [G08] |
| Proposed Azure platform | Functional commerce discovery composition, not a binary-compatible Retail API implementation or recreation of Google's internals. |

## Capability comparison

Delivery stages below refer to the companion design: **A** existing POC,
**B** commerce search and controls, **C** learned ranking/recommendations,
**D** consented personalization/conversation, **E** production expansion.
These are dependency stages, not release dates.

### Catalog, retrieval and merchant experience

| Capability | Google evidence | Azure mapping | Work, limitations and stage |
|---|---|---|---|
| Catalog, collections and variants | Product hierarchies, catalog ingestion and shared search/recommendation data. [G01], [G02] | Search indexes plus a catalog projection/adapter and authoritative commerce backend. [A01], [A07] | **Composed, A/B.** Define parent/SKU relationships, deletion reconciliation and inventory freshness. Search is not the system of record for price or checkout stock. |
| Text search and exact identifiers | Query/context understanding and configurable search behavior. [G02], [G03] | BM25/full-text retrieval, analyzers and exact-key filters. [A01] | **Native/composed, A/B.** Test identifiers separately from natural-language queries; preserve hard eligibility. |
| Conceptual, multilingual and visual discovery | Search languages and product-understanding claims do not reveal Google's internal retrieval algorithm. [G02], [G07] | Optional vector/hybrid retrieval and semantic ranking; embeddings or image-derived features require a separately selected model. [A01], [A02], [A13] | **Composed/gap, B/D.** Native multilingual primitives do not prove language or image-search parity. Benchmark each target locale and modality. |
| Query expansion, synonyms and typo handling | Expansion, relevance thresholds, synonym, one-way, ignore, replacement and do-not-associate controls. [G02], [G03] | Synonym maps, query parsing and optional semantic query rewrite. [A02], [A06] | **Native/custom, B.** Azure supports equivalence/explicit synonym mappings; do not assume all conditional linguistic controls are native. Semantic query rewrite is documented as preview. |
| Browse/category pages | Dedicated browse use case with data-dependent popularity/revenue ranking. [G02], [G09] | Filtered match-all retrieval with a defined deterministic or learned browse policy. | **Composed/custom, B/C.** An empty text query has no meaningful textual relevance ordering. Do not apply semantic ranking as if a browse category were a text query. |
| Filters and explicit sorting | Filter expressions and prioritized field ordering. [G02] | Search filters and field sorting. [A01] | **Native/composed, A/B.** Explicit price/date sort must not be silently reordered by trend or personalization. |
| Facet buckets | Facets over attributes; numeric buckets supplied in requests. [G02] | Native query-dependent facets, numeric intervals and application rendering. [A05] | **Native/composed, B.** Define count scope, variant correlation and selection semantics. |
| Learned dynamic facets and tiles | Automatic facet-key selection/ranking is documented as allowlisted. [G02], [G07] | Facets provide buckets; learned choice/order of facet fields and tile UX are custom. [A05] | **Custom/conditional, B/C.** Azure query-dependent buckets are not the same as learned facet selection. Richer hierarchical/filter/aggregation facet operations are documented as preview. |
| Autocomplete | Uploaded or automatically learned suggestions; controls and filtering of unsuitable queries. [G04] | Native index-field suggesters; a separate curated query index/pipeline for behavioral suggestions. [A04] | **Native/custom, B/C.** Product-prefix completion alone is not Google's query-learning loop. |
| Boost/bury and exclusions | Conditional controls, including query and active-time conditions. [G03] | Native scoring functions for supported fields plus a custom rule evaluator and filters. [A03] | **Composed/custom, B.** Bury is not exclusion; boosts do not imply an exact position. Recommendation boost/bury is documented as Public Preview by Google. |
| Pinning and redirects | Dedicated pin and redirect controls; pinning is not supported for recommendations. [G03], [G07] | Eligible-candidate pinning and allowlisted redirects in the commerce API. | **Custom/partial, B.** This design never inserts an out-of-candidate product to imitate pinning; record that deliberate limitation. |
| Merchant console and serving configs | Controls attach to serving configs; release notes document Creator/Approver roles, preview and explainability. [G03], [G07] | Versioned configuration in Cosmos DB plus custom administrative APIs/UI and audit. | **Custom, B.** Azure portal configuration is not a retail merchandiser workbench. |
| Pagination | Google exposes paging behavior. [G02] | Search paging, or fixed ranked snapshots with signed cursors for custom reranking. | **Composed, B.** Existing POC remains one page; bounded reranking is not globally correct ordering across the catalog. |

### Learning, recommendations and conversation

| Capability | Google evidence | Azure mapping | Work, limitations and stage |
|---|---|---|---|
| Aggregate popularity and trend response | Behavioral data contributes to search tiers and model optimization. [G02], [G09] | Existing Fabric features, deterministic score, Search profile and live delta. | **Custom, A.** This is explainable aggregate ranking, not learned revenue optimization. External trend adapters are an Azure design extension, not presumed Google feature parity. |
| Learned search/revenue ranking | Search tiers progress through relevance, popularity, revenue and personalized revenue. [G09] | Azure ML training/evaluation plus controlled serving over Search candidates. [A10] | **Custom/gap, C/D.** Semantic ranker is not trained on the retailer's clicks/purchases through event ingestion. A custom ranker must earn promotion against baselines. |
| Automatic retraining/tuning | Google describes merchant-specific recommendation models and daily retraining. [G02], [G05] | Versioned ML jobs, datasets, evaluation and promotion controls. [A10] | **Custom, C.** The team owns labels, scheduling, feature validity, drift and rollback. No managed AutoML recommendation task is assumed. |
| Personalized sessions/users | Search/browse and selected recommendations use visitor histories. [G02], [G05], [G09] | Consent-aware profile features, custom models and scoped serving state. | **Custom, D.** Anonymous aggregate service remains available without personalization. Identity hashing alone is not consent. |
| Recommendation families | Multiple models/objectives and serving configs. [G05] | Batch-generated candidate lists and later learned models hosted/operated through Azure ML. | **Custom/gap, C/D.** See the family-by-family mapping below. |
| Page-level optimization | Coordinates recommendation panels and returns configurations used for further predictions. [G05] | Custom panel selection, duplicate suppression, exposure logging and experiments. | **Custom, C/D.** Budget panel fan-out separately; a list of product IDs does not deliver whole-page optimization. |
| Guided questions | LLM-generated questions, manual overrides and readiness gates. [G06] | Start with approved facet-based questions; optionally generate drafts offline with merchant approval. | **Custom, B/D.** Deterministic clarification is useful before adopting a generative model. |
| Generative discovery and comparison | Guided search plus release-documented conversational agent; wider suite claims require entitlement verification. [G06], [G07], [G08] | Foundry/Azure OpenAI with typed discovery tools and factual product grounding. [A11], [A12], [A13] | **Composed/custom/conditional, D.** Model choice, safety, region, API and quality remain validation gates. |
| Transactional shopping and support agents | Separate suite products include broader shopping/customer-service experiences. [G08] | Potential later integration with transactional backends and separately authorized tools. | **Out of current design, E+.** Not needed to build search, recommendations or read-only discovery. |

### Recommendation families are different engineering problems

| Google family [G05] | Proposed Azure starting point | Promotion evidence and caveats |
|---|---|---|
| Similar Items | Catalog attribute similarity; later evaluated text/image embeddings if useful. | Product relevance judgments; no user history required for the baseline. Google's Similar Items is non-personalized and not tunable. |
| Others You May Like | Item-to-item co-view candidates; later contextual/sequence modeling. | Distinguish substitutes from complements; evaluate next-item retrieval without future-event leakage. |
| Frequently Bought Together | Deduplicated order-level co-purchase associations, support thresholds and complement rules. | Count orders/quantities deliberately; avoid recommending another size of the same product as a complement. Revenue per session is an objective, not a guaranteed outcome. |
| Recommended for You | Non-personalized category/popularity fallback, then consented user/session models. | Requires sufficient valid histories and eligible exposures; cold-start users must not receive fabricated personalized explanations. |
| Buy It Again | Consented purchase history and repeat-purchase intervals for suitable categories. | Suppress inappropriate categories and reconcile returns/cancellations. Google's model has a documented popular-item fallback; this design makes fallback explicit rather than claiming identical behavior. |
| On-sale | Authoritative promotion eligibility plus a recommendation policy. | A sale filter alone is not a personalized promotion model. Verify validity dates, market/currency and inventory. |
| Recently Viewed | Bounded, purpose-limited recent-item history. | A history lookup, not an ML model. Opt-out/deletion and current product eligibility still apply. |
| Page-Level Optimization | Fixed panel policy first, then separately evaluated panel selection. | Record panel position, actual exposure and duplicate suppression. Measure request fan-out and layout effects. |

All Azure starting points above are proposed application work. Azure ML provides
execution and model lifecycle capabilities, not these finished commerce models.
The existing [AutoML forecasting research](08-azure-ml-forecasting.md) predicts
future activity; it must not be relabeled as a recommendation engine.

## The feedback loop is part of the product

### Catalog and events

Google shares catalog and event inputs between search and recommendations and
provides ingestion through APIs and integrations including BigQuery, Cloud
Storage, Tag Manager and Google Analytics. This is not evidence of equivalent
native connectors on Azure. [G01], [G02], [G10]

The Azure platform needs:

- Catalog imports plus replayable change/deletion handling from the retailer's
  product, inventory and pricing systems.
- Search/browse context, **actual impressions**, positions, selected filters,
  views, cart deltas and authoritative order outcomes.
- Stable event IDs for retries and distinct search, exposure, session, visitor,
  cart, order and attribution identities.
- Data-quality dashboards for joins, missing context, invalid clocks, duplicate
  events, bot contamination, source freshness and coverage.
- Versioned training snapshots, point-in-time features and promotion criteria.

The [current Beacon contract](../api/beacon.openapi.json) does not establish
all of these learning events. Propose additive versioned contracts; do not
assume a search response proves that every result was seen, or that client
purchase reports are authoritative labels.

Preserve the POC's separate behavior and external-trend streams. External
revisions/retractions are not shopper interactions, and cumulative social
snapshots must not enter recommendation purchase/view counts.

### Data readiness is not optional

Google documents data-dependent search tiers. Examples include:

- Tier 2: at least 100,000 search/browse events in the preceding 90 days.
- Tier 3: at least 250,000 search events associated with user interaction,
  alongside other catalog, price and event-quality requirements.
- Tier 4: at least 100,000 Google-served search events in the preceding
  30 days, plus consistent identity and other requirements. [G09]

These examples are **not the complete eligibility rules**, Azure requirements,
or evidence that reaching a count guarantees better search.

Google's conversational-filtering guide separately requires 1,000 queries per
day and 25% frequency-weighted conversational coverage: queries with at least
one suitable question. That is not simply "25% of events contain filters."
Filter feedback and attribute configuration help generate coverage. [G06]

For Azure, define task-specific readiness before training: joined catalog IDs,
valid exposures/outcomes, adequate support per cohort, consent, temporal
coverage and a leakage-safe evaluation set. Synthetic data proves mechanics
and reproducibility, not commercial personalization quality.

### Attribution and privacy

Google returns attribution tokens that link serving to events. Its attribution
guide contains inconsistent wording: one section describes tagging immediate
product interactions, while another says only the initial search event carries
the search token. Recommendation click/panel guidance is separate. Treat this
as a provider-integration clarification, not a reason to merge all identifiers
or rewrite the existing public contracts. [G11]

For the Azure-native design, specify an independent, versioned attribution
policy: actual exposures reference the serving decision; interactions reference
the relevant exposure where available; order IDs remain separate. Retain
unknown attribution as unknown rather than guessing.

API permission consent is not behavioral-tracking consent. Define purposes,
retention, withdrawal, deletion propagation and access controls for event
history, profiles, snapshots, models, published lists and telemetry. The Google
overview also discloses sampled query/result human rating; a procurement
comparison should review both providers' applicable data terms rather than
assuming identical processing arrangements. [G01], [A17]

## Important Azure boundaries

1. **Two meanings of hybrid.** Azure AI Search hybrid retrieval combines
   keyword/vector results using reciprocal rank fusion. This POC's hybrid
   serving combines indexed trends with a live-store adjustment. They are
   independent dimensions and must have separate configuration. [A01]
2. **Semantic ranking is bounded.** It reranks the top 50 inputs and extracts
   captions/answers from indexed text. It does not create a generative shopping
   response or replace the retailer's behavioral learning loop. [A02]
3. **Use the effective ordering score.** With applicable semantic scoring
   functions, `@search.rerankerBoostedScore` can determine order rather than
   `@search.score` or `@search.rerankerScore`. Direct index queries and agentic
   retrieval do not have identical scoring-profile behavior. [A03]
4. **Native facets and suggestions are only part of the UX.** Learned facet
   ordering, query popularity, safe suggestion mining and merchant workflows
   need application logic. [A04], [A05]
5. **Index updates are not a transaction with the live store.** Use `merge`
   for existing score documents, inspect per-document results and reconcile
   visibility. Collections are replaced by merges, not appended. [A07]
6. **Jobs are not online inference.** Fabric notebook startup, ML queueing,
   execution and publication bound freshness. Azure ML online inference is a
   different, optional architecture with its own budget. [A08], [A10]
7. **Do not choose Azure AI Personalizer.** Microsoft documented retirement
   for 25 August 2026 and closed new resources earlier. An open-source migration
   suggestion is not a replacement managed recommendation service. [A14]
8. **Generative tools need enforcement.** Structured outputs help constrain
   shape, not authorization or truth. Prompt Shields complements, rather than
   replaces, catalog validation and tool permissions. Select exact supported
   model/version/API/region before implementation. [A11], [A12], [A13]

## Economics and operating comparison

Do not compare a Google per-request price with only an Azure Search bill.
Google's managed recommendation training/serving includes work the Azure team
would own. Conversely, Azure composition can reuse existing Fabric, operational
data and governance where those investments genuinely exist.

| Cost area | Google comparison basis | Azure composition basis |
|---|---|---|
| Search/browse | Serving requests under retail pricing. [G13] | Dedicated Search tier, replicas/partitions and provisioned duration; semantic and other enabled metered features. [A18] |
| Recommendations | Prediction volume, including panel fan-out; model training/tuning. [G05], [G13] | Training/scoring compute, artifact storage, serving reads and optional online endpoint capacity. |
| Ingestion/analytics | Include surrounding ingestion, storage, logging and integration services, not just the Retail API line item. | Fabric capacity consumption, retention, storage, catalog synchronization and event processing. |
| Application and state | Integration and merchant operation still have a cost. | Functions hosting/runtime, Cosmos throughput/storage, monitoring and any justified gateway/network services. |
| Conversation | Confirm entitlement and pricing for the exact guided/agent product. | Selected model tokens, embeddings where used, tool calls, state, safety and evaluation. |
| Engineering | Managed-service integration, configuration and evaluation. | Custom merchant UI, ranking/recommender lifecycle, data governance, on-call ownership and upgrades. |

The costing baseline is a supported Dedicated Search tier. Microsoft also
documents a **Serverless Developer tier in preview**, with consumption-based
compute/storage billing, regional/feature restrictions and no preview SLA.
Assess it as a separate experiment, not the default production alternative
or evidence that the two platforms share the same pricing model. [A18]

Build the estimate from explicit workload inputs:

- Search/browse requests, peak concurrency, response size and candidate count.
- Suggestions per keystroke/session, recommendation panels and model fan-out.
- Catalog/variant count, update rate, indexed/vector size and market count.
- Events per day, retention, feature-window cadence and ML retraining/scoring.
- Model/deployment selection, conversation turns/tokens and tool-call limits.
- Availability/region requirements and existing versus incremental capacity.

Calculate infrastructure cost per 1,000 **completed shopper discovery requests**
with failures, retries and supporting services included. Report engineering
cost separately, and show idle-capacity and peak-load sensitivity. Pin prices,
currency, region and quotation date when preparing a budget. This research
does not select SKUs or produce an unsupported savings estimate.

Default quotas and catalog/model/control limits are operational planning
inputs, not throughput SLAs. Verify Google's current quota page and the
selected Azure tier before a comparative load test. [G12], [A18]

## Differentiation and unresolved gaps

The strongest initial demonstration is **auditable, event-driven relevance
adjustment using the retailer's Azure/Fabric estate**. The POC can explain
which eligible products moved, which events/features drove the change, how
long publication took and whether expiry restored baseline behavior.

It does not yet demonstrate the following:

| Gap or decision | Required evidence/action |
|---|---|
| Google-quality learned relevance/revenue optimization | Shared judged queries and later authorized online experiments; no synthetic revenue-lift claim. |
| Complete merchant control parity | Rule-by-rule behavior tests, including pinning limits, facet scope and explicit sort; document intentionally narrower behavior. |
| Recommendation quality/cold start | Task-specific offline metrics, support thresholds, cohort analysis and real-world exposure/outcome evaluation. |
| Current conversational-agent API/entitlement | Resolve the broken implementation link and confirm product boundaries with Google; do not implement against a guessed contract. |
| Attribution inconsistency | Obtain provider clarification before compatibility work; use an explicit independent Azure-native policy meanwhile. |
| Preview/allowlist dependencies | Approve or exclude each dependency; verify the tenant, region and selected API instead of inferring availability from a page title. |
| Production freshness and latency | Measure ingestion, notebook start, ML queue/execution, publication, visibility and request latency separately. |
| Model, region, residency and privacy policy | Retailer requirements and service-specific support/terms review before deployment. |
| Multi-tenant economics/isolation | Separate capacity, credentials, training data, indexes, caches and telemetry deliberately; do not treat tenant fields as authorization. [A16] |

The [companion design](../architecture/azure-commerce-search-platform-design.md)
turns these findings into component ownership, request/data flows, rollout
gates and a testable delivery sequence.

## Source register

All sources below were reviewed for this research on **28 September 2026**.
This is the review date, not a claim that every source was published that day.
Availability labels reflect the cited page, not a validated deployment.

| ID | Official source | Claims supported / qualification |
|---|---|---|
| G01 | [Implement AI Commerce Search][G01] | Shared ingestion, integration/data quality and data-processing disclosure. |
| G02 | [Features][G02] | Search/browse, recommendation learning, facets and dynamic-facet allowlist. |
| G03 | [Serving controls][G03] | Merchant rules, conditions, linguistic controls, pinning and recommendation-control preview. |
| G04 | [Autocomplete overview][G04] | Uploaded/learned suggestion datasets and readiness/refresh limitations. |
| G05 | [Recommendation models][G05] | Model families, objectives, restrictions and page-level orchestration. |
| G06 | [Conversational filtering developer guide][G06] | Generated questions, manual controls and exact coverage definition. |
| G07 | [Release notes][G07] | Branding, merchant console roles and conversational-agent release history. |
| G08 | [Gemini Enterprise for Customer Experience][G08] | Suite boundary and preview Shopping agent; product claims are not API contracts. |
| G09 | [Data quality and performance tiers][G09] | Data-dependent search/browse readiness; examples above are not exhaustive. |
| G10 | [Record real-time user events][G10] | Event integration and catalog/event joining requirements. |
| G11 | [Attribution tokens][G11] | Search/recommendation feedback; internally inconsistent search-event wording. |
| G12 | [Quotas and limits][G12] | Default service quotas; verify actual project quotas separately. |
| G13 | [Retail pricing][G13] | Request and recommendation training/tuning charging model; not a total-cost estimate. |
| A01 | [Azure AI Search hybrid retrieval][A01] | Keyword/vector fusion, filters, facets and sorting. |
| A02 | [Semantic ranking][A02] | Top-50 boundary, extractive answers and preview query rewrite. |
| A03 | [Scoring profiles with semantic ranker][A03] | Effective score, function limitations and direct-query/agentic differences. |
| A04 | [Autocomplete and suggestions][A04] | Index-field suggesters, not a managed behavioral suggestion pipeline. |
| A05 | [Faceted navigation][A05] | Query-dependent buckets and preview advanced facet capabilities. |
| A06 | [Synonym maps][A06] | Equivalence/explicit mappings and assignment constraints. |
| A07 | [Load a Search index][A07] | Upload/merge/delete semantics and per-document handling. |
| A08 | [Activator: trigger Fabric items][A08] | Run Notebook; parameter passing labeled preview. |
| A09 | [Activator alerts from a KQL Queryset][A09] | Scheduled query evaluation; Eventhouse and capacity requirements. |
| A10 | [Azure ML production endpoints][A10] | Synchronous online versus asynchronous batch inference; not a commerce model catalog. |
| A11 | [Structured outputs][A11] | Supported schema/tool constraints; select supported model/API. |
| A12 | [Prompt Shields][A12] | User/document prompt-injection protections and their integration scope. |
| A13 | [Foundry models sold by Azure][A13] | Model capabilities, deployment/region and preview distinctions. |
| A14 | [Personalizer overview and retirement][A14] | Retirement date and closed new-resource access. |
| A15 | [Feature-flag telemetry][A15] | Experiment telemetry primitives, not a complete exposure/statistics system; portal integration includes preview labeling. |
| A16 | [Multitenant Search design patterns][A16] | Index/service isolation trade-offs; not automatic application authorization. |
| A17 | [Entra permissions and consent][A17] | API authorization consent, distinct from shopper tracking consent. |
| A18 | [Plan and manage Search costs][A18] | Capacity and additional-feature charging considerations. |

[G01]: https://docs.cloud.google.com/retail/docs/overview
[G02]: https://docs.cloud.google.com/retail/docs/features
[G03]: https://docs.cloud.google.com/retail/docs/serving-control-rules
[G04]: https://docs.cloud.google.com/retail/docs/completion-overview
[G05]: https://docs.cloud.google.com/retail/docs/models
[G06]: https://docs.cloud.google.com/retail/docs/conversational-filtering-dev-guide
[G07]: https://docs.cloud.google.com/retail/docs/release-notes
[G08]: https://cloud.google.com/gemini-enterprise-cx
[G09]: https://docs.cloud.google.com/retail/docs/data-quality
[G10]: https://docs.cloud.google.com/retail/docs/record-events
[G11]: https://docs.cloud.google.com/retail/docs/attribution-tokens
[G12]: https://docs.cloud.google.com/retail/docs/quotas
[G13]: https://cloud.google.com/products/retail/pricing
[A01]: https://learn.microsoft.com/azure/search/hybrid-search-overview
[A02]: https://learn.microsoft.com/azure/search/semantic-search-overview
[A03]: https://learn.microsoft.com/azure/search/semantic-how-to-enable-scoring-profiles
[A04]: https://learn.microsoft.com/azure/search/search-add-autocomplete-suggestions
[A05]: https://learn.microsoft.com/azure/search/search-faceted-navigation
[A06]: https://learn.microsoft.com/azure/search/search-synonyms
[A07]: https://learn.microsoft.com/azure/search/search-how-to-load-search-index
[A08]: https://learn.microsoft.com/fabric/real-time-intelligence/data-activator/activator-trigger-fabric-items
[A09]: https://learn.microsoft.com/fabric/real-time-intelligence/data-activator/activator-alert-queryset
[A10]: https://learn.microsoft.com/azure/machine-learning/concept-endpoints?view=azureml-api-2
[A11]: https://learn.microsoft.com/azure/ai-foundry/openai/how-to/structured-outputs
[A12]: https://learn.microsoft.com/azure/ai-foundry/openai/concepts/content-filter-prompt-shields
[A13]: https://learn.microsoft.com/azure/ai-foundry/openai/concepts/models
[A14]: https://learn.microsoft.com/azure/ai-services/personalizer/what-is-personalizer
[A15]: https://learn.microsoft.com/azure/azure-app-configuration/howto-telemetry
[A16]: https://learn.microsoft.com/azure/search/search-modeling-multitenant-saas-applications
[A17]: https://learn.microsoft.com/entra/identity-platform/permissions-consent-overview
[A18]: https://learn.microsoft.com/azure/search/search-sku-manage-costs
