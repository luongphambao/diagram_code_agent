# `diagrams` patterns (copy these idioms)

The AWS/GCP/k8s blocks are verbatim from the mingrammer/diagrams gallery; the
Azure/OCI/IBM blocks apply the SAME idioms with that provider's real imports.
The idioms are **provider-agnostic** — for ANY cloud (Azure, GCP, OCI, IBM,
Alibaba…) reuse these exact techniques, just swap the imports (look them up in
`reference/cloud_services.md` and `reference/nodes.md`). NEVER mix AWS icons into
a non-AWS diagram — use the matching provider's nodes throughout.

Recurring techniques: nodes stored in variables, **list fan-out/fan-in**,
**nested clusters**, HA pairs joined with `-`, and edges colored/labeled by concern.

## Grouped Workers (list fan-out/fan-in; TB)
```python
from diagrams import Diagram
from diagrams.aws.compute import EC2
from diagrams.aws.database import RDS
from diagrams.aws.network import ELB

with Diagram("Grouped Workers", show=False, direction="TB"):
    ELB("lb") >> [EC2("worker1"),
                  EC2("worker2"),
                  EC2("worker3"),
                  EC2("worker4"),
                  EC2("worker5")] >> RDS("events")
```

## Clustered Web Services (clusters + HA replicas via `-`)
```python
from diagrams import Cluster, Diagram
from diagrams.aws.compute import ECS
from diagrams.aws.database import ElastiCache, RDS
from diagrams.aws.network import ELB, Route53

with Diagram("Clustered Web Services", show=False):
    dns = Route53("dns")
    lb = ELB("lb")

    with Cluster("Services"):
        svc_group = [ECS("web1"), ECS("web2"), ECS("web3")]

    with Cluster("DB Cluster"):
        db_primary = RDS("userdb")
        db_primary - [RDS("userdb ro")]

    memcached = ElastiCache("memcached")

    dns >> lb >> svc_group
    svc_group >> db_primary
    svc_group >> memcached
```

## Event Processing (nested clusters)
```python
from diagrams import Cluster, Diagram
from diagrams.aws.compute import ECS, EKS, Lambda
from diagrams.aws.database import Redshift
from diagrams.aws.integration import SQS
from diagrams.aws.storage import S3

with Diagram("Event Processing", show=False):
    source = EKS("k8s source")

    with Cluster("Event Flows"):
        with Cluster("Event Workers"):
            workers = [ECS("worker1"), ECS("worker2"), ECS("worker3")]
        queue = SQS("event queue")
        with Cluster("Processing"):
            handlers = [Lambda("proc1"), Lambda("proc2"), Lambda("proc3")]

    store = S3("events store")
    dw = Redshift("analytics")

    source >> workers >> queue >> handlers
    handlers >> store
    handlers >> dw
```

## Message Collecting (deeply nested clusters; GCP)
```python
from diagrams import Cluster, Diagram
from diagrams.gcp.analytics import BigQuery, Dataflow, PubSub
from diagrams.gcp.compute import AppEngine, Functions
from diagrams.gcp.database import BigTable
from diagrams.gcp.iot import IotCore
from diagrams.gcp.storage import GCS

with Diagram("Message Collecting", show=False):
    pubsub = PubSub("pubsub")
    with Cluster("Source of Data"):
        [IotCore("core1"), IotCore("core2"), IotCore("core3")] >> pubsub
    with Cluster("Targets"):
        with Cluster("Data Flow"):
            flow = Dataflow("data flow")
        with Cluster("Data Lake"):
            flow >> [BigQuery("bq"), GCS("storage")]
        with Cluster("Event Driven"):
            with Cluster("Processing"):
                flow >> AppEngine("engine") >> BigTable("bigtable")
            with Cluster("Serverless"):
                flow >> Functions("func") >> AppEngine("appengine")
    pubsub >> flow
```

## Azure — Clustered Web Service (clusters + HA replica + fan-out)
```python
from diagrams import Cluster, Diagram
from diagrams.azure.compute import AppServices
from diagrams.azure.database import SQLDatabases, CacheForRedis
from diagrams.azure.network import ApplicationGateway, FrontDoors

with Diagram("Azure Clustered Web Service", show=False):
    edge = FrontDoors("front door")
    gw = ApplicationGateway("app gateway")

    with Cluster("App Services"):
        svc_group = [AppServices("web1"), AppServices("web2"), AppServices("web3")]

    with Cluster("Data"):
        db_primary = SQLDatabases("sql primary")
        db_primary - [SQLDatabases("sql replica")]

    cache = CacheForRedis("redis")

    edge >> gw >> svc_group
    svc_group >> db_primary
    svc_group >> cache
```

## Azure — Event Processing (Functions + Service Bus + Event Hubs)
```python
from diagrams import Cluster, Diagram
from diagrams.azure.compute import FunctionApps
from diagrams.azure.integration import ServiceBus
from diagrams.azure.analytics import EventHubs, SynapseAnalytics
from diagrams.azure.storage import BlobStorage

with Diagram("Azure Event Processing", show=False):
    ingest = EventHubs("event hubs")
    queue = ServiceBus("service bus")

    with Cluster("Processing"):
        handlers = [FunctionApps("fn1"), FunctionApps("fn2"), FunctionApps("fn3")]

    store = BlobStorage("blob store")
    dw = SynapseAnalytics("synapse")

    ingest >> queue >> handlers
    handlers >> store
    handlers >> dw
```

## GCP — Clustered Web Service (Cloud Run + LB + Cloud SQL)
```python
from diagrams import Cluster, Diagram
from diagrams.gcp.compute import Run
from diagrams.gcp.database import SQL, Memorystore
from diagrams.gcp.network import LoadBalancing, DNS

with Diagram("GCP Clustered Web Service", show=False):
    dns = DNS("dns")
    lb = LoadBalancing("global lb")

    with Cluster("Services"):
        svc_group = [Run("svc1"), Run("svc2"), Run("svc3")]

    with Cluster("Data"):
        db_primary = SQL("cloud sql")
        db_primary - [SQL("read replica")]

    cache = Memorystore("memorystore")

    dns >> lb >> svc_group
    svc_group >> db_primary
    svc_group >> cache
```

## OCI — Web Service (nested clusters inside a VCN)
```python
from diagrams import Cluster, Diagram
from diagrams.oci.compute import VirtualMachine
from diagrams.oci.database import Autonomous
from diagrams.oci.network import LoadBalancer

with Diagram("OCI Web Service", show=False):
    with Cluster("VCN"):
        lb = LoadBalancer("load balancer")
        with Cluster("Compute"):
            workers = [VirtualMachine("vm1"), VirtualMachine("vm2"), VirtualMachine("vm3")]
    db = Autonomous("autonomous db")

    lb >> workers >> db
```

## IBM Cloud — Web Service (entry actor + fan-out)
```python
from diagrams import Cluster, Diagram
from diagrams.ibm.compute import Instance
from diagrams.ibm.network import LoadBalancer
from diagrams.ibm.storage import ObjectStorage
from diagrams.ibm.user import User

with Diagram("IBM Cloud Web Service", show=False):
    user = User("user")
    lb = LoadBalancer("load balancer")

    with Cluster("Compute"):
        workers = [Instance("app1"), Instance("app2")]

    store = ObjectStorage("object storage")

    user >> lb >> workers >> store
```

## Exposed Pod (chaining + fan-out + reverse `<<`; k8s)
```python
from diagrams import Diagram
from diagrams.k8s.clusterconfig import HPA
from diagrams.k8s.compute import Deployment, Pod, ReplicaSet
from diagrams.k8s.network import Ingress, Service

with Diagram("Exposed Pod with 3 Replicas", show=False):
    net = Ingress("domain.com") >> Service("svc")
    net >> [Pod("pod1"), Pod("pod2"), Pod("pod3")] << ReplicaSet("rs") << Deployment("dp") << HPA("hpa")
```

## Stateful Architecture (loops to build repeated structure; k8s)
```python
from diagrams import Cluster, Diagram
from diagrams.k8s.compute import Pod, StatefulSet
from diagrams.k8s.network import Service
from diagrams.k8s.storage import PV, PVC, StorageClass

with Diagram("Stateful Architecture", show=False):
    with Cluster("Apps"):
        svc = Service("svc")
        sts = StatefulSet("sts")
        apps = []
        for _ in range(3):
            pod = Pod("pod")
            pvc = PVC("pvc")
            pod - sts - pvc
            apps.append(svc >> pod >> pvc)
    apps << PV("pv") << StorageClass("sc")
```

## Advanced Web Service, colored (Edge color/style/label per concern)
```python
from diagrams import Cluster, Diagram, Edge
from diagrams.onprem.analytics import Spark
from diagrams.onprem.compute import Server
from diagrams.onprem.database import PostgreSQL
from diagrams.onprem.inmemory import Redis
from diagrams.onprem.aggregator import Fluentd
from diagrams.onprem.monitoring import Grafana, Prometheus
from diagrams.onprem.network import Nginx
from diagrams.onprem.queue import Kafka

with Diagram(name="Advanced Web Service with On-Premises (colored)", show=False):
    ingress = Nginx("ingress")
    metrics = Prometheus("metric")
    metrics << Edge(color="firebrick", style="dashed") << Grafana("monitoring")

    with Cluster("Service Cluster"):
        grpcsvc = [Server("grpc1"), Server("grpc2"), Server("grpc3")]

    with Cluster("Sessions HA"):
        primary = Redis("session")
        primary - Edge(color="brown", style="dashed") - Redis("replica") << Edge(label="collect") << metrics
        grpcsvc >> Edge(color="brown") >> primary

    with Cluster("Database HA"):
        primary = PostgreSQL("users")
        primary - Edge(color="brown", style="dotted") - PostgreSQL("replica") << Edge(label="collect") << metrics
        grpcsvc >> Edge(color="black") >> primary

    aggregator = Fluentd("logging")
    aggregator >> Edge(label="parse") >> Kafka("stream") >> Edge(color="black", style="bold") >> Spark("analytics")

    ingress >> Edge(color="darkgreen") << grpcsvc >> Edge(color="darkorange") >> aggregator
```

## Custom node (logo not built in)
```python
from urllib.request import urlretrieve
from diagrams import Cluster, Diagram
from diagrams.aws.database import Aurora
from diagrams.custom import Custom
from diagrams.k8s.compute import Pod

rabbitmq_url = "https://jpadilla.github.io/rabbitmqapp/assets/img/icon.png"
rabbitmq_icon = "rabbitmq.png"
urlretrieve(rabbitmq_url, rabbitmq_icon)

with Diagram("Broker Consumers", show=False):
    with Cluster("Consumers"):
        consumers = [Pod("worker"), Pod("worker"), Pod("worker")]
    queue = Custom("Message queue", rabbitmq_icon)
    queue >> consumers >> Aurora("Database")
```
