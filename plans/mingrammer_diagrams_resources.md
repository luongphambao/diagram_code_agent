# Mingrammer Diagrams Resources

Tổng hợp tài liệu, blog, repo và issue hữu ích để học và áp dụng [`mingrammer/diagrams`](https://github.com/mingrammer/diagrams) cho architecture diagram gần production.

---

## 1. Official Docs

| Link | Nội dung chính | Ghi chú |
|---|---|---|
| [mingrammer/diagrams GitHub](https://github.com/mingrammer/diagrams) | Repository chính thức | Source code, examples, provider icons |
| [Diagrams Official Website](https://diagrams.mingrammer.com/) | Trang tài liệu chính | Entry point tốt nhất để học thư viện |
| [Installation Guide](https://diagrams.mingrammer.com/docs/getting-started/installation) | Cài đặt Diagrams và Graphviz | Cần Graphviz để render diagram |
| [Getting Started Examples](https://diagrams.mingrammer.com/docs/getting-started/examples) | Ví dụ architecture diagram | Có AWS, GCP, Kubernetes, on-prem |
| [Diagram Guide](https://diagrams.mingrammer.com/docs/guides/diagram) | `Diagram`, `graph_attr`, `node_attr`, `edge_attr`, output format | Quan trọng nếu muốn custom layout |
| [Node Guide](https://diagrams.mingrammer.com/docs/guides/node) | Cách dùng node, direction, rendering order | Nên đọc khi diagram bị sai thứ tự node |
| [Edge Guide](https://diagrams.mingrammer.com/docs/guides/edge) | `Edge(label=...)`, style, color, Graphviz edge attributes | Quan trọng để làm data flow rõ ràng |
| [Graphviz Graph Attributes](https://graphviz.org/docs/graph/) | Graphviz attributes cho graph layout | Diagrams dùng Graphviz phía dưới |

---

## 2. Blog / Tutorial Hay

| Link | Nội dung chính | Vì sao nên đọc |
|---|---|---|
| [Creating AWS architecture diagrams with Python and Cursor](https://blog.diatomlabs.com/creating-aws-architecture-diagrams-with-python-and-cursor-a-step-by-step-guide-c88a0aa16298) | Tạo AWS architecture diagram với Python và Cursor | Có tư duy iterate diagram bằng AI assistant |
| [Automate Architecture with Python’s Diagrams Library](https://dev.to/epam_india_python/code-your-diagrams-automate-architecture-with-pythons-diagrams-library-4o5o) | Diagram as code với Python Diagrams | Phù hợp cho team muốn giữ docs update theo code |
| [Spend less time on management of architecture diagrams](https://medium.com/zeals-tech-blog/spend-less-time-on-management-of-architecture-diagrams-with-diagrams-d5fc2f7cbaf9) | Quản lý architecture diagram bằng code | Hay ở góc version-control diagram |
| [Software Architecture Illustration](https://ewinnington.github.io/posts/Software-Architecture-Illustration) | Tổng quan nhiều cách minh họa architecture | Giúp so sánh Diagrams với cách vẽ khác |
| [Diagram as Code using Diagrams](https://medium.com/%40vijaypatil44u/diagram-as-code-using-diagrams-f30647df4940) | Tutorial cơ bản | Dễ đọc cho người mới bắt đầu |
| [Exploring the Best Diagram as Code Tools](https://medium.com/%40alexandre_43174/exploring-the-best-diagram-as-code-tools-for-software-architecture-66a63b850075) | So sánh Diagram-as-Code tools | Có Mermaid, D2, PlantUML, Structurizr, Diagrams |
| [Code your Design Diagrams with Python](https://abhik-chakraborty92.medium.com/code-your-design-diagrams-with-python-e6125a2539bf) | Diagrams crash course | Có phần beautify bằng `graph_attr`, `node_attr`, `edge_attr` |
| [Diagrams as Code: The Complete How-to-Use Guide](https://dzone.com/articles/diagrams-as-code-the-complete-how-to-use-guide) | Hướng dẫn tổng quan | Có nhắc custom Graphviz attributes |
| [Diagrams as Code with Python – Part 2](https://akshay-g-bhadange.medium.com/diagrams-as-code-with-python-part-2-getting-started-with-diagram-and-cluster-8ba8a5c8dc9b) | Diagram, Cluster, styling | Hữu ích khi học global styling |
| [DevOps Diagram as Code](https://blog.stephane-robert.info/post/devops-diagram-as-code/) | DevOps diagram-as-code | Có output format, render options, styling |

---

## 3. Repo / Plugin Đáng Tham Khảo

| Repo | Nội dung chính | Ghi chú |
|---|---|---|
| [r3ap3rpy/diagramming](https://github.com/r3ap3rpy/diagramming) | Tutorial/video series | Có core concepts: Diagram, Node, Cluster, data flow |
| [dheeraj3choudhary/AWS-Diagram-As-Code](https://github.com/dheeraj3choudhary/AWS-Diagram-As-Code/blob/main/nodes.py) | AWS diagram sample | Import nhiều AWS nodes |
| [eavanvalkenburg/azure-diagrams](https://github.com/eavanvalkenburg/azure-diagrams/blob/master/diagram.py) | Azure architecture diagram | Có custom layout bằng Graphviz attributes |
| [bruce-mig/diagram-as-code](https://github.com/bruce-mig/diagram-as-code) | Diagram-as-code sample | Repo demo cách viết Python script generate diagram |
| [tzulberti/sphinx-diagrams](https://github.com/tzulberti/sphinx-diagrams) | Sphinx integration | Dùng Diagrams trong documentation pipeline |
| [cloudposse/example-app-on-lambda-with-gha](https://github.com/cloudposse/example-app-on-lambda-with-gha/blob/main/diagramming.py) | Real-ish app architecture | Đáng xem vì Cloud Posse thường viết repo theo hướng production hơn |
| [mujahidk/python-diagrams](https://github.com/mujahidk/python-diagrams) | Dockerized sample | Có sample ELB → EC2 → RDS |
| [Deepak17460/Aws-Diagrams](https://github.com/Deepak17460/Aws-Diagrams) | AWS serverless sample | Lambda, S3, DynamoDB |
| [andrewmoshu/diagram-mcp-server](https://github.com/andrewmoshu/diagram-mcp-server) | MCP server for diagrams | Hướng AI/agent generate architecture diagram |
| [shawnho1018/gcp-diagram-mcp-server](https://github.com/shawnho1018/gcp-diagram-mcp-server) | GCP diagram MCP server | Generate GCP diagram code từ input/IaC |
| [leninkhaidem/architecture-diagrams Skill](https://github.com/leninkhaidem/architecture-diagrams/blob/main/architecture-diagrams/SKILL.md) | Architecture diagram skill | Gần với hướng tạo skill cho AI assistant |

---

## 4. GitHub Discussion / Issues Nên Đọc

Các issue này rất hữu ích khi muốn diagram nhìn chuyên nghiệp hơn, vì chúng chạm đúng vấn đề thực tế của Graphviz layout.

| Link | Chủ đề | Nên học gì |
|---|---|---|
| [Discussion #1169 - Diagrams MCP](https://github.com/mingrammer/diagrams/discussions/1169) | MCP cho Diagrams | Hướng dùng AI/agent để generate diagram |
| [Issue #17 - Arrows to/from clusters](https://github.com/mingrammer/diagrams/issues/17) | Connect edge vào cluster | Dùng `lhead`, `ltail`, Graphviz attrs |
| [Issue #65 - Control size/position of nodes and clusters](https://github.com/mingrammer/diagrams/issues/65) | Control node/cluster position | Hiểu limitation khi muốn layout thủ công như draw.io |
| [Issue #196 - Custom node label spacing](https://github.com/mingrammer/diagrams/issues/196) | Label spacing/custom node | Hữu ích khi dùng custom icon/logo |
| [Issue #202 - graph_attr doesn’t take effect](https://github.com/mingrammer/diagrams/issues/202) | Graph attributes không như kỳ vọng | Hay gặp khi diagram nhiều node bị dàn thành một line |
| [Issue #579 - Alignment inconsistent](https://github.com/mingrammer/diagrams/issues/579) | Alignment và label bị lệch | Hiểu giới hạn Graphviz layout |
| [Issue #601 - Change fontsize of all labels](https://github.com/mingrammer/diagrams/issues/601) | Font size toàn diagram | Global font size không phải lúc nào đủ |
| [Issue #699 - Edge position/routing](https://github.com/mingrammer/diagrams/issues/699) | Edge routing | Cách xử lý arrow đi sai hướng hoặc label bị lệch |
| [Issue #701 - graph_attr/node_attr/edge_attr example](https://github.com/mingrammer/diagrams/issues/701) | Ví dụ custom attributes | Cách áp dụng bộ attr trong design process |
| [Issue #891 - Node ordering nightmare](https://github.com/mingrammer/diagrams/issues/891) | Node ordering trong cluster | Khi nhiều cluster làm layout không như mong muốn |
| [Issue #1013 - Multiple rows instead of single row](https://github.com/mingrammer/diagrams/issues/1013) | Chia node thành nhiều hàng | Khi diagram quá nhiều node bị kéo thành một hàng dài |

---

## 5. GitHub Search Queries

Dùng các query này để tìm thêm repo dùng `mingrammer/diagrams`:

```text
"from diagrams import Diagram"
```

```text
"from diagrams import Cluster, Diagram"
```

```text
"from diagrams.aws.compute import" "with Diagram"
```

```text
"from diagrams.azure" "with Diagram"
```

```text
"from diagrams.gcp" "with Diagram"
```

```text
"from diagrams.k8s" "Ingress" "Service" "Pod"
```

```text
"from diagrams import Diagram" "graph_attr" "edge_attr" "node_attr"
```

```text
"from diagrams import Cluster" "show=False" "outformat"
```

```text
"mingrammer/diagrams" "MCP"
```

```text
"diagrams.custom import Custom" "architecture"
```

---

## 6. Production Diagram Checklist

Nếu muốn diagram gần production, không nên chỉ dùng default layout. Nên custom ít nhất:

```python
graph_attr = {
    "fontsize": "20",
    "bgcolor": "white",
    "pad": "0.4",
    "splines": "ortho",
    "nodesep": "0.8",
    "ranksep": "1.0",
}

node_attr = {
    "fontsize": "12",
}

edge_attr = {
    "fontsize": "10",
}
```

### Ý nghĩa các attribute quan trọng

| Attribute | Dùng để làm gì |
|---|---|
| `splines="ortho"` | Edge đi dạng vuông góc, nhìn giống enterprise architecture hơn |
| `nodesep` | Khoảng cách ngang giữa các node |
| `ranksep` | Khoảng cách dọc giữa các layer/rank |
| `pad` | Padding toàn canvas |
| `fontsize` | Font size tổng thể |
| `bgcolor` | Nền diagram |
| `rankdir` / `direction` | Hướng flow: LR, TB, RL, BT |

---

## 7. Internal Skill Gợi Ý Cho Team

```markdown
# Architecture Diagram Skill with Python Diagrams

## Goal
Generate production-like architecture diagrams using mingrammer/diagrams and Graphviz.

## Rules
1. Always use clusters for logical boundaries:
   - Client / External Systems
   - API Layer
   - Application Services
   - Data Layer
   - Observability
   - External Providers

2. Always set layout attributes:
   - graph_attr: splines, nodesep, ranksep, pad, fontsize, bgcolor
   - node_attr: fontsize
   - edge_attr: fontsize

3. Prefer left-to-right flow for request pipelines:
   - direction="LR"

4. Prefer top-to-bottom flow for layered architecture:
   - direction="TB"

5. Avoid too many nodes in one canvas.
   If there are more than 20–25 nodes, split into:
   - Context diagram
   - Container diagram
   - Data flow diagram
   - Deployment diagram

6. Use clear edge labels:
   - HTTP
   - gRPC
   - Kafka event
   - SQL query
   - Vector search
   - Metrics/logs/traces

7. Do not connect everything to everything.
   Show only important runtime/data/control flows.

8. Use Custom icons only when official icons do not exist.

9. Export SVG for documentation and PNG for quick review.

10. After rendering, review:
   - Is the main flow obvious in 5 seconds?
   - Are clusters meaningful?
   - Are arrows crossing too much?
   - Are labels readable?
   - Is there too much detail?
```

---

## 8. Template Code Base

```python
from diagrams import Diagram, Cluster, Edge
from diagrams.aws.compute import ECS
from diagrams.aws.database import RDS
from diagrams.aws.network import ALB
from diagrams.aws.integration import SQS
from diagrams.onprem.client import Users
from diagrams.onprem.monitoring import Prometheus, Grafana

graph_attr = {
    "fontsize": "20",
    "bgcolor": "white",
    "pad": "0.4",
    "splines": "ortho",
    "nodesep": "0.8",
    "ranksep": "1.0",
}

node_attr = {
    "fontsize": "12",
}

edge_attr = {
    "fontsize": "10",
}

with Diagram(
    "Production Architecture",
    filename="production_architecture",
    show=False,
    direction="LR",
    graph_attr=graph_attr,
    node_attr=node_attr,
    edge_attr=edge_attr,
    outformat="svg",
):
    users = Users("Users")

    with Cluster("API Layer"):
        alb = ALB("Application Load Balancer")

    with Cluster("Application Services"):
        app = ECS("Backend Service")
        worker = ECS("Worker Service")

    with Cluster("Async Processing"):
        queue = SQS("Task Queue")

    with Cluster("Data Layer"):
        db = RDS("PostgreSQL")

    with Cluster("Observability"):
        metrics = Prometheus("Metrics")
        dashboard = Grafana("Dashboard")

    users >> Edge(label="HTTPS") >> alb
    alb >> Edge(label="REST API") >> app
    app >> Edge(label="enqueue job") >> queue
    queue >> Edge(label="consume") >> worker
    app >> Edge(label="SQL") >> db
    worker >> Edge(label="SQL") >> db

    app >> Edge(label="metrics", style="dashed") >> metrics
    worker >> Edge(label="metrics", style="dashed") >> metrics
    metrics >> dashboard
```

---

## 9. Gợi Ý Sử Dụng Thực Tế

`mingrammer/diagrams` mạnh nhất cho:

- Container architecture diagram
- Deployment diagram
- Cloud architecture diagram
- Runtime/data flow diagram
- Infrastructure documentation trong repo

Nên tách diagram theo nhiều mức thay vì nhồi tất cả vào một canvas:

1. **Context diagram**: user, system, external systems
2. **Container diagram**: frontend, backend, database, queue, storage
3. **Runtime/data flow diagram**: request/data/event đi như thế nào
4. **Deployment diagram**: cloud account, VPC, subnet, cluster, instance, service
5. **Observability/security diagram**: logs, metrics, tracing, IAM, secrets

Nếu muốn C4-style documentation mạnh hơn, có thể kết hợp thêm:

- Structurizr
- Mermaid
- PlantUML
- D2

