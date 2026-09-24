# Search and Beacon API contracts

These are **two independent OpenAPI 3.0.3 draft contracts** for the POC,
reconstructed from the supplied `openai.json` Postman export. Each contains
its own schemas and local references; neither depends on the other file.

| Service | Contract | Endpoint | Responsibility |
|---|---|---|---|
| Search | [search.openapi.json](search.openapi.json) | `POST /v1/search` | Retrieve and rank catalog items for the storefront |
| Beacon | [beacon.openapi.json](beacon.openapi.json) | `POST /v2/events` | Capture shopper activity for asynchronous event processing |

The example service hosts are reserved `example.com` placeholders. Replace
them with each deployment's base URL. No requests were sent to the source
provider, and the original download has not been edited.

## Review of the supplied file

| Finding | Treatment in these drafts |
|---|---|
| The file is a Postman collection v2.1, not an OpenAPI document. It contains requests, not schemas. | Reconstructed operations, reusable schemas, examples, and explicit assumptions instead of mechanically splitting JSON. |
| The file ends at line 531 inside the headers of an eleventh request named "3. search ... with biasing and refinements". The outer JSON is incomplete. | Used only the ten complete requests: two Search and eight Beacon examples. The third Search body's biasing options cannot be recovered and are not invented. |
| Some raw request bodies contain `//` comments despite declaring `application/json`. | Examples in both contracts are strict JSON. Comments are not valid request content. |
| All ten complete requests have empty response arrays. | Every success/error status and response shape is a **POC proposal**, not verified provider behavior. |
| Search says Postman `noauth` but sends `Authorization: client-key {{clientKey}}` explicitly. | Modelled the actual header using an OpenAPI `apiKey` security scheme; this is not Bearer authentication. Preserved `x-customer-id`. |
| Beacon sends no authentication credential; customer identity is supplied in the body. | Explicit `security: []` describes the examples, not a production recommendation. Authentication and tenant isolation must be decided before public deployment. |
| Beacon sends `access-control-allow-origin: *` as a request header. | Omitted it: CORS permission is a server response policy, not something a client grants itself. Browser `User-Agent` is also not a custom business parameter. |
| Four distinct beacon payloads share one endpoint. | Added a discriminated `oneOf` with `autoSearch`, `viewProduct`, `addToCart`, and `order`, each requiring its corresponding payload. |
| There is no event ID or order ID in the samples. Cart IDs are not event identities. | Added optional, explicitly proposed `eventId` and `orderId` fields without requiring changes to observed requests. Legacy retries still cannot be reliably deduplicated. |
| Search attribution is inconsistent: comments imply IDs and tokens are interchangeable; order examples also carry a different token in metadata. | Keep correlation ID and attribution token separate. Proposed order handling prefers the top-level token and records mismatches. |
| The source does not establish requiredness, defaults, limits, or filter semantics. | Inferred minimal required fields and basic numeric constraints; documented proposed refinement semantics and unresolved deployment limits. |
| Search has vendor-specific sponsorship, cache, and diagnostic fields. | Preserved them for visibility, but require explicit unsupported-option errors where the POC does not implement them. Do not silently promise Topsort integration. |

Request property spelling and nesting are preserved, including `referer`,
`origin.autosearch`, `attributes.color` in refinement names, and the
camelCase beacon event names. Numeric-looking product IDs remain strings.
Unknown properties remain allowed for compatibility; this does not grant
them a defined effect or permission to bypass validation.

## Proposed service boundary and client flow

1. The storefront calls Search with customer scope, collection, query,
   refinements, and optional session/visitor identifiers.
2. Search returns a proposed `id`, products in `records`, pagination
   metadata, and an optional opaque `searchAttributionToken`.
3. The storefront captures an `autoSearch` event using that `id` in
   `search.id`. The proposed Search response's exact field names must be
   confirmed with real response examples before existing clients migrate.
4. Product views, cart additions, and purchases go to Beacon, not Search.
   Reuse session/visitor IDs for correlation; use a **new event ID for each
   logical action** and the **same event ID/body for retries**.
5. Beacon validates and durably accepts an event before returning the
   proposed `202`. Acceptance is not proof of downstream processing.
6. Beacon normalizes events into the internal research envelope; the
   aggregation and signal-delivery pipeline eventually affects Search.

Search owns retrieval, relevance, filters, and result delivery. Beacon owns
event validation, receipt, deduplication, and normalization. It does not
return search results or synchronously guarantee a ranking change.

### Authentication and browser delivery

The Search credential must be scoped for its intended caller. Do not ship
a privileged backend key in browser JavaScript. A backend-for-frontend or
a deliberately browser-safe credential model needs to be chosen before
public deployment. Beacon's unauthenticated examples do not establish a
trustworthy tenant boundary: `customer.id`, URLs, prices, and order reports
are client claims, not authoritative evidence.

Configure allowed origins and preflight handling on each service.
`application/json` and Search's custom headers can trigger a browser
preflight. "Beacon" here means the event-capture service, not a guarantee
of compatibility with `navigator.sendBeacon()`: that API cannot set custom
authorization headers or read the acceptance response. Validate the chosen
browser transport, payload limits, consent policy, and credential approach.

## Mapping to the POC's internal events

The public compatibility payload is intentionally **not** the internal
[research event envelope](../06-event-schema.md). Use a normalization
adapter, not a silent rename of that internal contract.

| Public Beacon event | Internal event | Mapping and limitation |
|---|---|---|
| `autoSearch` | `search` | Preserve `search.id` as correlation. Resolve query/results/filter context from the originating Search request/response if retained; the beacon alone does not contain it. Do not fabricate a query or product attribution when context is unavailable. |
| `viewProduct` | `view_product` | Map `product.productId`; resolve authoritative catalog attributes server-side. |
| `addToCart` | `add_to_bag` | Proposed interpretation: each item is an addition in this action, not the whole cart. Deduplicate the parent first, then fan out with stable child IDs derived from parent event ID and item index. Confirm delta-versus-snapshot semantics before counting. |
| `order` | `purchase` | Preserve the items array and quantities after deduplication. Use the optional `orderId` when available; do not substitute cart ID or search attribution as an order ID. Missing order IDs prevent authoritative order reconciliation. |

Common normalization:

- Use the supplied `eventId` or an ingress-generated ID. Scope source
  deduplication by customer and area, and retain that scope internally.
- Normalize `visit.generated.localTime` to UTC `eventTime`. Keep server
  `receivedAt` separately; client clocks may be wrong. The offset field's
  sign is not established, so do not apply it twice.
- Map `visit.customerData.sessionId` to internal `sessionId`. Keep
  `visitorId` as pseudonymous context, not an authenticated `userId`.
- Assign internal `source` from trusted ingestion configuration rather
  than accepting vendor `engineSource` metadata as proof of origin.
- Record schema version and correlation metadata in the normalization
  layer. Quarantine/report unresolvable product or search context rather
  than inventing values.

The source provides no `remove_from_bag` or `external_trend` public
requests. They remain internal POC/generator concerns until separately
specified; these contracts do not invent public endpoints for them.

## Decisions to settle before implementation or client migration

- Obtain the full collection and actual success/error responses. Verify
  the proposed Search response, Beacon acknowledgement, and status codes.
- Confirm inferred required fields, empty-query behavior, refinement
  operators/range boundaries, cart delta semantics, and attribution rules.
- Publish page-size/body-size/rate limits, deduplication retention, allowed
  clock skew/lateness, and supported metadata/refinement fields.
- Decide the authentication/authorization model for both browser-facing
  services and update the security schemes and error responses accordingly.
- Decide which legacy vendor options are implemented. Unsupported options
  must receive the documented error, not a success-shaped no-op.
- Implement semantic checks that OpenAPI cannot express here: `low <= high`,
  consistent `or` modes per field, metadata-key uniqueness, known customer/
  catalog scope, and duplicate-ID/body comparison.
- Keep baseline/index/hybrid selection in controlled POC configuration
  until a public selector is deliberately specified. `enableTopsort` is
  not that selector. Reject nonzero hybrid offsets until pagination across
  a bounded candidate window is designed.

These are reviewable interface drafts, not evidence of running services
or verified compatibility with the original provider.

## Validation performed

- Both standalone documents passed OpenAPI validation using
  `@apidevtools/swagger-parser` 12.1.0.
- All contract request/response examples and all ten complete source
  request bodies passed schema validation with Ajv 8.17.1 and
  `ajv-formats` 3.0.1. Source-body comments were removed for validation only.
- Negative cases rejected missing event-specific payloads, unsupported
  event types, invalid pagination/refinements, empty carts, invalid
  quantities, and timestamps without an offset.
- Local documentation links and schema references resolved. No provider
  endpoints were called; cross-field business rules still need service
  implementation tests.
