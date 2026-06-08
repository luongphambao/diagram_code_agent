# diagrams node catalog

Every importable node class in the installed `diagrams` package (1998 classes, 17 providers). Import as `from diagrams.<provider>.<module> import <Class>`. Use ONLY names that appear here — do not guess.

## alibabacloud

`diagrams.alibabacloud.analytics`: AnalyticDb, ClickHouse, DataLakeAnalytics, ElaticMapReduce, OpenSearch

`diagrams.alibabacloud.application`: ApiGateway, BeeBot, BlockchainAsAService, CloudCallCenter, CodePipeline, DirectMail, LogService, MNS, MessageNotificationService, NodeJsPerformancePlatform, OpenSearch, PTS, PerformanceTestingService, RdCloud, SCA, SLS, SmartConversationAnalysis, Yida

`diagrams.alibabacloud.communication`: DirectMail, MobilePush

`diagrams.alibabacloud.compute`: AutoScaling, BatchCompute, ContainerRegistry, ContainerService, ECI, ECS, EHPC, ESS, ElasticComputeService, ElasticContainerInstance, ElasticHighPerformanceComputing, ElasticSearch, FC, FunctionCompute, OOS, OperationOrchestrationService, ROS, ResourceOrchestrationService, SAE, SAS, SLB, ServerLoadBalancer, ServerlessAppEngine, SimpleApplicationServer, WAS, WebAppService

`diagrams.alibabacloud.database`: ApsaradbCassandra, ApsaradbHbase, ApsaradbMemcache, ApsaradbMongodb, ApsaradbOceanbase, ApsaradbPolardb, ApsaradbPostgresql, ApsaradbPpas, ApsaradbRedis, ApsaradbSqlserver, DBS, DMS, DRDS, DTS, DataManagementService, DataTransmissionService, DatabaseBackupService, DisributeRelationalDatabaseService, GDS, GraphDatabaseService, HybriddbForMysql, RDS, RelationalDatabaseService

`diagrams.alibabacloud.iot`: IotInternetDeviceId, IotLinkWan, IotMobileConnectionPackage, IotPlatform

`diagrams.alibabacloud.network`: CEN, Cdn, CloudEnterpriseNetwork, EIP, ElasticIpAddress, ExpressConnect, NatGateway, SLB, ServerLoadBalancer, SmartAccessGateway, VPC, VirtualPrivateCloud, VpnGateway

`diagrams.alibabacloud.security`: ABS, AS, AntiBotService, AntiDdosBasic, AntiDdosPro, AntifraudService, BastionHost, CFW, CM, CloudFirewall, CloudSecurityScanner, ContentModeration, CrowdsourcedSecurityTesting, DES, DataEncryptionService, DbAudit, GameShield, IdVerification, ManagedSecurityService, SecurityCenter, ServerGuard, SslCertificates, WAF, WebApplicationFirewall

`diagrams.alibabacloud.storage`: CloudStorageGateway, FileStorageHdfs, FileStorageNas, HBR, HDFS, HDR, HybridBackupRecovery, HybridCloudDisasterRecovery, Imm, NAS, OSS, OTS, ObjectStorageService, ObjectTableStore

`diagrams.alibabacloud.web`: Dns, Domain

## aws

`diagrams.aws.analytics`: AmazonOpensearchService, Analytics, Athena, Cloudsearch, CloudsearchSearchDocuments, DataLakeResource, DataPipeline, EMR, EMRCluster, EMREngine, EMREngineMaprM3, EMREngineMaprM5, EMREngineMaprM7, EMRHdfsCluster, ES, ElasticsearchService, Glue, GlueCrawlers, GlueDataCatalog, Kinesis, KinesisDataAnalytics, KinesisDataFirehose, KinesisDataStreams, KinesisVideoStreams, LakeFormation, ManagedStreamingForKafka, Quicksight, Redshift, RedshiftDenseComputeNode, RedshiftDenseStorageNode

`diagrams.aws.ar`: ArVr, Sumerian

`diagrams.aws.blockchain`: Blockchain, BlockchainResource, ManagedBlockchain, QLDB, QuantumLedgerDatabaseQldb

`diagrams.aws.business`: A4B, AlexaForBusiness, BusinessApplications, Chime, Workmail

`diagrams.aws.compute`: AMI, AppRunner, ApplicationAutoScaling, AutoScaling, Batch, Compute, ComputeOptimizer, EB, EC2, EC2Ami, EC2AutoScaling, EC2ContainerRegistry, EC2ContainerRegistryImage, EC2ContainerRegistryRegistry, EC2ElasticIpAddress, EC2ImageBuilder, EC2Instance, EC2Instances, EC2Rescue, EC2SpotInstance, ECR, ECS, EKS, ElasticBeanstalk, ElasticBeanstalkApplication, ElasticBeanstalkDeployment, ElasticContainerService, ElasticContainerServiceContainer, ElasticContainerServiceService, ElasticKubernetesService, Fargate, Lambda, LambdaFunction, Lightsail, LocalZones, Outposts, SAR, ServerlessApplicationRepository, ThinkboxDeadline, ThinkboxDraft, ThinkboxFrost, ThinkboxKrakatoa, ThinkboxSequoia, ThinkboxStoke, ThinkboxXmesh, VmwareCloudOnAWS, Wavelength

`diagrams.aws.cost`: Budgets, CostAndUsageReport, CostExplorer, CostManagement, ReservedInstanceReporting, SavingsPlans

`diagrams.aws.database`: Aurora, AuroraInstance, DAX, DB, DDB, DMS, Database, DatabaseMigrationService, DatabaseMigrationServiceDatabaseMigrationWorkflow, DocumentDB, DocumentdbMongodbCompatibility, Dynamodb, DynamodbAttribute, DynamodbAttributes, DynamodbDax, DynamodbGSI, DynamodbGlobalSecondaryIndex, DynamodbItem, DynamodbItems, DynamodbStreams, DynamodbTable, ElastiCache, Elasticache, ElasticacheCacheNode, ElasticacheForMemcached, ElasticacheForRedis, KeyspacesManagedApacheCassandraService, Neptune, QLDB, QuantumLedgerDatabaseQldb, RDS, RDSInstance, RDSMariadbInstance, RDSMysqlInstance, RDSOnVmware, RDSOracleInstance, RDSPostgresqlInstance, RDSSqlServerInstance, Redshift, RedshiftDenseComputeNode, RedshiftDenseStorageNode, Timestream

`diagrams.aws.devtools`: CLI, Cloud9, Cloud9Resource, CloudDevelopmentKit, Codeartifact, Codebuild, Codecommit, Codedeploy, Codepipeline, Codestar, CommandLineInterface, DevTools, DeveloperTools, ToolsAndSdks, XRay

`diagrams.aws.enablement`: CustomerEnablement, Iq, ManagedServices, ProfessionalServices, Support

`diagrams.aws.enduser`: Appstream20, DesktopAndAppStreaming, Workdocs, Worklink, Workspaces

`diagrams.aws.engagement`: Connect, CustomerEngagement, Pinpoint, SES, SimpleEmailServiceSes, SimpleEmailServiceSesEmail

`diagrams.aws.game`: GameTech, Gamelift

`diagrams.aws.general`: Client, Disk, Forums, General, GenericDatabase, GenericFirewall, GenericOfficeBuilding, GenericSDK, GenericSamlToken, InternetAlt1, InternetAlt2, InternetGateway, Marketplace, MobileClient, Multimedia, OfficeBuilding, SDK, SamlToken, SslPadlock, TapeStorage, Toolkit, TraditionalServer, User, Users

`diagrams.aws.integration`: ApplicationIntegration, Appsync, ConsoleMobileApplication, EventResource, Eventbridge, EventbridgeCustomEventBusResource, EventbridgeDefaultEventBusResource, EventbridgeSaasPartnerEventBusResource, ExpressWorkflows, MQ, SF, SNS, SQS, SimpleNotificationServiceSns, SimpleNotificationServiceSnsEmailNotification, SimpleNotificationServiceSnsHttpNotification, SimpleNotificationServiceSnsTopic, SimpleQueueServiceSqs, SimpleQueueServiceSqsMessage, SimpleQueueServiceSqsQueue, StepFunctions

`diagrams.aws.iot`: FreeRTOS, Freertos, InternetOfThings, Iot1Click, IotAction, IotActuator, IotAlexaEcho, IotAlexaEnabledDevice, IotAlexaSkill, IotAlexaVoiceService, IotAnalytics, IotAnalyticsChannel, IotAnalyticsDataSet, IotAnalyticsDataStore, IotAnalyticsNotebook, IotAnalyticsPipeline, IotBank, IotBicycle, IotBoard, IotButton, IotCamera, IotCar, IotCart, IotCertificate, IotCoffeePot, IotCore, IotDesiredState, IotDeviceDefender, IotDeviceGateway, IotDeviceManagement, IotDoorLock, IotEvents, IotFactory, IotFireTv, IotFireTvStick, IotGeneric, IotGreengrass, IotGreengrassConnector, IotHardwareBoard, IotHouse, IotHttp, IotHttp2, IotJobs, IotLambda, IotLightbulb, IotMedicalEmergency, IotMqtt, IotOverTheAirUpdate, IotPolicy, IotPolicyEmergency, IotReportedState, IotRule, IotSensor, IotServo, IotShadow, IotSimulator, IotSitewise, IotThermostat, IotThingsGraph, IotTopic, IotTravel, IotUtility, IotWindfarm

`diagrams.aws.management`: AmazonDevopsGuru, AmazonManagedGrafana, AmazonManagedPrometheus, AmazonManagedWorkflowsApacheAirflow, AutoScaling, Chatbot, Cloudformation, CloudformationChangeSet, CloudformationStack, CloudformationTemplate, Cloudtrail, Cloudwatch, CloudwatchAlarm, CloudwatchEventEventBased, CloudwatchEventTimeBased, CloudwatchLogs, CloudwatchRule, Codeguru, CommandLineInterface, Config, ControlTower, LicenseManager, ManagedServices, ManagementAndGovernance, ManagementConsole, Opsworks, OpsworksApps, OpsworksDeployments, OpsworksInstances, OpsworksLayers, OpsworksMonitoring, OpsworksPermissions, OpsworksResources, OpsworksStack, Organizations, OrganizationsAccount, OrganizationsOrganizationalUnit, ParameterStore, PersonalHealthDashboard, Proton, SSM, ServiceCatalog, SystemsManager, SystemsManagerAppConfig, SystemsManagerAutomation, SystemsManagerDocuments, SystemsManagerInventory, SystemsManagerMaintenanceWindows, SystemsManagerOpscenter, SystemsManagerParameterStore, SystemsManagerPatchManager, SystemsManagerRunCommand, SystemsManagerStateManager, TrustedAdvisor, TrustedAdvisorChecklist, TrustedAdvisorChecklistCost, TrustedAdvisorChecklistFaultTolerant, TrustedAdvisorChecklistPerformance, TrustedAdvisorChecklistSecurity, WellArchitectedTool

`diagrams.aws.media`: ElasticTranscoder, ElementalConductor, ElementalDelta, ElementalLive, ElementalMediaconnect, ElementalMediaconvert, ElementalMedialive, ElementalMediapackage, ElementalMediastore, ElementalMediatailor, ElementalServer, KinesisVideoStreams, MediaServices

`diagrams.aws.migration`: ADS, ApplicationDiscoveryService, CEM, CloudendureMigration, DMS, DatabaseMigrationService, Datasync, DatasyncAgent, MAT, MigrationAndTransfer, MigrationHub, SMS, ServerMigrationService, Snowball, SnowballEdge, Snowmobile, TransferForSftp

`diagrams.aws.ml`: ApacheMxnetOnAWS, AugmentedAi, Bedrock, Comprehend, DLC, DeepLearningAmis, DeepLearningContainers, Deepcomposer, Deeplens, Deepracer, ElasticInference, Forecast, FraudDetector, Kendra, Lex, MachineLearning, Personalize, Polly, Rekognition, RekognitionImage, RekognitionVideo, Sagemaker, SagemakerGroundTruth, SagemakerModel, SagemakerNotebook, SagemakerTrainingJob, TensorflowOnAWS, Textract, Transcribe, Translate

`diagrams.aws.mobile`: APIGateway, APIGatewayEndpoint, Amplify, Appsync, DeviceFarm, Mobile, Pinpoint

`diagrams.aws.network`: ALB, APIGateway, APIGatewayEndpoint, AppMesh, CF, CLB, ClientVpn, CloudFront, CloudFrontDownloadDistribution, CloudFrontEdgeLocation, CloudFrontStreamingDistribution, CloudMap, DirectConnect, ELB, ElasticLoadBalancing, ElbApplicationLoadBalancer, ElbClassicLoadBalancer, ElbNetworkLoadBalancer, Endpoint, GAX, GlobalAccelerator, IGW, InternetGateway, NATGateway, NLB, Nacl, NetworkFirewall, NetworkingAndContentDelivery, PrivateSubnet, Privatelink, PublicSubnet, Route53, Route53HostedZone, RouteTable, SiteToSiteVpn, TGW, TGWAttach, TransitGateway, TransitGatewayAttachment, VPC, VPCCustomerGateway, VPCElasticNetworkAdapter, VPCElasticNetworkInterface, VPCFlowLogs, VPCPeering, VPCRouter, VPCTrafficMirroring, VpnConnection, VpnGateway

`diagrams.aws.quantum`: Braket, QuantumTechnologies

`diagrams.aws.robotics`: Robomaker, RobomakerCloudExtensionRos, RobomakerDevelopmentEnvironment, RobomakerFleetManagement, RobomakerSimulator, Robotics

`diagrams.aws.satellite`: GroundStation, Satellite

`diagrams.aws.security`: ACM, AdConnector, Artifact, CertificateAuthority, CertificateManager, CloudDirectory, CloudHSM, Cloudhsm, Cognito, DS, Detective, DirectoryService, FMS, FirewallManager, Guardduty, IAM, IAMAWSSts, IAMAccessAnalyzer, IAMPermissions, IAMRole, IdentityAndAccessManagementIam, IdentityAndAccessManagementIamAWSSts, IdentityAndAccessManagementIamAWSStsAlternate, IdentityAndAccessManagementIamAccessAnalyzer, IdentityAndAccessManagementIamAddOn, IdentityAndAccessManagementIamDataEncryptionKey, IdentityAndAccessManagementIamEncryptedData, IdentityAndAccessManagementIamLongTermSecurityCredential, IdentityAndAccessManagementIamMfaToken, IdentityAndAccessManagementIamPermissions, IdentityAndAccessManagementIamRole, IdentityAndAccessManagementIamTemporarySecurityCredential, Inspector, InspectorAgent, KMS, KeyManagementService, Macie, ManagedMicrosoftAd, RAM, ResourceAccessManager, SecretsManager, SecurityHub, SecurityHubFinding, SecurityIdentityAndCompliance, Shield, ShieldAdvanced, SimpleAd, SingleSignOn, WAF, WAFFilteringRule

`diagrams.aws.storage`: Backup, CDR, CloudendureDisasterRecovery, EBS, EFS, EFSInfrequentaccessPrimaryBg, EFSStandardPrimaryBg, ElasticBlockStoreEBS, ElasticBlockStoreEBSSnapshot, ElasticBlockStoreEBSVolume, ElasticFileSystemEFS, ElasticFileSystemEFSFileSystem, FSx, Fsx, FsxForLustre, FsxForWindowsFileServer, MultipleVolumesResource, S3, S3AccessPoints, S3Glacier, S3GlacierArchive, S3GlacierVault, S3ObjectLambdaAccessPoints, SimpleStorageServiceS3, SimpleStorageServiceS3Bucket, SimpleStorageServiceS3BucketWithObjects, SimpleStorageServiceS3Object, SnowFamilySnowballImportExport, Snowball, SnowballEdge, Snowmobile, Storage, StorageGateway, StorageGatewayCachedVolume, StorageGatewayNonCachedVolume, StorageGatewayVirtualTapeLibrary

## azure

`diagrams.azure.analytics`: AnalysisServices, DataExplorerClusters, DataFactories, DataLakeAnalytics, DataLakeStoreGen1, Databricks, EventHubClusters, EventHubs, Hdinsightclusters, LogAnalyticsWorkspaces, StreamAnalyticsJobs, SynapseAnalytics

`diagrams.azure.compute`: ACR, AKS, AppServices, AutomanagedVM, AvailabilitySets, BatchAccounts, CitrixVirtualDesktopsEssentials, CloudServices, CloudServicesClassic, CloudsimpleVirtualMachines, ContainerApps, ContainerInstances, ContainerRegistries, DiskEncryptionSets, DiskSnapshots, Disks, FunctionApps, ImageDefinitions, ImageVersions, KubernetesServices, MeshApplications, OsImages, SAPHANAOnAzure, ServiceFabricClusters, SharedImageGalleries, SpringCloud, VM, VMClassic, VMImages, VMLinux, VMSS, VMScaleSet, VMWindows, Workspaces

`diagrams.azure.database`: BlobStorage, CacheForRedis, CosmosDb, DataExplorerClusters, DataFactory, DataLake, DatabaseForMariadbServers, DatabaseForMysqlServers, DatabaseForPostgresqlServers, ElasticDatabasePools, ElasticJobAgents, InstancePools, ManagedDatabases, SQL, SQLDatabases, SQLDatawarehouse, SQLManagedInstances, SQLServerStretchDatabases, SQLServers, SQLVM, SsisLiftAndShiftIr, SynapseAnalytics, VirtualClusters, VirtualDatacenter

`diagrams.azure.devops`: ApplicationInsights, Artifacts, Boards, Devops, DevtestLabs, LabServices, Pipelines, Repos, TestPlans

`diagrams.azure.general`: Allresources, Azurehome, Developertools, Helpsupport, Information, Managementgroups, Marketplace, Quickstartcenter, Recent, Reservations, Resource, Resourcegroups, Servicehealth, Shareddashboard, Subscriptions, Support, Supportrequests, Tag, Tags, Templates, Twousericon, Userhealthicon, Usericon, Userprivacy, Userresource, Whatsnew

`diagrams.azure.identity`: ADB2C, ADDomainServices, ADIdentityProtection, ADPrivilegedIdentityManagement, AccessReview, ActiveDirectory, ActiveDirectoryConnectHealth, AppRegistrations, ConditionalAccess, EnterpriseApplications, Groups, IdentityGovernance, InformationProtection, ManagedIdentities, Users

`diagrams.azure.integration`: APIForFhir, APIManagement, AppConfiguration, DataCatalog, EventGridDomains, EventGridSubscriptions, EventGridTopics, IntegrationAccounts, IntegrationServiceEnvironments, LogicApps, LogicAppsCustomConnector, PartnerTopic, SendgridAccounts, ServiceBus, ServiceBusRelays, ServiceCatalogManagedApplicationDefinitions, SoftwareAsAService, StorsimpleDeviceManagers, SystemTopic

`diagrams.azure.iot`: DeviceProvisioningServices, DigitalTwins, IotCentralApplications, IotHub, IotHubSecurity, Maps, Sphere, TimeSeriesInsightsEnvironments, TimeSeriesInsightsEventsSources, Windows10IotCoreServices

`diagrams.azure.migration`: DataBox, DataBoxEdge, DatabaseMigrationServices, MigrationProjects, RecoveryServicesVaults

`diagrams.azure.ml`: AzureOpenAI, AzureSpeedToText, BatchAI, BotServices, CognitiveServices, GenomicsAccounts, MachineLearningServiceWorkspaces, MachineLearningStudioWebServicePlans, MachineLearningStudioWebServices, MachineLearningStudioWorkspaces

`diagrams.azure.mobile`: AppServiceMobile, MobileEngagement, NotificationHubs

`diagrams.azure.monitor`: ChangeAnalysis, Logs, Metrics, Monitor

`diagrams.azure.network`: ApplicationGateway, ApplicationSecurityGroups, CDNProfiles, Connections, DDOSProtectionPlans, DNSPrivateZones, DNSZones, ExpressrouteCircuits, Firewall, FrontDoors, LoadBalancers, LocalNetworkGateways, NetworkInterfaces, NetworkSecurityGroupsClassic, NetworkWatcher, OnPremisesDataGateways, PrivateEndpoint, PublicIpAddresses, ReservedIpAddressesClassic, RouteFilters, RouteTables, ServiceEndpointPolicies, Subnets, TrafficManagerProfiles, VirtualNetworkClassic, VirtualNetworkGateways, VirtualNetworks, VirtualWans

`diagrams.azure.security`: ApplicationSecurityGroups, ConditionalAccess, Defender, ExtendedSecurityUpdates, KeyVaults, SecurityCenter, Sentinel

`diagrams.azure.storage`: ArchiveStorage, Azurefxtedgefiler, BlobStorage, DataBox, DataBoxEdgeDataBoxGateway, DataLakeStorage, GeneralStorage, NetappFiles, QueuesStorage, StorageAccounts, StorageAccountsClassic, StorageExplorer, StorageSyncServices, StorsimpleDataManagers, StorsimpleDeviceManagers, TableStorage

`diagrams.azure.web`: APIConnections, AppServiceCertificates, AppServiceDomains, AppServiceEnvironments, AppServicePlans, AppServices, MediaServices, NotificationHubNamespaces, Search, Signalr

## digitalocean

`diagrams.digitalocean.compute`: Containers, Docker, Droplet, DropletConnect, DropletSnapshot, K8SCluster, K8SNode, K8SNodePool

`diagrams.digitalocean.database`: DbaasPrimary, DbaasPrimaryStandbyMore, DbaasReadOnly, DbaasStandby

`diagrams.digitalocean.network`: Certificate, Domain, DomainRegistration, Firewall, FloatingIp, InternetGateway, LoadBalancer, ManagedVpn, Vpc

`diagrams.digitalocean.storage`: Folder, Space, Volume, VolumeSnapshot

## elastic

`diagrams.elastic.agent`: Agent, Endpoint, Fleet, Integrations

`diagrams.elastic.beats`: APM, Auditbeat, Filebeat, Functionbeat, Heartbeat, Metricbeat, Packetbeat, Winlogbeat

`diagrams.elastic.elasticsearch`: Alerting, Beats, ElasticSearch, Elasticsearch, Kibana, LogStash, Logstash, LogstashPipeline, ML, MachineLearning, MapServices, Maps, Monitoring, SQL, SearchableSnapshots, SecuritySettings, Stack

`diagrams.elastic.enterprisesearch`: AppSearch, Crawler, EnterpriseSearch, SiteSearch, WorkplaceSearch

`diagrams.elastic.observability`: APM, Logs, Metrics, Observability, Uptime

`diagrams.elastic.orchestration`: ECE, ECK

`diagrams.elastic.saas`: Cloud, Elastic

`diagrams.elastic.security`: Endpoint, SIEM, Security, Xdr

## firebase

`diagrams.firebase.base`: Firebase

`diagrams.firebase.develop`: Authentication, Firestore, Functions, Hosting, MLKit, RealtimeDatabase, Storage

`diagrams.firebase.extentions`: Extensions

`diagrams.firebase.grow`: ABTesting, AppIndexing, DynamicLinks, FCM, InAppMessaging, Invites, Messaging, Predictions, RemoteConfig

`diagrams.firebase.quality`: AppDistribution, CrashReporting, Crashlytics, PerformanceMonitoring, TestLab

## gcp

`diagrams.gcp.analytics`: BigQuery, Bigquery, Composer, DataCatalog, DataFusion, Dataflow, Datalab, Dataprep, Dataproc, Genomics, PubSub, Pubsub

`diagrams.gcp.api`: APIGateway, Apigee, Endpoints

`diagrams.gcp.compute`: AppEngine, ComputeEngine, ContainerOptimizedOS, Functions, GAE, GCE, GCF, GKE, GKEOnPrem, GPU, KubernetesEngine, Run

`diagrams.gcp.database`: BigTable, Bigtable, Datastore, Firestore, Memorystore, SQL, Spanner

`diagrams.gcp.devtools`: Build, Code, CodeForIntellij, ContainerRegistry, GCR, GradleAppEnginePlugin, IdePlugins, MavenAppEnginePlugin, SDK, Scheduler, SourceRepositories, Tasks, TestLab, ToolsForEclipse, ToolsForPowershell, ToolsForVisualStudio

`diagrams.gcp.iot`: IotCore

`diagrams.gcp.migration`: TransferAppliance

`diagrams.gcp.ml`: AIHub, AIPlatform, AIPlatformDataLabelingService, AdvancedSolutionsLab, AutoML, Automl, AutomlNaturalLanguage, AutomlTables, AutomlTranslation, AutomlVideoIntelligence, AutomlVision, DialogFlowEnterpriseEdition, InferenceAPI, JobsAPI, NLAPI, NaturalLanguageAPI, RecommendationsAI, STT, SpeechToText, TPU, TTS, TextToSpeech, TranslationAPI, VideoIntelligenceAPI, VisionAPI

`diagrams.gcp.network`: Armor, CDN, DNS, DedicatedInterconnect, ExternalIpAddresses, FirewallRules, LoadBalancing, NAT, Network, PartnerInterconnect, PremiumNetworkTier, Router, Routes, StandardNetworkTier, TrafficDirector, VPC, VPN, VirtualPrivateCloud

`diagrams.gcp.operations`: Logging, Monitoring

`diagrams.gcp.security`: IAP, Iam, KMS, KeyManagementService, ResourceManager, SCC, SecurityCommandCenter, SecurityScanner

`diagrams.gcp.storage`: Filestore, GCS, PersistentDisk, Storage

## generic

`diagrams.generic.blank`: Blank

`diagrams.generic.compute`: Rack

`diagrams.generic.database`: SQL

`diagrams.generic.device`: Mobile, Tablet

`diagrams.generic.network`: Firewall, Router, Subnet, Switch, VPN

`diagrams.generic.os`: Android, Centos, Debian, IOS, LinuxGeneral, Raspbian, RedHat, Suse, Ubuntu, Windows

`diagrams.generic.place`: Datacenter

`diagrams.generic.storage`: Storage

`diagrams.generic.virtualization`: Qemu, Virtualbox, Vmware, XEN

## gis

`diagrams.gis.cli`: Gdal, Imposm, Lastools, Mapnik, Mdal, Pdal

`diagrams.gis.cplusplus`: Mapnik

`diagrams.gis.data`: BAN, Here, IGN, Openstreetmap

`diagrams.gis.database`: Postgis

`diagrams.gis.desktop`: Maptunik, QGIS

`diagrams.gis.format`: Geopackage, Geoparquet

`diagrams.gis.geocoding`: Addok, Gisgraphy, Nominatim, Pelias

`diagrams.gis.java`: Geotools

`diagrams.gis.javascript`: Cesium, Geostyler, Keplerjs, Leaflet, Maplibre, OlExt, Openlayers, Turfjs

`diagrams.gis.mobile`: Mergin, Qfield, Smash

`diagrams.gis.ogc`: OGC, WFS, WMS

`diagrams.gis.organization`: Osgeo

`diagrams.gis.python`: Geopandas, Pysal

`diagrams.gis.routing`: Graphhopper, Osrm, Pgrouting, Valhalla

`diagrams.gis.server`: Actinia, Baremaps, Deegree, G3WSuite, Geohealthcheck, Geomapfish, Geomesa, Geonetwork, Geonode, Georchestra, Geoserver, Geowebcache, Kepler, Mapproxy, Mapserver, Mapstore, Mviewer, Pg_Tileserv, Pycsw, Pygeoapi, QGISServer, Zooproject

## ibm

`diagrams.ibm.analytics`: Analytics, DataIntegration, DataRepositories, DeviceAnalytics, StreamingComputing

`diagrams.ibm.applications`: ActionableInsight, Annotate, ApiDeveloperPortal, ApiPolyglotRuntimes, AppServer, ApplicationLogic, EnterpriseApplications, Index, IotApplication, Microservice, MobileApp, Ontology, OpenSourceTools, RuntimeServices, SaasApplications, ServiceBroker, SpeechToText, VisualRecognition, Visualization

`diagrams.ibm.blockchain`: Blockchain, BlockchainDeveloper, CertificateAuthority, ClientApplication, Communication, Consensus, Event, EventListener, ExistingEnterpriseSystems, HyperledgerFabric, KeyManagement, Ledger, Membership, MembershipServicesProviderApi, MessageBus, Node, Services, SmartContract, TransactionManager, Wallet

`diagrams.ibm.compute`: BareMetalServer, ImageService, Instance, Key, PowerInstance

`diagrams.ibm.data`: Caches, Cloud, ConversationTrainedDeployed, DataServices, DataSources, DeviceIdentityService, DeviceRegistry, EnterpriseData, EnterpriseUserDirectory, FileRepository, GroundTruth, Model, TmsDataInterface

`diagrams.ibm.devops`: ArtifactManagement, BuildTest, CodeEditor, CollaborativeDevelopment, ConfigurationManagement, ContinuousDeploy, ContinuousTesting, Devops, Provision, ReleaseManagement

`diagrams.ibm.general`: CloudMessaging, CloudServices, Cloudant, CognitiveServices, DataSecurity, Enterprise, GovernanceRiskCompliance, IBMContainers, IBMPublicCloud, IdentityAccessManagement, IdentityProvider, InfrastructureSecurity, Internet, IotCloud, MicroservicesApplication, MicroservicesMesh, Monitoring, MonitoringLogging, ObjectStorage, OfflineCapabilities, Openwhisk, PeerCloud, RetrieveRank, Scalable, ServiceDiscoveryConfiguration, TextToSpeech, TransformationConnectivity

`diagrams.ibm.infrastructure`: Channels, CloudMessaging, Dashboard, Diagnostics, EdgeServices, EnterpriseMessaging, EventFeed, InfrastructureServices, InterserviceCommunication, LoadBalancingRouting, MicroservicesMesh, MobileBackend, MobileProviderNetwork, Monitoring, MonitoringLogging, PeerServices, ServiceDiscoveryConfiguration, TransformationConnectivity

`diagrams.ibm.management`: AlertNotification, ApiManagement, CloudManagement, ClusterManagement, ContentManagement, DataServices, DeviceManagement, InformationGovernance, ItServiceManagement, Management, MonitoringMetrics, ProcessManagement, ProviderCloudPortalService, PushNotifications, ServiceManagementTools

`diagrams.ibm.network`: Bridge, DirectLink, Enterprise, Firewall, FloatingIp, Gateway, InternetServices, LoadBalancer, LoadBalancerListener, LoadBalancerPool, LoadBalancingRouting, PublicGateway, Region, Router, Rules, Subnet, TransitGateway, Vpc, VpnConnection, VpnGateway, VpnPolicy

`diagrams.ibm.security`: ApiSecurity, BlockchainSecurityService, DataSecurity, Firewall, Gateway, GovernanceRiskCompliance, IdentityAccessManagement, IdentityProvider, InfrastructureSecurity, PhysicalSecurity, SecurityMonitoringIntelligence, SecurityServices, TrustendComputing, Vpn

`diagrams.ibm.social`: Communities, FileSync, LiveCollaboration, Messaging, Networking

`diagrams.ibm.storage`: BlockStorage, ObjectStorage

`diagrams.ibm.user`: Browser, Device, IntegratedDigitalExperiences, PhysicalEntity, Sensor, User

## k8s

`diagrams.k8s.chaos`: ChaosMesh, LitmusChaos

`diagrams.k8s.clusterconfig`: HPA, HorizontalPodAutoscaler, LimitRange, Limits, Quota

`diagrams.k8s.compute`: Cronjob, DS, DaemonSet, Deploy, Deployment, Job, Pod, RS, ReplicaSet, STS, StatefulSet

`diagrams.k8s.controlplane`: API, APIServer, CCM, CM, ControllerManager, KProxy, KubeProxy, Kubelet, Sched, Scheduler

`diagrams.k8s.ecosystem`: ExternalDns, Helm, Krew, Kustomize

`diagrams.k8s.group`: NS, Namespace

`diagrams.k8s.infra`: ETCD, Master, Node

`diagrams.k8s.network`: Endpoint, Ep, Ing, Ingress, Netpol, NetworkPolicy, SVC, Service

`diagrams.k8s.others`: CRD, PSP

`diagrams.k8s.podconfig`: CM, ConfigMap, Secret

`diagrams.k8s.rbac`: CRB, CRole, ClusterRole, ClusterRoleBinding, Group, RB, Role, RoleBinding, SA, ServiceAccount, User

`diagrams.k8s.storage`: PV, PVC, PersistentVolume, PersistentVolumeClaim, SC, StorageClass, Vol, Volume

## oci

`diagrams.oci.compute`: Autoscale, AutoscaleWhite, BM, BMWhite, BareMetal, BareMetalWhite, Container, ContainerEngine, ContainerEngineWhite, ContainerWhite, Functions, FunctionsWhite, InstancePools, InstancePoolsWhite, OCIR, OCIRWhite, OCIRegistry, OCIRegistryWhite, OKE, OKEWhite, VM, VMWhite, VirtualMachine, VirtualMachineWhite

`diagrams.oci.connectivity`: Backbone, BackboneWhite, CDN, CDNWhite, CustomerDatacenter, CustomerDatacntrWhite, CustomerPremises, CustomerPremisesWhite, DNS, DNSWhite, DisconnectedRegions, DisconnectedRegionsWhite, FastConnect, FastConnectWhite, NATGateway, NATGatewayWhite, VPN, VPNWhite

`diagrams.oci.database`: ADB, ADBWhite, Autonomous, AutonomousWhite, BigdataService, BigdataServiceWhite, DBService, DBServiceWhite, DMS, DMSWhite, DatabaseService, DatabaseServiceWhite, DataflowApache, DataflowApacheWhite, Dcat, DcatWhite, Dis, DisWhite, Science, ScienceWhite, Stream, StreamWhite

`diagrams.oci.devops`: APIGateway, APIGatewayWhite, APIService, APIServiceWhite, ResourceMgmt, ResourceMgmtWhite

`diagrams.oci.governance`: Audit, AuditWhite, Compartments, CompartmentsWhite, Groups, GroupsWhite, Logging, LoggingWhite, OCID, OCIDWhite, Policies, PoliciesWhite, Tagging, TaggingWhite

`diagrams.oci.monitoring`: Alarm, AlarmWhite, Email, EmailWhite, Events, EventsWhite, HealthCheck, HealthCheckWhite, Notifications, NotificationsWhite, Queue, QueueWhite, Search, SearchWhite, Telemetry, TelemetryWhite, Workflow, WorkflowWhite

`diagrams.oci.network`: Drg, DrgWhite, Firewall, FirewallWhite, InternetGateway, InternetGatewayWhite, LoadBalancer, LoadBalancerWhite, RouteTable, RouteTableWhite, SecurityLists, SecurityListsWhite, ServiceGateway, ServiceGatewayWhite, Vcn, VcnWhite

`diagrams.oci.security`: CloudGuard, CloudGuardWhite, DDOS, DDOSWhite, Encryption, EncryptionWhite, IDAccess, IDAccessWhite, KeyManagement, KeyManagementWhite, MaxSecurityZone, MaxSecurityZoneWhite, Vault, VaultWhite, WAF, WAFWhite

`diagrams.oci.storage`: BackupRestore, BackupRestoreWhite, BlockStorage, BlockStorageClone, BlockStorageCloneWhite, BlockStorageWhite, Buckets, BucketsWhite, DataTransfer, DataTransferWhite, ElasticPerformance, ElasticPerformanceWhite, FileStorage, FileStorageWhite, ObjectStorage, ObjectStorageWhite, StorageGateway, StorageGatewayWhite

## onprem

`diagrams.onprem.aggregator`: Fluentd, Vector

`diagrams.onprem.analytics`: Beam, Databricks, Dbt, Dremio, Flink, Hadoop, Hive, Metabase, Norikra, PowerBI, Powerbi, Presto, Singer, Spark, Storm, Superset, Tableau, Trino

`diagrams.onprem.auth`: Boundary, BuzzfeedSso, Oauth2Proxy

`diagrams.onprem.cd`: Spinnaker, Tekton, TektonCli

`diagrams.onprem.certificates`: CertManager, LetsEncrypt

`diagrams.onprem.ci`: CircleCI, Circleci, ConcourseCI, Concourseci, DroneCI, Droneci, GithubActions, GitlabCI, Gitlabci, Jenkins, TC, Teamcity, TravisCI, Travisci, ZuulCI, Zuulci

`diagrams.onprem.client`: Client, User, Users

`diagrams.onprem.compute`: Nomad, Server

`diagrams.onprem.container`: Containerd, Crio, Docker, Firecracker, Gvisor, K3S, LXC, Lxc, RKT, Rkt

`diagrams.onprem.database`: Cassandra, ClickHouse, Clickhouse, CockroachDB, Cockroachdb, CouchDB, Couchbase, Couchdb, Dgraph, Druid, HBase, Hbase, InfluxDB, Influxdb, JanusGraph, Janusgraph, MSSQL, MariaDB, Mariadb, MongoDB, Mongodb, Mssql, MySQL, Mysql, Neo4J, Oracle, PostgreSQL, Postgresql, Scylla

`diagrams.onprem.dns`: Coredns, Powerdns

`diagrams.onprem.etl`: Embulk

`diagrams.onprem.gitops`: ArgoCD, Argocd, Flagger, Flux

`diagrams.onprem.groupware`: Nextcloud

`diagrams.onprem.iac`: Ansible, Atlantis, Awx, Pulumi, Puppet, Terraform

`diagrams.onprem.identity`: Dex

`diagrams.onprem.inmemory`: Aerospike, Hazelcast, Memcached, Redis

`diagrams.onprem.logging`: FluentBit, Fluentbit, Graylog, Loki, RSyslog, Rsyslog, SyslogNg

`diagrams.onprem.messaging`: Centrifugo

`diagrams.onprem.mlops`: Mlflow, Polyaxon

`diagrams.onprem.monitoring`: Cortex, Datadog, Dynatrace, Grafana, Humio, Mimir, Nagios, Newrelic, Prometheus, PrometheusOperator, Sentry, Splunk, Thanos, Zabbix

`diagrams.onprem.network`: Ambassador, Apache, Bind9, Caddy, Consul, ETCD, Envoy, Etcd, Glassfish, Gunicorn, HAProxy, Haproxy, Internet, Istio, Jbossas, Jetty, Kong, Linkerd, Mikrotik, Nginx, OPNSense, OSM, Ocelot, OpenServiceMesh, Opnsense, PFSense, Pfsense, Pomerium, Powerdns, Tomcat, Traefik, Tyk, VyOS, Vyos, Wildfly, Yarp, Zookeeper

`diagrams.onprem.proxmox`: ProxmoxVE, Pve

`diagrams.onprem.queue`: ActiveMQ, Activemq, Celery, EMQX, Emqx, Kafka, Nats, RabbitMQ, Rabbitmq, ZeroMQ, Zeromq

`diagrams.onprem.registry`: Harbor, Jfrog

`diagrams.onprem.search`: Solr

`diagrams.onprem.security`: Bitwarden, Trivy, Vault

`diagrams.onprem.storage`: CEPH, CEPH_OSD, Ceph, CephOsd, Glusterfs, Portworx

`diagrams.onprem.tracing`: Jaeger, Tempo

`diagrams.onprem.vcs`: Git, Gitea, Github, Gitlab, Svn

`diagrams.onprem.workflow`: Airflow, Digdag, KubeFlow, Kubeflow, NiFi, Nifi

## openstack

`diagrams.openstack.apiproxies`: EC2API

`diagrams.openstack.applicationlifecycle`: Freezer, Masakari, Murano, Solum

`diagrams.openstack.baremetal`: Cyborg, Ironic

`diagrams.openstack.billing`: CloudKitty, Cloudkitty

`diagrams.openstack.compute`: Nova, Qinling, Zun

`diagrams.openstack.containerservices`: Kuryr

`diagrams.openstack.deployment`: Ansible, Charms, Chef, Helm, Kolla, KollaAnsible, TripleO, Tripleo

`diagrams.openstack.frontend`: Horizon

`diagrams.openstack.monitoring`: Monasca, Telemetry

`diagrams.openstack.multiregion`: Tricircle

`diagrams.openstack.networking`: Designate, Neutron, Octavia

`diagrams.openstack.nfv`: Tacker

`diagrams.openstack.optimization`: Congress, Rally, Vitrage, Watcher

`diagrams.openstack.orchestration`: Blazar, Heat, Mistral, Senlin, Zaqar

`diagrams.openstack.packaging`: LOCI, Puppet, RPM

`diagrams.openstack.sharedservices`: Barbican, Glance, Karbor, Keystone, Searchlight

`diagrams.openstack.storage`: Cinder, Manila, Swift

`diagrams.openstack.user`: OpenStackClient, Openstackclient

`diagrams.openstack.workloadprovisioning`: Magnum, Sahara, Trove

## outscale

`diagrams.outscale.compute`: Compute, DirectConnect

`diagrams.outscale.network`: ClientVpn, InternetService, LoadBalancer, NatService, Net, SiteToSiteVpng

`diagrams.outscale.security`: Firewall, IdentityAndAccessManagement

`diagrams.outscale.storage`: SimpleStorageService, Storage

## programming

`diagrams.programming.flowchart`: Action, Collate, Database, Decision, Delay, Display, Document, InputOutput, Inspection, InternalStorage, LoopLimit, ManualInput, ManualLoop, Merge, MultipleDocuments, OffPageConnectorLeft, OffPageConnectorRight, Or, PredefinedProcess, Preparation, Sort, StartEnd, StoredData, SummingJunction

`diagrams.programming.framework`: Angular, Backbone, Camel, Django, DotNet, Dotnet, Ember, FastAPI, Fastapi, Flask, Flutter, GraphQL, Graphql, Hibernate, Jhipster, Laravel, Micronaut, NextJs, Nextjs, Phoenix, Quarkus, Rails, React, Spring, Sqlpage, Starlette, Svelte, Vercel, Vue

`diagrams.programming.language`: Bash, C, Cpp, Csharp, Dart, Elixir, Erlang, Go, Java, JavaScript, Javascript, Kotlin, Latex, Matlab, NodeJS, Nodejs, PHP, Php, Python, R, Ruby, Rust, Scala, Sql, Swift, TypeScript, Typescript

`diagrams.programming.runtime`: Dapr

## saas

`diagrams.saas.alerting`: Newrelic, Opsgenie, Pagerduty, Pushover, Xmatters

`diagrams.saas.analytics`: Dataform, Snowflake, Stitch

`diagrams.saas.automation`: N8N

`diagrams.saas.cdn`: Akamai, Cloudflare, Fastly

`diagrams.saas.chat`: Discord, Line, Mattermost, Messenger, RocketChat, Slack, Teams, Telegram

`diagrams.saas.communication`: Twilio

`diagrams.saas.crm`: Intercom, Zendesk

`diagrams.saas.filesharing`: Nextcloud

`diagrams.saas.identity`: Auth0, Okta

`diagrams.saas.logging`: DataDog, Datadog, NewRelic, Newrelic, Papertrail

`diagrams.saas.media`: Cloudinary

`diagrams.saas.recommendation`: Recombee

`diagrams.saas.security`: Crowdstrike, Sonarqube

`diagrams.saas.social`: Facebook, Twitter
