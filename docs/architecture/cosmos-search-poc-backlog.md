# Cosmos catalogue Search: gap analysis and product backlog

## Scope and decision

Rezolve AI's internal engine is Google AI Commerce Search. This POC evaluates
Cosmos DB for NoSQL keyword/BM25 catalogue retrieval using the existing
[Search contract](../api/search.openapi.json) and synthetic products.
It does not recreate Google's behavioral learning, recommendations,
personalization, merchant console or conversational product suite.

The approved bounded exception to the [platform design](azure-commerce-search-platform-design.md)
uses Cosmos native retrieval instead of OpenSearch for this POC, Python 3.11+
and FastAPI, local OCI deployment and existing authorized Cosmos resources.
The [runbook](../../src/search-api/README.md) owns executable commands.
Optional embeddings/hybrid retrieval require a separate gated experiment.

## Gap analysis

| Capability | Cosmos provides | Application work / remaining gap |
|---|---|---|
| Catalogue | JSON documents, partitioned storage, point reads | Product schema, validation, revisions, import and authorizations |
| Text search | Full-text index, matching functions, BM25 | Search text, query terms, SDK integration, parameterization and judged relevance |
| Filters | SQL predicates and nested-array queries | Allowlist, grouping, inclusive money ranges, same-variant eligibility |
| Counts/paging | Aggregations, TOP and SDK paging | Exact parent totals, bounded ranked prefix, tie/snapshot limitations |
| API | Database SDK, not storefront service | Contract models, errors, security, correlation, rate/deadline controls |
| Facets | Aggregation queries, not a dedicated faceting product | API contract, count semantics, aggregation cost and UX |
| Suggestions | No complete learned commerce-suggestion service | Curated/prefix index, query popularity, safety and endpoint |
| Merchandising | Database state and transactions | Policy versions, boost/bury/pins, approvals, administration and testing |
| Recommendations | Storage and similarity primitives | Candidate generation, co-purchase rules/models, consent and lifecycle |
| Personalized ranking | Profile/feature storage | Consent, feedback processing, ranking models and evaluation |
| Hybrid discovery | Vector search and RRF | External embeddings, model/version validation, semantic-match universe and exact counts |
| Production | Availability/distribution/database controls | Partition load study, ingestion, reconciliation, mutable-state consistency, deployment/SLO/DR |

Customer evidence such as Walmart supports Cosmos as an e-commerce data
platform, not proof that it replaces Walmart's search engine. ASOS recommendation
serving is relevant to data/serving design, not evidence of managed search parity.

## Product backlog

Status separates implemented code/offline tests from verified live behavior.
No resource provisioning or paid calls are implied.

| ID | Priority | Story / deliverable | Acceptance / gate |
|---|---|---|---|
| POC-01 | P0 | Contract and scoped architecture decision | Public schemas/examples validated; limits and unsupported options documented |
| POC-02 | P0 | Live Cosmos feasibility | Authorized account verified BM25 parameters, EXISTS/count, ranked prefixes and RU; tied-order stability remains service-dependent |
| POC-03 | P0 | Catalogue mapping and importer | Offline export validates 1,000 products/6,136 variants; live import verifies each item, idempotent resume, ready epoch; no source/image writes |
| POC-04 | P0 | Python/FastAPI service and security | Scoped client-key authorization, Entra Cosmos access, strict validation, startup/readiness, 400/401/403 errors |
| POC-05 | P0 | Retrieval/refinements/pagination | Same-variant filters, inclusive ranges, exact IDs, BM25, exact parent total; pageSize 20 default/100 maximum, rank window 1,000 |
| POC-06 | P0 | Response and reliability | Contract output, independent correlation, no fabricated attribution, 429/503, bounded retries/deadline, safe telemetry |
| POC-07 | P0 | Offline regression suite | HTTP/schema/query/adapter failure tests, type/lint and existing catalogue/image tests; no cloud calls |
| POC-08 | P0 | Evaluation/runbook/container | Opt-in live report, NDCG/Recall boundaries, latency/RU, exact eligibility/count assertions; container/live verification separately reported |
| POC-09 | P1 gated | Vector/hybrid experiment | Select approved provider/model; validate vectors/policy, matching and exact totals; keep disabled until approved |
| POC-10 | Later | Facets/autocomplete/browse | New reviewed contracts; query-dependent count and language semantics |
| POC-11 | Later | Merchant controls | Immutable policies, preview/approval, eligible pinning and explicit-sort preservation |
| POC-12 | Later | Beacon and feedback | Actual exposures, idempotency, source revision/retraction, readiness and expiry |
| POC-13 | Later | Recommendations/preferences | Task-specific evaluation, consent/deletion; learned models require separate decision |
| POC-14 | Later | Continuous catalogue projection | Tombstones, reconciliation, authoritative hydration and count/paging consistency |
| POC-15 | Later | Production scale/operations | Partition load evidence, hosted deployment, privacy, distributed admission, backup/DR and SLOs |

POC-01 precedes baseline implementation. Live POC-02 evidence gates acceptance
of Cosmos query/import behavior. API scaffolding and offline validation can
proceed without cloud access. POC-08 needs a verified import, baseline and
passing tests. POC-09 follows baseline evaluation and separate approval.

## Current delivery boundary

The keyword baseline is implemented and live-verified on the approved synthetic
catalogue: 1,000 products/6,136 variants, an idempotent import rerun, 28 real HTTP
checks and 36 concurrent Cosmos queries without failures. See the
[Bicep deployment and measured evidence](../../infra/README.md#deployment-and-live-verification-evidence).
The approved portal/CIDR and supplemental development rules retain Entra-only
authentication and restricted public access.

Offline tests are still not cloud evidence. BM25 tied-order stability,
mutable-catalogue snapshots, production scaling/availability, complete billing,
container-hosted identity integration, Google relevance comparison and optional
hybrid retrieval remain outside the verified baseline. The API is local;
no Azure API hosting was provisioned. Do not claim managed-commerce parity or
commercial uplift from these synthetic results.

Image hosting now uses a Bicep-provisioned synthetic read-only blob container.
The active `catalog-images-001` snapshot stores schema-v2 relative `imagePath`
and gallery paths; `CATALOG_IMAGE_BASE_URL` resolves the public API URLs.
The original snapshot remains unchanged. Dev/test/prod storage names are
deployment/configuration choices, not catalogue data or shopper state.

## Official references

- [Cosmos full-text search](https://learn.microsoft.com/azure/cosmos-db/gen-ai/full-text-search)
- [FullTextScore constraints](https://learn.microsoft.com/cosmos-db/query/fulltextscore)
- [Cosmos hybrid search](https://learn.microsoft.com/azure/cosmos-db/gen-ai/hybrid-search)
- [General OFFSET LIMIT](https://learn.microsoft.com/cosmos-db/query/offset-limit)
- [Async Cosmos SDK query API](https://learn.microsoft.com/python/api/azure-cosmos/azure.cosmos.aio.containerproxy)

General OFFSET support is not proof that ranked queries support OFFSET.
FullTextScore belongs in ORDER BY RANK/RRF, never a SELECT/WHERE projection.
Language/fuzzy feature status and index availability must be checked for the
selected account and SDK rather than assumed from a customer story.
