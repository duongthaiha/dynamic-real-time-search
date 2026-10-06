targetScope = 'resourceGroup'

param location string = resourceGroup().location

@secure()
param operatorPrincipalId string

param allowedClientIps array = []

param allowedClientCidrs array = [
  '85.210.10.0/24'
]

param allowAzurePortalMiddleware bool = true

param databaseName string = 'commerce-search-poc'
param containerName string = 'catalog-images-001'

var accountName = 'cosmos-rezolve-${uniqueString(subscription().id, resourceGroup().name)}'

// Azure Public "All" middleware addresses apply to NoSQL; legacy/API-specific IPs are excluded.
// https://learn.microsoft.com/azure/cosmos-db/how-to-configure-firewall
var azurePortalMiddlewareIps = [
  '13.91.105.215'
  '4.210.172.107'
  '13.88.56.148'
  '40.91.218.243'
]
var effectiveAllowedIps = union(
  allowedClientIps,
  allowedClientCidrs,
  allowAzurePortalMiddleware ? azurePortalMiddlewareIps : []
)

resource account 'Microsoft.DocumentDB/databaseAccounts@2026-03-15' = {
  name: accountName
  location: location
  kind: 'GlobalDocumentDB'
  tags: union(resourceGroup().tags, {
    SecurityControl: 'Ignore'
  })
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    publicNetworkAccess: empty(effectiveAllowedIps) ? 'Disabled' : 'Enabled'
    ipRules: [for ip in effectiveAllowedIps: {
      ipAddressOrRange: ip
    }]
    isVirtualNetworkFilterEnabled: false
    disableLocalAuth: true
    minimalTlsVersion: 'Tls12'
    enableAutomaticFailover: false
    enableMultipleWriteLocations: false
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2026-03-15' = {
  parent: account
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
    // No provisioned throughput on a serverless database.
    options: {}
  }
}

resource catalog 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2026-03-15' = {
  parent: database
  name: containerName
  properties: {
    resource: {
      id: containerName
      partitionKey: {
        paths: [
          '/scopeId'
        ]
        kind: 'Hash'
        version: 2
      }
      fullTextPolicy: {
        defaultLanguage: 'en-US'
        fullTextPaths: [
          {
            path: '/searchText'
            language: 'en-US'
          }
        ]
      }
      indexingPolicy: {
        automatic: true
        indexingMode: 'consistent'
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/"_etag"/?'
          }
        ]
        fullTextIndexes: [
          {
            path: '/searchText'
          }
        ]
      }
    }
    options: {}
  }
}

resource importerRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2026-03-15' = {
  parent: account
  name: guid(account.id, catalog.id, operatorPrincipalId, 'catalog-importer')
  properties: {
    principalId: operatorPrincipalId
    roleDefinitionId: '${account.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    // Data-plane scope uses dbs/colls, not the ARM sqlDatabases/containers path.
    scope: '${account.id}/dbs/${databaseName}/colls/${containerName}'
  }
}

output accountName string = account.name
output endpoint string = account.properties.documentEndpoint
output databaseName string = database.name
output containerName string = catalog.name
