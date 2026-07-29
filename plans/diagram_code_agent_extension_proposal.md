# Đề xuất mở rộng Diagram Code Agent

Repo: https://github.com/luongphambao/diagram_code_agent

## 1. Đánh giá nhanh repo hiện tại

Sau khi xem cấu trúc repo, có thể thấy **Diagram Code Agent đã có nền tảng khá mạnh**, không chỉ là High-Level Architecture Diagram.

Các khả năng hiện có:

- Nhận requirement dạng text hoặc tài liệu.
- Đề xuất tech stack và blueprint có bước user approve/reject.
- Sinh PNG, DOT và file `.drawio` có thể chỉnh sửa.
- Có visual critic, static audit và native layout-repair engine.
- Đã hỗ trợ BPMN/swimlane.
- Đã có C4 ở mức `context` và `container`.
- Đã có một số topology preset như:
  - hierarchy
  - hub-spoke
  - mesh
  - hybrid
  - sequence dạng numbered walkthrough
- Đã có module `codevis`, nhưng hiện chủ yếu phân tích:
  - Python import graph
  - Python class inheritance graph

Vì vậy, không nên ưu tiên thêm hàng loạt diagram đơn giản như generic flowchart, basic component diagram hoặc use case diagram trước. Những loại đó engine hiện tại đã có thể biểu diễn tương đối tốt.

Giá trị cao nhất sẽ đến từ các diagram có **ngữ nghĩa riêng**, cần schema, validation và renderer chuyên biệt.

---

# 2. Những diagram nên làm thêm

## Thứ tự ưu tiên đề xuất

| Ưu tiên | Diagram | Giá trị | Mức phù hợp với repo | Cách triển khai |
|---|---|---:|---:|---|
| P0 | True UML Sequence Diagram | Rất cao | Cao | Native renderer mới |
| P0 | ERD / Database Schema Diagram | Rất cao | Cao | Native renderer mới |
| P0 | State Machine Diagram | Rất cao | Rất cao | Mở rộng native graph |
| P1 | Deployment Diagram từ IaC | Cao | Rất cao | Preset + parser, tái sử dụng architecture renderer |
| P1 | Code Component / Dependency Map | Cao | Cao | Mở rộng `codevis` |
| P2 | Data Lineage Diagram | Trung bình–cao | Trung bình | Parser SQL/dbt/Airflow |
| P2 | Security Threat / Trust Boundary Diagram | Trung bình–cao | Cao | Preset architecture + STRIDE metadata |

## Ba loại nên làm MVP trước

1. **True Sequence Diagram**
2. **ERD**
3. **State Machine Diagram**

Ba loại này bổ sung trực tiếp những thứ mà architecture diagram không giải quyết tốt:

- Runtime interaction
- Data structure
- Entity lifecycle

---

# 3. True UML Sequence Diagram

## Tại sao đây là ưu tiên số một?

Repo hiện có `layout_intent="sequence"`, nhưng thực chất là **numbered request walkthrough trên architecture diagram**, chưa phải UML Sequence Diagram đúng nghĩa.

Một UML Sequence Diagram đầy đủ cần có:

- Lifeline
- Activation bar
- Synchronous message
- Asynchronous message
- Return message
- `alt`
- `opt`
- `loop`
- `par`
- Note
- Actor
- External system
- Create participant
- Destroy participant

Registry hiện tại mô tả sequence theo hướng numbered request walkthrough. Prettygraph hiện cũng chưa phải công cụ phù hợp cho true lifeline diagram.

## Use case có giá trị cao

Ví dụ requirement:

> Vẽ flow user login bằng magic link, frontend gọi backend, backend gọi Supabase, callback trả lại session và frontend redirect dashboard.

Luồng logic:

```text
User       Frontend       Backend       Supabase
 |             |              |              |
 | Login       |              |              |
 |------------>|              |              |
 |             | POST /login  |              |
 |             |------------->|              |
 |             |              | Create link  |
 |             |              |------------->|
 |             |              |<-------------|
 |             |<-------------|              |
```

Output thực tế nên là UML lifeline đúng chuẩn, không phải các box nối ngang.

## Schema đề xuất

```python
class SequenceParticipant:
    id: str
    label: str
    kind: actor | frontend | service | database | external

class SequenceMessage:
    order: int
    from_: str
    to: str
    label: str
    kind: sync | async | return | create | destroy

class SequenceFragment:
    kind: alt | opt | loop | par | critical
    condition: str
    start_order: int
    end_order: int

class SequenceActivation:
    participant: str
    start_order: int
    end_order: int
```

## Renderer nên thiết kế thế nào?

Không nên ép Sequence Diagram đi qua `g.box()` và `g.link()`.

Nên tạo:

```text
backend/src/prettygraph/native/sequence.py
```

Renderer thực hiện:

1. Đặt participant theo chiều ngang.
2. Tạo lifeline dọc cố định.
3. Tính tọa độ `y` của từng message theo `order`.
4. Vẽ activation bar trên lifeline.
5. Vẽ return message dạng dashed.
6. Vẽ frame cho `alt`, `opt`, `loop`, `par`.
7. Xuất trực tiếp shape `umlLifeline` vào draw.io.
8. Sinh PNG từ cùng một canonical layout.

Exporter chung hiện biến node thành `shape=label`, vì vậy không phù hợp để tạo lifeline hoặc fragment UML đúng chuẩn.

## Validation nên có

- Message trỏ đến participant không tồn tại.
- Trùng `order`.
- Fragment không chứa message nào.
- Fragment chồng lên nhau sai cấu trúc.
- Activation kết thúc trước khi bắt đầu.
- Return message không có request tương ứng.
- Participant không tham gia message nào.
- Quá nhiều participant làm diagram quá rộng.

## API Flow Diagram không cần renderer riêng

Sau khi có sequence engine, API Flow Diagram chỉ cần là một preset:

```text
OpenAPI / source code
        ↓
Extract endpoints and calls
        ↓
SequenceSpec
        ↓
Sequence renderer
```

---

# 4. ERD / Database Schema Diagram

## Tại sao cần renderer riêng?

Hiện repo có thể dựng ERD bằng cách:

- Mỗi table là một `g.box(kind="data")`
- PK/FK đặt trong `sublabel`
- Quan hệ nối bằng `g.link()`

Cách này mới chỉ tạo ra “table-looking box”, chưa phải ERD chuyên nghiệp.

Một ERD tốt cần:

- Mỗi column là một row riêng.
- PK, FK, unique, nullable.
- Data type.
- Composite key.
- Index.
- Cardinality.
- Crow’s-foot notation.
- Junction table.
- Self-reference.
- Schema hoặc database boundary.

## Input nên hỗ trợ

- PostgreSQL DDL
- MySQL DDL
- Prisma schema
- SQLAlchemy model
- Django model
- TypeORM entity
- Supabase migration
- Requirement dạng text
- Database schema trong repo

Ví dụ:

```sql
CREATE TABLE session (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    status text NOT NULL
);

CREATE TABLE session_answer (
    id uuid PRIMARY KEY,
    session_id uuid REFERENCES session(id),
    answer_text text
);
```

Agent cần tự nhận ra:

```text
session 1 ─── N session_answer
```

## Schema đề xuất

```python
class ERDColumn:
    name: str
    data_type: str
    primary_key: bool
    foreign_key: bool
    nullable: bool
    unique: bool
    default: str
    references: str

class ERDEntity:
    id: str
    name: str
    schema: str
    columns: list[ERDColumn]
    indexes: list[str]

class ERDRelationship:
    from_entity: str
    from_columns: list[str]
    to_entity: str
    to_columns: list[str]
    cardinality: one_to_one | one_to_many | many_to_many
    on_delete: str
```

## Renderer nên thiết kế thế nào?

Nên tạo:

```text
backend/src/prettygraph/native/erd.py
backend/src/codevis/sql_schema.py
backend/src/codevis/orm_schema.py
```

## Lớp phân tích

```text
SQL / ORM models
      ↓
Parser
      ↓
ERDSpec
```

## Lớp render

- Table header.
- Column rows.
- PK/FK badge.
- Ports gắn với đúng row FK.
- Crow’s-foot connector.
- Group theo PostgreSQL schema.
- Layout table dựa trên dependency graph.
- Junction table đặt giữa hai bảng chính.
- Reference tables đẩy ra khu vực ngoài.

## Layout strategy

Không nên chỉ dùng Graphviz auto-layout mặc định.

Nên:

1. Tạo dependency graph từ FK.
2. Tìm root tables.
3. Xếp bảng theo layer.
4. Đưa lookup/master tables sang một cột.
5. Đưa transaction tables vào trung tâm.
6. Đưa child/detail tables ở layer tiếp theo.
7. Tối ưu edge crossing bằng layout-repair engine.

## Validation nên có

- FK tham chiếu table không tồn tại.
- FK tham chiếu column không tồn tại.
- FK data type không tương thích.
- Many-to-many nhưng không có junction table.
- Table không có primary key.
- Duplicate index.
- Self-reference không có label.
- Orphan table.
- Circular dependency.

Có thể phân loại:

```text
Error      → schema sai
Warning    → thiết kế đáng chú ý
Info       → recommendation
```

Feature này rất hữu ích cho:

- BA
- Backend developer
- DBA
- Data engineer
- Người review database

---

# 5. State Machine Diagram

## Vì sao giá trị rất cao?

Nhiều feature software có logic dựa trên status:

- Lead status
- Session lifecycle
- Order status
- Payment status
- Document approval
- Background job
- Supplier acknowledgement
- Buyer enrichment
- Ticket workflow

Architecture diagram không thể trả lời tốt:

> Từ status nào được chuyển sang status nào, do actor nào, khi điều kiện nào xảy ra?

State Machine Diagram giải quyết chính xác vấn đề này.

## Schema đề xuất

```python
class StateNode:
    id: str
    label: str
    kind: initial | normal | final | choice | fork | history
    group: str

class StateTransition:
    from_: str
    to: str
    event: str
    guard: str
    action: str
    actor: str
```

Label transition theo chuẩn:

```text
event [guard] / action
```

Ví dụ:

```text
SUPPLIER_ACCEPTED
   |
   | confirm_demo [permission: demo.confirm]
   v
DEMO_CONFIRMED
```

## Renderer

Có thể tạo:

```text
backend/src/prettygraph/native/state_machine.py
```

State Machine có thể tái sử dụng phần lớn native graph engine hiện tại.

Cần thêm các shape semantic:

- Initial state: filled circle
- Final state: bullseye
- Normal state: rounded rectangle
- Choice: diamond
- Fork/join: thick bar
- Composite state: nested container
- Transition: directional edge có event, guard, action

## Validation có giá trị đặc biệt

Agent không nên chỉ vẽ. Agent nên kiểm tra:

- State không thể reach từ initial state.
- State không thể đi đến final state.
- Terminal state vẫn có outgoing transition.
- Hai transition có cùng event và guard.
- Transition thiếu actor.
- Transition thiếu permission.
- Có vòng lặp không có exit.
- Status được đề cập trong requirement nhưng thiếu trong diagram.
- FE hiển thị action nhưng BE không cho phép transition đó.
- Không rõ transition dành cho admin, supplier hay system.

## Output bổ sung

State Machine có thể sinh transition table cho Dev và QA:

| Current state | Event | Guard | Actor | Next state |
|---|---|---|---|---|
| Pending | Enrich success | Data valid | System | Enriched |
| Enriched | Accept | Has permission | Supplier | Supplier Accepted |

Đây là output rất hữu ích cho:

- SRS
- Acceptance criteria
- Backend validation
- Frontend action visibility
- Test cases

---

# 6. Deployment Diagram từ Docker, Kubernetes và Terraform

## Không nên xây renderer hoàn toàn mới

Deployment Diagram về hình thức khá gần architecture diagram hiện tại.

Repo đã có:

- Cloud/VPC/subnet/AZ nesting.
- Technology icon.
- Hybrid topology.
- Network topology.
- Clusters và parent boundaries.
- Protocol-labeled edges.

Vì vậy, nên tạo **Deployment preset + source parsers**, thay vì làm renderer riêng hoàn toàn.

## Input

- `docker-compose.yml`
- Kubernetes YAML
- Helm-rendered manifests
- Terraform
- Vercel config
- AWS ECS task definitions
- GitHub Actions deployment workflow
- Bitbucket Pipelines
- GitLab CI

## Schema mở rộng

```python
class DeploymentNode:
    id: str
    kind: device | node | runtime | artifact | service | database
    environment: dev | staging | production
    image: str
    replicas: int
    ports: list[int]
    region: str
    zone: str

class DeploymentRelation:
    kind: deploys | hosts | communicates | mounts | exposes
```

Ví dụ:

```text
AWS Region
└── EKS Cluster
    ├── Namespace: frontend
    │   └── Deployment: web (x3)
    ├── Namespace: backend
    │   └── Deployment: api (x4)
    └── StatefulSet: worker
```

## Giá trị thực tế quan trọng nhất

Không chỉ vẽ deployment. Agent nên so sánh:

```text
Desired architecture
        vs
Current deployment files
```

Ví dụ finding:

```text
Architecture yêu cầu API x3
Kubernetes manifest hiện chỉ replicas: 1
```

Hoặc:

```text
Architecture yêu cầu private database
Terraform đang expose public_access = true
```

Đây là hướng mở rộng rất tự nhiên cho repo.

---

# 7. Code Component / Dependency Map

## Repo đã có gì?

`codevis` hiện có:

- Python module import graph.
- Transitive reduction để giảm hairball.
- Python class inheritance graph.
- Group class theo module.

Đây là nền tảng tốt nhưng còn hẹp.

## Nên mở rộng thành ba level

### Level 1 — Package map

```text
routers
   ↓
services
   ↓
repositories
   ↓
models
```

### Level 2 — Runtime component map

Agent nhận biết:

- API routes
- Controllers
- Services
- Repositories
- Event consumers
- Scheduled jobs
- Database models
- External clients

### Level 3 — Detailed dependency graph

- Import
- Function call
- Class inheritance
- Interface implementation
- Database access
- HTTP calls
- Queue publish/consume

## Ngôn ngữ ưu tiên

1. Python
2. TypeScript/JavaScript
3. Java
4. C#
5. Go

Không nên làm tất cả cùng lúc. Python và TypeScript nên được ưu tiên trước.

## Công nghệ parser

Đối với Python có thể tiếp tục dùng `ast`.

Đối với nhiều ngôn ngữ, nên thêm analyzer layer dựa trên Tree-sitter:

```text
Source files
    ↓
Language adapter
    ↓
Normalized CodeGraph
    ↓
Filter / transitive reduction
    ↓
PrettyGraph renderer
```

## Bộ lọc bắt buộc

Code dependency graph rất dễ trở thành hairball.

UI nên cho phép:

- Chỉ xem một package.
- Chỉ xem dependency trực tiếp.
- Ẩn test files.
- Ẩn generated files.
- Chọn depth.
- Group theo folder.
- Group theo architectural layer.
- Chỉ hiển thị circular dependencies.
- Chỉ hiển thị cross-layer violations.

Giá trị lớn nhất không phải là vẽ tất cả import, mà là phát hiện:

```text
Controller gọi trực tiếp database
Domain phụ thuộc infrastructure
Circular dependency
Unused module
Service có quá nhiều dependency
```

---

# 8. Kiến trúc tổng thể đề xuất

## Không tiếp tục nhồi mọi thứ vào `Blueprint`

Hiện `Blueprint` đang chứa:

- Architecture nodes
- Clusters
- Edges
- C4 level
- Process blueprint cho BPMN
- Layout intent
- Presentation metadata

Nếu tiếp tục thêm:

```text
sequence
erd
state_machine
deployment
code_map
```

vào cùng model, schema sẽ trở thành một “god object”.

## Target architecture

```text
DiagramRequest
      |
      v
Diagram Type Router
      |
      v
Type-specific Analyzer
      |
      v
DiagramSpec
      |
      v
HITL Plan Approval
      |
      v
Renderer Registry
      |
      +---- Architecture Renderer
      +---- BPMN Renderer
      +---- Sequence Renderer
      +---- ERD Renderer
      +---- State Renderer
      +---- Code Map Renderer
      |
      v
Structural Validator
      |
      v
Visual Critic
      |
      v
PNG + draw.io + JSON Spec
```

## Base schema

```python
class DiagramPlan:
    kind: Literal[
        "architecture",
        "bpmn",
        "sequence",
        "erd",
        "state_machine",
        "deployment",
        "code_map",
    ]

    title: str
    objective: str
    audience: str
    source_type: str
    presentation_style: str
    spec: DiagramSpec
```

`spec` nên là discriminated union:

```python
DiagramSpec = (
    ArchitectureSpec
    | ProcessSpec
    | SequenceSpec
    | ERDSpec
    | StateMachineSpec
    | DeploymentSpec
    | CodeMapSpec
)
```

## Renderer registry

```python
RENDERERS = {
    "architecture": ArchitectureRenderer(),
    "bpmn": BPMNRenderer(),
    "sequence": SequenceRenderer(),
    "erd": ERDRenderer(),
    "state_machine": StateMachineRenderer(),
    "deployment": ArchitectureRenderer(preset="deployment"),
    "code_map": PrettyGraphRenderer(preset="code"),
}
```

## Quyết định quan trọng

- **Sequence:** native renderer riêng.
- **ERD:** native renderer riêng.
- **State Machine:** mở rộng native graph.
- **Deployment:** tái sử dụng architecture renderer.
- **Code Map:** tái sử dụng prettygraph và layout repair.

---

# 9. Thay đổi workflow agent

Workflow hiện tại phù hợp với solution architecture:

```text
Analyze requirements
→ Propose diagram brief
→ Propose tech stack
→ Propose architecture blueprint
→ Resolve icons
→ Drawer
→ Critic
→ Final approval
```

Nhưng flow này không phù hợp hoàn toàn với ERD hoặc State Machine.

Ví dụ:

- ERD không cần approve tech stack.
- Sequence không cần WAF pillar.
- State Machine không cần cloud topology.

## Flow mới đề xuất

```text
1. Detect diagram type
2. Extract domain information
3. Propose type-specific plan
4. User approves the plan
5. Render
6. Run type-specific structural lint
7. Run visual critic
8. Final approval
```

## Flow theo từng loại

### Architecture

```text
Requirement
→ Tech stack approval
→ Blueprint approval
→ Render
```

### Sequence

```text
Requirement / OpenAPI
→ Participants + message flow approval
→ Render
```

### ERD

```text
SQL / ORM / requirement
→ Entities + relationships approval
→ Render
```

### State Machine

```text
Requirement / status list
→ States + transitions approval
→ Render
```

Tech stack gate chỉ nên chạy khi diagram thực sự cần tech stack.

---

# 10. Thiết kế Frontend

## Diagram type selector

Ở đầu màn hình:

```text
Diagram type

[ Auto detect ▼ ]

Architecture
Sequence
ERD / Database
State Machine
BPMN / Swimlane
Deployment
Code Map
```

`Auto detect` vẫn là mặc định, nhưng user có thể override.

## Input source selector

```text
Describe
Upload document
Connect repository
Upload SQL
Upload OpenAPI
Upload Infrastructure files
```

## Approval card theo từng loại

Không nên dùng một Blueprint Card cho tất cả.

### Sequence approval card

```text
Participants: 6
Messages: 14
Fragments: 2

Main flow:
User → FE → API → Supabase → Email Provider
```

### ERD approval card

```text
Schemas: 2
Tables: 18
Relationships: 24
Warnings: 3 tables without PK
```

### State approval card

```text
States: 9
Transitions: 16
Actors: Admin, Supplier, System
Unreachable states: 1
```

## Artifact panel

Giữ các output chung:

```text
out.png
out.drawio
diagram_spec.json
engineer_report.json
```

Output bổ sung tùy loại:

```text
sequence_source.json
schema.sql.normalized
transition_table.csv
code_graph.json
```

Không nên bắt mọi diagram phải sinh `diagram.py`.

`diagram.py` phù hợp với architecture renderer hiện tại, nhưng không nên là canonical source cho ERD và Sequence.

Canonical source mới nên là:

```text
diagram_spec.json
```

---

# 11. Những loại chưa nên ưu tiên

## Use Case Diagram

Giá trị implementation không cao.

Actor và capability có thể biểu diễn bằng:

- C4 Context
- Context Diagram
- Architecture preset

## Generic Flowchart / Activity Diagram

BPMN/swimlane hiện đã mạnh hơn và có schema riêng cho:

- Lane
- Phase
- Task
- Gateway
- Event
- Message flow

## C4 Context và Container

Repo đã có `c4_level="context"|"container"`.

Chỉ cần hoàn thiện preset, không cần tạo feature mới hoàn toàn.

## Generic Class Diagram

Repo đã có Python inheritance graph.

Nên nâng thành Code Map thay vì chỉ bổ sung một class renderer nhỏ.

## CI/CD Diagram

Có thể triển khai như architecture/deployment preset từ:

- GitHub Actions
- GitLab CI
- Bitbucket Pipelines
- Jenkins

Không cần renderer độc lập.

## Data Flow Diagram

Có thể là architecture preset với:

- node kind `source`
- node kind `process`
- node kind `data`
- edge flow `data`

Chỉ nên làm riêng khi cần DFD Level 0/1/2 nghiêm ngặt.

---

# 12. Roadmap khuyến nghị

## Phase 1 — Typed diagram foundation

- Thêm `diagram_kind`.
- Tạo `DiagramSpec` union.
- Tạo renderer registry.
- Tách type detection khỏi architecture analysis.
- Tạo type-specific lint framework.
- Thêm diagram selector ở frontend.
- Giữ backward compatibility cho Blueprint và ProcessBlueprint hiện tại.

## Phase 2 — True Sequence Diagram

- Sequence schema.
- Native lifeline renderer.
- Activation bar.
- Fragments `alt`, `opt`, `loop`, `par`.
- Draw.io UML shapes.
- API flow preset.
- Structural tests.

## Phase 3 — ERD

- SQL DDL parser.
- PostgreSQL support trước.
- Entity/column/FK schema.
- Crow’s-foot draw.io renderer.
- Dependency-aware layout.
- Schema lint.

## Phase 4 — State Machine

- State/transition schema.
- State-specific shapes.
- Unreachable/dead-end validation.
- Export transition table.
- Permission/actor metadata.

## Phase 5 — Deployment và Code Map

- Docker Compose parser.
- Kubernetes parser.
- Terraform parser.
- TypeScript code analyzer.
- Architecture-vs-runtime comparison.

---

# 13. Kết luận đề xuất

Không nên biến repo thành một công cụ:

> “Vẽ được 30 loại diagram nhưng loại nào cũng nông.”

Nên định vị sản phẩm thành:

> **AI Software Diagram Agent có khả năng hiểu requirement, source code, database và infrastructure; tạo diagram có ngữ nghĩa, kiểm tra logic và xuất draw.io chỉnh sửa được.**

Bộ diagram chiến lược:

```text
Architecture   → System structure
BPMN           → Business process
Sequence       → Runtime interaction
ERD            → Data structure
State Machine  → Entity lifecycle
Deployment     → Runtime infrastructure
Code Map       → Source-code structure
```

Trong đó, bộ ba nên triển khai đầu tiên là:

1. **True Sequence Diagram**
2. **ERD**
3. **State Machine Diagram**

Ba loại này bổ sung đúng những khoảng trống lớn nhất của repo hiện tại, có giá trị rõ cho:

- BA
- Frontend developer
- Backend developer
- QA
- Architect
- DevOps
- DBA

Đồng thời vẫn tận dụng được các nền tảng repo đã có:

- HITL approval
- Visual critic
- Draw.io export
- Layout engine
- Static audit
- Blueprint workflow
