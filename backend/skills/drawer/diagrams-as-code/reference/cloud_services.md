# Cloud service → exact import cheatsheet (non-AWS)

The `diagrams` class names for Azure / GCP / OCI / IBM / Alibaba are NOT obvious
from the product name (e.g. "Azure Functions" → `FunctionApps`, "Cloud Run" →
`Run`). Look the service up here FIRST; fall back to `reference/nodes.md` (grep)
only if it is not listed. Wrong imports crash the render.

**Rules**
- Use the matching provider's nodes for the WHOLE diagram. Do NOT borrow an AWS
  node (or icon) into an Azure/GCP/OCI/IBM diagram.
- **No built-in class for a service?** Use the bundled icon pack for the SAME
  provider via `Custom`: `Custom("Service", "/icons/<provider>/<category>/<name>.png")`
  (call `search_icons("<service>", provider="<provider>")` first; never guess a
  path). Only if the pack has nothing either, use a generic node
  (`diagrams.generic.*`) or an `onprem`/`saas` logo.
- **OCI** classes come in a colored and a `*White` variant (`VM` vs `VMWhite`).
  Use the plain (colored) name for normal light-background diagrams.

---

## Azure  (`from diagrams.azure.<module> import <Class>`)
| Service | Import |
|---|---|
| App Service / Web App | `compute.AppServices` (or `web.AppServices`) |
| Azure Functions | `compute.FunctionApps` |
| AKS (Kubernetes) | `compute.AKS` |
| Virtual Machine | `compute.VM` |
| Container Instances | `compute.ContainerInstances` |
| Container Registry (ACR) | `compute.ContainerRegistries` (or `compute.ACR`) |
| Azure SQL Database | `database.SQLDatabases` |
| Cosmos DB | `database.CosmosDb` |
| Cache for Redis | `database.CacheForRedis` |
| PostgreSQL | `database.DatabaseForPostgresqlServers` |
| Blob Storage | `storage.BlobStorage` |
| Storage Account | `storage.StorageAccounts` |
| Service Bus | `integration.ServiceBus` |
| API Management | `integration.APIManagement` |
| Logic Apps | `integration.LogicApps` |
| Event Grid | `integration.EventGridTopics` |
| Event Hubs | `analytics.EventHubs` |
| Synapse Analytics | `analytics.SynapseAnalytics` |
| Databricks | `analytics.Databricks` |
| Stream Analytics | `analytics.StreamAnalyticsJobs` |
| Application Gateway | `network.ApplicationGateway` |
| Load Balancer | `network.LoadBalancers` |
| Front Door | `network.FrontDoors` |
| Firewall | `network.Firewall` |
| DNS | `network.DNSZones` |
| Virtual Network (VNet) | `network.VirtualNetworks` |
| Key Vault | `security.KeyVaults` |
| Sentinel | `security.Sentinel` |
| Azure AD / Entra ID | `identity.ActiveDirectory` |
| Cognitive Services | `ml.CognitiveServices` |
| Azure OpenAI | `ml.AzureOpenAI` |
| ML Workspace | `ml.MachineLearningServiceWorkspaces` |
| IoT Hub | `iot.IotHub` |

## GCP  (`from diagrams.gcp.<module> import <Class>`)
| Service | Import |
|---|---|
| Compute Engine (GCE) | `compute.ComputeEngine` (or `compute.GCE`) |
| GKE (Kubernetes) | `compute.GKE` (or `compute.KubernetesEngine`) |
| Cloud Run | `compute.Run` |
| Cloud Functions | `compute.Functions` (or `compute.GCF`) |
| App Engine | `compute.AppEngine` (or `compute.GAE`) |
| Cloud SQL | `database.SQL` |
| Firestore | `database.Firestore` |
| Spanner | `database.Spanner` |
| Bigtable | `database.BigTable` |
| Memorystore | `database.Memorystore` |
| BigQuery | `analytics.BigQuery` |
| Pub/Sub | `analytics.PubSub` |
| Dataflow | `analytics.Dataflow` |
| Dataproc | `analytics.Dataproc` |
| Cloud Storage (GCS) | `storage.GCS` (or `storage.Storage`) |
| Filestore | `storage.Filestore` |
| Cloud Load Balancing | `network.LoadBalancing` |
| Cloud DNS | `network.DNS` |
| Cloud CDN | `network.CDN` |
| VPC | `network.VPC` |
| Cloud Armor | `network.Armor` |
| API Gateway | `api.APIGateway` |
| Apigee | `api.Apigee` |
| IAM | `security.Iam` |
| KMS | `security.KMS` |
| Security Command Center | `security.SecurityCommandCenter` |
| Vertex AI / AI Platform | `ml.AIPlatform` |
| AutoML | `ml.AutoML` |
| Vision API | `ml.VisionAPI` |
| Cloud Logging | `operations.Logging` |
| Cloud Monitoring | `operations.Monitoring` |
| IoT Core | `iot.IotCore` |

## OCI  (`from diagrams.oci.<module> import <Class>`; plain name, not `*White`)
| Service | Import |
|---|---|
| Virtual Machine | `compute.VirtualMachine` |
| Container Engine (OKE) | `compute.OKE` (or `compute.ContainerEngine`) |
| Functions | `compute.Functions` |
| Container Registry (OCIR) | `compute.OCIRegistry` |
| Autonomous Database | `database.Autonomous` |
| Database Service | `database.DatabaseService` |
| Object Storage | `storage.ObjectStorage` |
| Block Storage | `storage.BlockStorage` |
| File Storage | `storage.FileStorage` |
| Load Balancer | `network.LoadBalancer` |
| VCN | `network.Vcn` |
| Internet Gateway | `network.InternetGateway` |
| Firewall | `network.Firewall` |
| API Gateway | `devops.APIGateway` |
| Vault | `security.Vault` |
| Cloud Guard | `security.CloudGuard` |
| WAF | `security.WAF` |

## IBM Cloud  (`from diagrams.ibm.<module> import <Class>`)
| Service | Import |
|---|---|
| Virtual Server / Instance | `compute.Instance` |
| Bare Metal Server | `compute.BareMetalServer` |
| VPC | `network.Vpc` |
| Load Balancer | `network.LoadBalancer` |
| Gateway | `network.Gateway` |
| Subnet | `network.Subnet` |
| Object Storage | `storage.ObjectStorage` |
| Block Storage | `storage.BlockStorage` |
| User (entry actor) | `user.User` |
| IAM | `general.IdentityAccessManagement` |
| Monitoring | `general.Monitoring` |
| Cloudant (DB) | `general.Cloudant` |

> IBM has no dedicated managed-DB classes (no RDS/SQL-DB equivalent). For a
> specific IBM database use `general.Cloudant`, a `generic`/`onprem` DB node, or
> `Custom(..., "/icons/ibm/...")`.

## Alibaba Cloud  (`from diagrams.alibabacloud.<module> import <Class>`)
| Service | Import |
|---|---|
| ECS (Elastic Compute) | `compute.ECS` (or `compute.ElasticComputeService`) |
| Container Service | `compute.ContainerService` |
| Function Compute | `compute.FunctionCompute` |
| Server Load Balancer (SLB) | `compute.ServerLoadBalancer` (or `network.SLB`) |
| RDS | `database.RDS` (or `database.RelationalDatabaseService`) |
| ApsaraDB for Redis | `database.ApsaradbRedis` |
| Object Storage (OSS) | `storage.OSS` (or `storage.ObjectStorageService`) |
| VPC | `network.VPC` |
| NAT Gateway | `network.NatGateway` |
| CDN | `network.Cdn` |
| WAF | `security.WAF` |

---

## Non-cloud tech logos (any provider's diagram)
For databases/brokers/runtimes that aren't a cloud service, use these instead of
a cloud node:
- `from diagrams.onprem.database import PostgreSQL, MongoDB, Cassandra`
- `from diagrams.onprem.inmemory import Redis`
- `from diagrams.onprem.queue import Kafka`
- `from diagrams.programming.language import Python, Go, Java` /
  `from diagrams.programming.framework import React, Django`
- Brand logo with no built-in node → call `fetch_logo("<Product>")` tool,
  use the returned path in `Custom("<Product>", "<PATH>")`.
