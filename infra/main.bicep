targetScope = 'subscription'

@description('Isolated resource group for the synthetic Search POC.')
param resourceGroupName string = 'rg-rezolve-search-poc-uks'

@description('Single Azure region for this serverless development account.')
param location string = 'uksouth'

@secure()
@description('Entra object ID of the operator authorized to import the synthetic catalogue.')
param operatorPrincipalId string

@description('Additional explicit development IPv4 addresses; keep personal addresses in private parameters.')
param allowedClientIps array = []

@description('User-approved client CIDR ranges for the POC data plane.')
param allowedClientCidrs array = [
  '85.210.10.0/24'
]

@description('Allow the published Azure Public portal middleware addresses for NoSQL accounts.')
param allowAzurePortalMiddleware bool = true

@description('Versioned, immutable catalogue container and import epoch.')
param containerName string = 'catalog-images-001'

@minLength(3)
@maxLength(24)
@description('Environment-specific storage account name; changing it does not change Cosmos image paths.')
param storageAccountName string = 'strezolve${uniqueString(subscription().id, resourceGroupName)}'

param imageContainerName string = 'product-images'

@description('Anonymous read of synthetic images only; upload and management still require Entra.')
param allowPublicImageRead bool = true

resource group 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: resourceGroupName
  location: location
  tags: {
    application: 'rezolve-commerce-search'
    environment: 'poc'
    dataClassification: 'synthetic'
    managedBy: 'bicep'
    SecurityControl: 'Ignore'
  }
}

module cosmos './cosmos.bicep' = {
  name: 'cosmos-search-backend'
  scope: group
  params: {
    location: location
    operatorPrincipalId: operatorPrincipalId
    allowedClientIps: allowedClientIps
    allowedClientCidrs: allowedClientCidrs
    allowAzurePortalMiddleware: allowAzurePortalMiddleware
    containerName: containerName
  }
}

module images './storage.bicep' = {
  name: 'catalog-image-storage'
  scope: group
  params: {
    location: location
    accountName: storageAccountName
    containerName: imageContainerName
    operatorPrincipalId: operatorPrincipalId
    allowPublicImageRead: allowPublicImageRead
  }
}

output resourceGroupName string = group.name
output accountName string = cosmos.outputs.accountName
output endpoint string = cosmos.outputs.endpoint
output databaseName string = cosmos.outputs.databaseName
output containerName string = cosmos.outputs.containerName
output importEpoch string = containerName
output storageAccountName string = images.outputs.accountName
output imageContainerName string = images.outputs.containerName
output imageBaseUrl string = images.outputs.blobEndpoint
