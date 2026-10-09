# Cosmos Search POC infrastructure

[main.bicep](main.bicep) creates a new isolated resource group at subscription
scope. [cosmos.bicep](cosmos.bicep) creates only:

- A single-region Azure Cosmos DB for NoSQL serverless account.
- `commerce-search-poc` database and immutable `catalog-images-001` container.
- English full-text policy/index on `/searchText` and `/scopeId` partition key.
- A container-scoped Cosmos Data Contributor assignment for the explicitly
  authorized import operator; no subscription-wide or existing-account roles.

[storage.bicep](storage.bicep) also creates a Standard LRS StorageV2 account,
the `product-images` blob container and a container-scoped Entra upload role.
Shared-key access is disabled; TLS 1.2 and HTTPS are required. Only the synthetic
image container permits anonymous blob reads, not listing or writing. Public
network access is intentional so browser image URLs work; no real shopper data,
receipts or prompts are uploaded.

The account uses Entra only (`disableLocalAuth=true`) and TLS 1.2. Its restricted
firewall combines three explicitly approved sources, deduplicated in Bicep:

- `allowedClientIps`: additional development egress addresses supplied privately.
- `allowedClientCidrs`: defaults to the user-approved `85.210.10.0/24`.
- `allowAzurePortalMiddleware`: defaults to true and adds the Azure Public
  **All** API middleware addresses applicable to this NoSQL account:
  `13.91.105.215`, `4.210.172.107`, `13.88.56.148`, `40.91.218.243`.

The portal addresses come from Microsoft's
[current firewall guide](https://learn.microsoft.com/azure/cosmos-db/how-to-configure-firewall).
Legacy, MongoDB-only and Cassandra-only middleware addresses are not added.
Portal middleware rules do not replace caller authentication or the operator's
own source-IP rule for NoSQL Data Explorer.

Final verification using the same `2026-03-15` management API as Bicep reports
`Succeeded` with five effective rules: the four middleware addresses and the
approved CIDR. That CIDR covers all eight development addresses observed during
this POC, so their individual entries are not needed for the verified access path.

There is no `0.0.0.0` all-Azure-services bypass or all-address CIDR. To disable
public access, explicitly set both address arrays to empty and
`allowAzurePortalMiddleware=false`. Do not commit personal development IP
addresses or operator IDs into parameter files.

The user-authorized `SecurityControl: Ignore` exception tag is applied explicitly
to this POC resource group and account. It is not applied to existing resources
or intended as a production policy exception. Entra authentication, TLS and the
explicit-IP firewall remain enforced by the template.

Serverless avoids idle provisioned-RU charges, but consumed RUs, storage and
applicable backup/network charges remain billable. This is not a production
availability/DR configuration. No API hosting, AKS, embeddings, model services,
registry or existing retailer/agent resource changes are included.

## Deploy

If the shared Azure CLI installation is unavailable or has broken dependencies,
use an isolated tooling environment rather than changing the machine install:

```powershell
python -m venv .venv-azure
.\.venv-azure\Scripts\python.exe -m pip install -r infra\requirements-azure-cli.txt
$env:PATH = "$(Join-Path (Get-Location) '.venv-azure\Scripts');$env:PATH"
```

The isolated CLI is separate from `.venv-search`: Azure CLI dependencies must
not replace the API's Cosmos SDK. This tooling environment is ignored by Git;
TLS verification stays enabled.

Use the approved subscription and region (UK South for this POC). Acquire the
signed-in operator object ID without printing it, and pass it as the secure
`operatorPrincipalId` parameter. All resource creation is defined in Bicep.
Compile first, then run a subscription-level what-if before create:

```powershell
az bicep build --file infra\main.bicep --stdout | Out-Null
$principal = az ad signed-in-user show --query id --output tsv --only-show-errors

az deployment sub what-if --name rezolve-search-poc `
  --location uksouth --template-file infra\main.bicep `
  --parameters operatorPrincipalId=$principal --output none

az deployment sub create --name rezolve-search-poc `
  --location uksouth --template-file infra\main.bicep `
  --parameters operatorPrincipalId=$principal --output none
```

The default deployment allows the approved CIDR and portal middleware routes.
Additional development egress addresses can be discovered using the account's
own firewall rejection (do not query an external IP service or log the raw
rejection). Redeploy the same templates with `allowedClientIps` containing those
addresses, after a second what-if. Preserve these private supplemental rules on
redeployment if the local API needs them. Firewall changes and role propagation
can require a bounded wait before validation.

Use a private temporary JSON deployment-parameter file for IPs/IDs; avoid shell
history, console output and committed files containing personal network/identity
information. Deployment outputs contain nonsecret endpoint/database/container
names; use them to set the four Cosmos variables in the
[Search runbook](../src/search-api/README.md).

The local import/operator identity can write this POC container. A production
or separately hosted API should use its own managed identity with Cosmos Data
Reader rather than reuse operator write privileges.

## Verify and operate

### Images and environment-portable catalogue paths

`storageAccountName` can be overridden for dev/test/prod deployment, while
`imageContainerName` defaults to `product-images`. The `imageBaseUrl` Bicep output
sets `CATALOG_IMAGE_BASE_URL`; the storage account name is never stored in v2
catalogue documents. `allowPublicImageRead=false` disables anonymous reads, but
then this baseline needs a separately designed authenticated image-delivery
path; it does not manufacture SAS credentials.

```powershell
# After approved storage deployment; use its account-name output.
az storage blob upload-batch --account-name <storage-account> `
  --auth-mode login --destination product-images --source data\catalog\images `
  --overwrite false --validate-content --max-connections 4

$env:CATALOG_IMPORT_EPOCH = "catalog-images-001"
$env:COSMOS_CONTAINER = "catalog-images-001"
$env:CATALOG_IMAGE_BASE_URL = "https://<storage-account>.blob.core.windows.net"
.\.venv-search\Scripts\catalog-import.exe --epoch catalog-images-001 `
  --image-container product-images --write --confirm-container $env:COSMOS_CONTAINER
```

Upload/verify images before publishing the new snapshot. Switch the API epoch,
container and image-base configuration only after the ready import verifies.
The previous `catalog-import-001` snapshot is preserved for rollback. Do not patch
URLs into a published immutable catalogue or regenerate the source image state.

The authorized upload contains 1,000 PNG photographs plus 1,000 SVG fallbacks.
All 2,000 stored content checksums, lengths and MIME types matched local files.
All 1,000 current catalogue image paths passed anonymous HEAD checks; sample
PNG/SVG downloads matched source bytes. Anonymous container listing and writing
were denied. The API retained its absolute-URI response contract and passed the
28 live HTTP checks on the new relative-path snapshot.

Run the authorized importer and live evaluation from the Search runbook.
Verify that the account remains key-auth-disabled and IP-restricted, the
container has full-text policy/index and no TTL, and the ready import has exactly
1,000 products and 6,136 variants.

Change the allowed address only through reviewed Bicep parameters. Do not
modify the published catalogue in place or assume a successful ARM deployment
proves query correctness. All existing resource groups and data remain untouched.
Resource teardown is a separate destructive action requiring explicit approval.

## Deployment and live verification evidence

The authorized UK South deployment creates:

| Resource | Name |
|---|---|
| Resource group | `rg-rezolve-search-poc-uks` |
| Cosmos account | `cosmos-rezolve-frv3w6fiiwjwi` |
| Database | `commerce-search-poc` |
| Active container | `catalog-images-001` |
| Preserved previous container | `catalog-import-001` |
| Image storage account | `strezolvefrv3w6fiiwjwi` |
| Public synthetic-image container | `product-images` |

Bicep compilation and subscription what-if were performed before deployment.
The deployed container's schema/index and the container-scoped role assignment
are management-plane validation, not data-query evidence. Cosmos role scopes
use `${accountId}/dbs/${databaseName}/colls/${containerName}`, not the ARM
`sqlDatabases/containers` resource path.

After the user approved `SecurityControl: Ignore`, restricted public networking
persisted and live Entra connectivity succeeded with the observed development
egress allowlist. The synthetic import and idempotent rerun both verified
**1,000 products and 6,136 variants** in the ready immutable epoch.

The real local HTTP API passed **28 checks**, including health/readiness,
correlation/response schemas, exact IDs/SKUs, stock eligibility, inclusive price
ranges, refinement AND/OR grouping, exact totals, the 1,000-candidate paging
window, and expected 400/401/403/422 responses.

| Live evaluation | Result |
|---|---|
| HTTP checks | 28 passed, zero failures |
| Concurrent Cosmos queries | 36 passed at concurrency 4 |
| HTTP latency, 12 timed successful cases | p50 62.60 ms, p95 544.59 ms |
| Adapter latency, concurrent run | p50 71.40 ms, p95 569.18 ms |
| Count + ranked-prefix query charge, concurrent run | 1,358.757 RU total |

These are bounded synthetic POC measurements, not production latency guarantees,
total cost estimates or Google-quality/revenue parity. Readiness and import RU
are excluded from the query metric. The API remains local/containerized; no
Azure API hosting was provisioned. The generated evidence reports are under
`data\cosmos-poc\`; rerun the authorized evaluation commands to refresh them.

## Additive large-catalogue snapshot

[catalog-snapshot.bicep](catalog-snapshot.bicep) targets the existing resource
group/accounts, creating only a fresh Cosmos container, a versioned public
synthetic-image container and container-scoped operator roles. Defaults are
`catalog-scale-001` and `product-images-scale-001`; the existing
`catalog-images-001`/`product-images` data must remain untouched.

Unlike redeploying the original account modules, this template does not change
Cosmos capacity mode, firewall rules, Storage account/network settings or model
deployments. Shared-key access remains disabled. New public blobs must contain
synthetic images only, not prompts, receipts or checkpoints.

```powershell
az bicep build --file infra\catalog-snapshot.bicep --stdout | Out-Null
# After reviewing private parameter values and obtaining resource approval:
# az deployment group what-if --resource-group rg-rezolve-search-poc-uks `
#   --template-file infra\catalog-snapshot.bicep --parameters '@<private-parameters.json>'
# Apply only after what-if confirms isolated new containers/scoped roles.
```

Use a private parameter file for `operatorPrincipalId`; do not commit operator
identity data. Do not reuse a published container name or perform a full
account redeployment merely to add an expanded snapshot.

Retaining `/scopeId` is conditional on the
[capacity/import gates](../src/search-api/README.md#large-catalogue-imports).
Local Bicep compilation is not proof of permission, provider compatibility,
model access, successful upload or query performance. The same documented
Storage `2026-09-01` type-cache warning applies to this additive template.
Set `includeCatalog=false` for a separately approved image-only pilot: no Cosmos
container or Cosmos role is created in that mode. A later Cosmos deployment
requires its own capacity review and explicit approval.

## Official references

- [Cosmos serverless](https://learn.microsoft.com/azure/cosmos-db/serverless)
- [Full-text indexing](https://learn.microsoft.com/azure/cosmos-db/gen-ai/full-text-search)
- [Cosmos account Bicep schema](https://learn.microsoft.com/azure/templates/microsoft.documentdb/2026-03-15/databaseaccounts)
- [Container Bicep schema](https://learn.microsoft.com/azure/templates/microsoft.documentdb/2026-03-15/databaseaccounts/sqldatabases/containers)
- [Data-plane role-assignment schema](https://learn.microsoft.com/azure/templates/microsoft.documentdb/2026-03-15/databaseaccounts/sqlroleassignments)
- [Storage account schema](https://learn.microsoft.com/azure/templates/microsoft.storage/storageaccounts)
- [Blob container schema](https://learn.microsoft.com/azure/templates/microsoft.storage/storageaccounts/blobservices/containers)

The Storage resource provider advertised stable API `2026-09-01` for this
deployment. The installed Bicep type cache does not yet describe it (BCP081);
resource properties were therefore validated by Azure what-if/deployment and
post-deployment checks, rather than claimed as fully validated by local typing.
