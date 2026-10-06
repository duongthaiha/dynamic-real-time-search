targetScope = 'resourceGroup'

param location string = resourceGroup().location
param accountName string
param containerName string = 'product-images'
param allowPublicImageRead bool = true

@secure()
param operatorPrincipalId string

resource account 'Microsoft.Storage/storageAccounts@2026-09-01' = {
  name: accountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  tags: union(resourceGroup().tags, {
    SecurityControl: 'Ignore'
  })
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    allowBlobPublicAccess: allowPublicImageRead
    publicNetworkAccess: 'Enabled'
    // Browsers fetch only synthetic public blobs; control/write requests require Entra.
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'None'
    }
  }
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2026-09-01' = {
  parent: account
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource images 'Microsoft.Storage/storageAccounts/blobServices/containers@2026-09-01' = {
  parent: blobs
  name: containerName
  properties: {
    publicAccess: allowPublicImageRead ? 'Blob' : 'None'
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

output accountName string = account.name
output containerName string = images.name
output blobEndpoint string = account.properties.primaryEndpoints.blob
