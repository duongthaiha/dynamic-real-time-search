targetScope = 'resourceGroup'

@description('Existing Entra-only Cosmos account. This template does not modify account settings.')
param cosmosAccountName string
param databaseName string = 'commerce-search-poc'
param catalogContainerName string = 'catalog-scale-001'
@description('Disable for an image-only pilot; enable after separately approved Cosmos capacity review.')
param includeCatalog bool = true

@description('Existing image Storage account. Account and network policies are not changed.')
param storageAccountName string = 'strezolvefrv3w6fiiwjwi'
param imageContainerName string = 'product-images-scale-001'

@secure()
param operatorPrincipalId string

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2026-03-15' existing = {
  name: cosmosAccountName
}
resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2026-03-15' existing = {
  parent: cosmos
  name: databaseName
}
resource catalog 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2026-03-15' = if (includeCatalog) {
  parent: database
  name: catalogContainerName
  properties: {
    resource: {
      id: catalogContainerName
      partitionKey: {
        paths: ['/scopeId']
        kind: 'Hash'
        version: 2
      }
      fullTextPolicy: {
        defaultLanguage: 'en-US'
        fullTextPaths: [{ path: '/searchText', language: 'en-US' }]
      }
      indexingPolicy: {
        automatic: true
        indexingMode: 'consistent'
        includedPaths: [{ path: '/*' }]
        excludedPaths: [{ path: '/"_etag"/?' }]
        fullTextIndexes: [{ path: '/searchText' }]
      }
    }
    options: {}
  }
}
resource importer 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2026-03-15' = if (includeCatalog) {
  parent: cosmos
  name: guid(cosmos.id, catalog!.id, operatorPrincipalId, 'catalog-importer')
  properties: {
    principalId: operatorPrincipalId
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    scope: '${cosmos.id}/dbs/${databaseName}/colls/${catalogContainerName}'
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2026-09-01' existing = {
  name: storageAccountName
}
resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2026-09-01' existing = {
  parent: storage
  name: 'default'
}
resource images 'Microsoft.Storage/storageAccounts/blobServices/containers@2026-09-01' = {
  parent: blobs
  name: imageContainerName
  properties: {
    publicAccess: 'Blob'
  }
}
resource uploader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(images.id, operatorPrincipalId, 'image-uploader')
  scope: images
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: operatorPrincipalId
    principalType: 'User'
  }
}

output catalogContainer string = includeCatalog ? catalogContainerName : ''
output imageContainer string = images.name
output imageBaseUrl string = 'https://${storageAccountName}.blob.${environment().suffixes.storage}'
