# Fashion ecommerce search query sample

## Research and scope

Researched on 2026-10-09 for this repository's UK fashion store: clothing,
footwear, bags and accessories. This is **1,000 original synthetic, unique
English search terms**, not collected shopper logs or a statistically
representative traffic sample. No external query dataset was downloaded or
copied. No models, cloud services or live searches are called during generation.

Two public sources informed the design:

1. [Baymard: ecommerce search query types](https://baymard.com/research-articles/ecommerce-search-query-types).
   Its usability research identifies exact-item, product-type, feature and
   use-case searches as important ecommerce patterns. Features include colour,
   material, size, price and brand; users combine them with other intents.
   Apparel shoppers also search by occasion and season. Category synonyms and
   alternate spellings matter. **The article's percentages describe sites with
   usability problems, not the frequency of shopper query types.**
2. [Amazon Science: Shopping Queries / ESCI](https://github.com/amazon-science/esci-data).
   This benchmark separates queries from query-product relevance judgments
   (Exact, Substitute, Complement, Irrelevant), with English, Japanese and
   Spanish data. It deliberately includes challenging queries; its composition
   is not a normal-traffic distribution. We use its distinction between query
   coverage and judged relevance, not its query text or ranking technology.

Practical synthesis: include short category queries, narrower attribute
combinations, brand intent, exact titles/identifiers and longer occasion phrases.
Add explicit synonym, misspelling and service-navigation slices rather than
assuming every shopper uses catalog terminology. Electronics compatibility and
technical problem/symptom searches are excluded because this is a fashion
sample, not a general marketplace.

## Deliberately designed coverage

These are **coverage quotas chosen for this sample**, not industry percentages.
Each row has one primary intent; intent types overlap in actual shopping.
Attribute and brand queries dominate this test mix. Exact identifiers and rare
edge cases are intentionally oversampled to expose retrieval gaps.

| Primary intent | Count | Share | Coverage |
|---|---:|---:|---|
| Product type | 100 | 10% | Category, singular/plural, men's/women's wording |
| Feature | 350 | 35% | Colour, fit, material, one or multiple attributes |
| Brand | 150 | 15% | Existing synthetic brands, brand plus category/feature |
| Exact | 80 | 8% | 40 catalog titles, 20 product IDs, 20 variant SKUs |
| Use case | 100 | 10% | Occasion, season, travel/work, longer natural phrases |
| Price | 80 | 8% | GBP budgets, upper bounds and price bands |
| Size | 60 | 6% | Category-appropriate UK, alpha, waist/length, one-size |
| Synonym | 40 | 4% | Alternate vocabulary with canonical interpretation |
| Typo | 30 | 3% | Original controlled misspellings plus corrected wording |
| Non-product | 10 | 1% | Delivery, returns, sizing and service navigation |
| **Total** | **1,000** | **100%** | **Unique after case-insensitive deduplication** |

All 15 catalog categories are covered. Sampling rotates across categories
within each intent; this is balanced coverage, not sales-weighted popularity.
Brand/feature/title candidates come from the existing source catalog.
All 15 broad category head terms are retained. Shopper-facing feature phrases
shorten catalog material labels and use accessory subtype names; price budgets
are drawn from each category's configured range rather than a store-wide band.
Use cases are shopper intentions, **not verified product suitability claims**.
Synonyms are useful interpretations rather than universally exact equivalents
(for example, "purse" is ambiguous across locales).

## Files and fields

Generated outputs live in [data/search-terms-fashion-1000](../../data/search-terms-fashion-1000/):

- [search-terms.csv](../../data/search-terms-fashion-1000/search-terms.csv):
  spreadsheet-friendly annotated dataset.
- [search-terms.txt](../../data/search-terms-fashion-1000/search-terms.txt):
  exactly 1,000 lines, one query per line, no header.
- [manifest.json](../../data/search-terms-fashion-1000/manifest.json):
  seed, source projection hash, counts, token-length histogram and output hashes.
- [evaluation-batches](../../data/search-terms-fashion-1000/evaluation-batches/):
  ten arrays of 100 cases, compatible with the existing evaluator's 100-case
  limit. Each case uses the original query unchanged and has no invented grades,
  expected product list or expected result count.

CSV columns:

| Field | Meaning |
|---|---|
| `queryId` | Stable row ID for the same seed and source |
| `query` | Original synthetic shopper input, normalized to lowercase |
| `intent` | Primary coverage label from the table above |
| `category` | Intended catalog category, or `service` for non-product queries |
| `canonicalQuery` | Suggested typo/synonym interpretation; otherwise original query (exact IDs retain catalog casing) |

`canonicalQuery` is annotation only: **do not replace the raw query when
measuring typo/synonym behaviour**. Categories are not relevance judgments.
Size and price phrases stay in `query`; they are not silently translated into
API refinements. The keyword baseline need not understand those constraints,
correct typos or route service queries. Zero results may be legitimate.
Use structured refinements separately when testing same-variant eligibility.

## Reproduce and validate offline

Use the already configured repository Python environment; the generator adds
no dependencies and does not reseed or modify the source catalog:

```powershell
.\.venv-search\Scripts\python.exe src\load-generator\generate_search_terms.py
.\.venv-search\Scripts\python.exe -m unittest discover `
  -s src\load-generator -p "test_generate_search_terms.py"
Get-ChildItem data\search-terms-fashion-1000\evaluation-batches\batch-*.json |
  ForEach-Object {
    .\.venv-search\Scripts\python.exe -m catalog_search.evaluate --cases $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "Offline case validation failed" }
  }
```

Default source: `data\catalog\products.jsonl`, the stable 1,000-parent synthetic
catalog whose taxonomy is retained by expansion. Its exact items may not exist
in an independently reseeded snapshot. To target another complete source:

```powershell
.\.venv-search\Scripts\python.exe src\load-generator\generate_search_terms.py `
  --source data\catalog-expanded-10000\metadata\products.jsonl `
  --output data\search-terms-fashion-expanded
```

The source must cover the same 15 categories and supply enough distinct
candidates. Invalid/incomplete input fails explicitly. The seed and parsed
source projection (IDs, titles, brands, categories, attributes and SKUs)
determine repeatable output; image receipts/URLs are not used.
Regeneration replaces dataset files in the selected output directory.
Never point `--output` at the catalog itself.

## What this can and cannot establish

Use this sample for demo inputs, offline contract validation and an explicitly
approved retrieval coverage experiment. The included tests verify exact count,
uniqueness, intent quotas, category coverage, identifier provenance, file hashes,
determinism, source preservation and batch/query alignment.

This is a set of distinct queries, not sessions: there are no arrival rates,
repeat-search frequencies, click/purchase labels, personalization, shopper IDs,
head/tail frequency weights or complete relevance judgments. It cannot establish
normal-traffic proportions, conversion uplift, Recall/NDCG or latency guarantees.
Relevance evaluation needs independently reviewed query-product judgments;
realistic traffic weighting needs consented/approved aggregate traffic evidence.
The current evaluator's "passed" without expected results only means the search
completed without an error, not that products were relevant.

Live execution is **not performed or authorized by this dataset**. Adding
`--live` consumes Cosmos RUs and requires a separate approved budget/scope.
Retain raw queries and report zero-result/service slices separately from
catalog relevance and filter-correctness results.
