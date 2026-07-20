# Cách tái tạo và nâng cấp file Draw.io bằng GPT API

> Tài liệu này mô tả quy trình kỹ thuật có thể tái tạo được, các quyết định thiết kế, prompt mẫu và code khung để tự động chuyển một ảnh kiến trúc tham chiếu cùng file `.drawio` cũ thành một file `.drawio` production-ready.
>
> Tôi không thể cung cấp private chain-of-thought nội bộ theo dạng suy nghĩ từng token. Thay vào đó, tài liệu này ghi lại đầy đủ **phương pháp, rationale kỹ thuật, quy tắc thiết kế và quy trình kiểm thử** để bạn có thể triển khai lại bằng API.

---

## 1. Bản chất công việc tôi đã làm

Tôi không xử lý ảnh như một ảnh nền rồi đặt vào Draw.io. Tôi tái dựng sơ đồ thành các phần tử có thể chỉnh sửa:

- Mỗi layer là một `mxCell`.
- Mỗi service card là một hoặc nhiều `mxCell`.
- Mỗi icon được nhúng vào file dưới dạng `data:image/png;base64,...`.
- Mỗi connector là một edge với source, target và các waypoint.
- Màu sắc, font, bo góc, shadow, gradient và line style được viết trực tiếp vào XML.
- File cuối vẫn là Draw.io XML chuẩn, nên người dùng có thể mở và chỉnh sửa từng object.

Quy trình tổng quát:

```text
Ảnh tham chiếu + file Draw.io hiện tại
                 │
                 ▼
        Phân tích cấu trúc ảnh
                 │
                 ▼
       Chuẩn hóa thành DiagramSpec
                 │
                 ▼
    Python sinh hoặc chỉnh mxGraph XML
                 │
                 ▼
       Validate XML và connector
                 │
                 ▼
        Export preview rồi QA
                 │
                 └── lặp lại nếu cần
```

---

## 2. Vì sao kết quả tốt hơn khi không yêu cầu GPT xuất thẳng XML

Không nên dùng một prompt kiểu:

```text
Hãy nhìn ảnh này và trả về toàn bộ file Draw.io XML.
```

Cách đó dễ gặp:

- XML bị thiếu hoặc sai escape.
- ID trùng nhau.
- Edge trỏ vào source/target không tồn tại.
- Một thay đổi nhỏ khiến model viết lại hàng trăm KB XML.
- Tọa độ không ổn định giữa các lần chạy.
- Connector chồng lên card.
- Icon base64 làm output quá lớn và dễ bị cắt.

Cách production tốt hơn là chia trách nhiệm:

### GPT chịu trách nhiệm

- Hiểu bố cục và ý nghĩa.
- Nhận diện zone, node, edge, label.
- Đề xuất tọa độ tương đối.
- Phân loại luồng dữ liệu.
- So sánh preview với ảnh tham chiếu.
- Trả về JSON có schema cố định.

### Python chịu trách nhiệm

- Tạo ID ổn định.
- Viết XML đúng chuẩn.
- Escape text.
- Nhúng icon.
- Tạo waypoint.
- Validate source/target.
- Sắp xếp z-order.
- Lưu file `.drawio`.

Đây là điểm quan trọng nhất để scale sang nhiều sơ đồ.

---

## 3. Những quyết định thiết kế đã dùng cho sơ đồ SKT TTMBS

### 3.1. Chuẩn hóa canvas

Ảnh tham chiếu có tỷ lệ gần 16:9, nên tôi dùng hệ tọa độ:

```text
Canvas: 2048 × 1152
```

Việc dùng hệ tọa độ cố định giúp:

- dễ đo vị trí theo pixel;
- dễ xuất preview;
- dễ tái sử dụng prompt;
- dễ so sánh ảnh output với ảnh reference.

### 3.2. Chia bố cục thành hai vùng lớn

```text
┌──────────────────┬──────────────────────────────────────────────┐
│ Management       │ Main architecture layers                    │
│ Security & CI/CD │ Dashboard / Storage / Stream / Broker / Edge │
└──────────────────┴──────────────────────────────────────────────┘
```

Trong file production:

- cột trái bắt đầu khoảng `x=66`;
- khu vực chính bắt đầu khoảng `x=474`;
- toàn bộ diagram nằm trong một outer panel có bo góc và shadow.

### 3.3. Các layer chính

| Layer | Vị trí gần đúng | Màu nền |
|---|---:|---|
| Dashboard & User Application | y=120 | tím-hồng rất nhạt |
| Data & Storage | y=245 | vàng-cam rất nhạt |
| Stream Processing & Analytics | y=348 | xanh lá-be rất nhạt |
| Message Brokering & Routing | y=487 | xanh dương-tím rất nhạt |
| Edge Devices & Access | y=660 | tím-hồng rất nhạt |

Palette được giữ nhạt để card trắng và connector nổi bật hơn.

### 3.4. Card service

Mỗi card có:

- nền trắng;
- stroke xám;
- bo góc;
- shadow nhẹ;
- icon bên trái;
- title bold;
- subtitle nhỏ hơn;
- khoảng cách nội dung nhất quán.

Không nên dùng một object duy nhất cho cả card và icon nếu muốn dễ chỉnh sửa. Cách tốt hơn:

```text
card_bg
├── icon
└── card_text
```

### 3.5. Connector

Tôi dùng connector kiểu orthogonal/Manhattan:

```text
ngang → dọc → ngang
```

Mỗi loại flow có màu riêng:

- MQTT/device delivery: xanh dương.
- Event processing: tím/xám.
- Public storage flow: nâu đỏ nhạt.
- Dashboard API: xanh lá.
- Security & auth: đỏ dashed.
- CI/CD: xanh lá đậm.
- Background sounding/logging: xám.

Các connector quan trọng được định tuyến bằng waypoint thay vì để Draw.io tự route hoàn toàn.

### 3.6. Icon

Icon được nhúng vào XML bằng data URI:

```text
shape=image;
image=data:image/png;base64,...
```

Lợi ích:

- file mở được trên máy khác;
- không phụ thuộc URL ngoài;
- không bị mất icon khi offline;
- preview và file Draw.io nhất quán.

Nhược điểm:

- file lớn hơn;
- không nên gửi toàn bộ base64 vào GPT.

Trong pipeline API, hãy lưu icon ở thư mục local và để Python nhúng vào cuối cùng.

---

## 4. Cấu trúc cơ bản của file Draw.io

Một file `.drawio` thường là XML dạng:

```xml
<mxfile>
  <diagram>
    <mxGraphModel>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>

        <!-- vertices -->
        <!-- edges -->
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

### Vertex

```xml
<mxCell
  id="firestore_card"
  value="Cloud Firestore"
  style="rounded=1;whiteSpace=wrap;html=1;..."
  vertex="1"
  parent="1">
  <mxGeometry x="1320" y="270" width="190" height="70" as="geometry"/>
</mxCell>
```

### Edge

```xml
<mxCell
  id="api_to_firestore"
  edge="1"
  parent="1"
  source="api_card"
  target="firestore_card"
  style="edgeStyle=orthogonalEdgeStyle;endArrow=block;...">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
```

### Edge có waypoint

```xml
<mxGeometry relative="1" as="geometry">
  <Array as="points">
    <mxPoint x="1450" y="215"/>
    <mxPoint x="1450" y="270"/>
  </Array>
</mxGeometry>
```

---

## 5. Kiến trúc API nên dùng

Tôi khuyên dùng pipeline ba bước.

## Bước A — Extract reference image thành JSON

Đầu vào:

- ảnh tham chiếu;
- inventory rút gọn từ file Draw.io cũ;
- kích thước canvas mong muốn.

Đầu ra:

```json
{
  "canvas": {"width": 2048, "height": 1152},
  "zones": [],
  "nodes": [],
  "edges": [],
  "legend_items": []
}
```

## Bước B — Python sinh Draw.io

Python đọc JSON và tạo:

- `mxfile`;
- `mxGraphModel`;
- zone;
- card;
- text;
- icon;
- edge;
- legend.

## Bước C — Visual QA

- export file mới thành PNG;
- gửi cả reference và preview vào GPT;
- GPT chỉ trả về danh sách patch;
- Python áp patch lên JSON spec;
- sinh lại file.

Không yêu cầu GPT viết lại XML trong vòng QA.

---

## 6. Schema đề xuất cho Structured Outputs

```python
from typing import Literal
from pydantic import BaseModel, Field


class Point(BaseModel):
    x: float
    y: float


class Canvas(BaseModel):
    width: int = 2048
    height: int = 1152


class Zone(BaseModel):
    id: str
    title: str
    x: float
    y: float
    width: float
    height: float
    fill: str
    gradient: str | None = None
    stroke: str = "#AEB4BE"


class Node(BaseModel):
    id: str
    zone_id: str
    title: str
    subtitle: str = ""
    x: float
    y: float
    width: float
    height: float
    icon_key: str | None = None
    kind: Literal[
        "service_card",
        "device",
        "network",
        "public_access",
        "label"
    ] = "service_card"


class Edge(BaseModel):
    id: str
    source: str
    target: str
    flow_type: Literal[
        "mqtt",
        "event",
        "storage",
        "dashboard_api",
        "security",
        "cicd",
        "logging"
    ]
    label: str = ""
    dashed: bool = False
    waypoints: list[Point] = Field(default_factory=list)


class LegendItem(BaseModel):
    label: str
    flow_type: str
    dashed: bool = False


class DiagramSpec(BaseModel):
    canvas: Canvas
    title: str
    zones: list[Zone]
    nodes: list[Node]
    edges: list[Edge]
    legend_items: list[LegendItem]
    assumptions: list[str] = Field(default_factory=list)
```

Structured output giúp bạn tránh trường hợp GPT trả về JSON thiếu field hoặc sai kiểu dữ liệu.

---

## 7. Prompt chính để phân tích ảnh

```text
You are an expert architecture-diagram reconstruction planner.

Your task is NOT to generate Draw.io XML.
Return only data matching the provided schema.

Inputs:
1. A reference architecture diagram image.
2. A compact inventory extracted from an existing Draw.io file.
3. A target canvas of 2048x1152.

Goals:
- Reconstruct the visual hierarchy and semantic architecture.
- Preserve service names and relationships from the inventory whenever they
  are supported by the reference image.
- Do not invent services that are not visible or present in the inventory.
- Separate the diagram into zones, nodes, edges and legend items.
- Use absolute coordinates in the 2048x1152 canvas.
- Keep at least 12px internal padding inside zones.
- Keep at least 16px between cards unless the reference clearly differs.
- Prefer orthogonal edge routes.
- Add waypoints where automatic routing would cross cards.
- Use stable snake_case IDs.
- Keep title and subtitle text separate.
- For uncertain text, include the uncertainty in assumptions rather than
  silently inventing content.
- Return editable objects, never use the reference image as a background.
```

### Điều cần thêm vào prompt

Hãy gửi inventory rút gọn:

```text
Existing Draw.io inventory:
- node: Cloud IAM | current id: iam
- node: Secret Manager | current id: secret_manager
- edge: Cloud IAM -> Secret Manager
...
```

Không gửi icon base64 hoặc toàn bộ XML 300–500 KB vào prompt.

---

## 8. Code gọi OpenAI API với ảnh và Structured Outputs

API hiện đại nên dùng `Responses API`. Model name nên để trong biến môi trường để dễ đổi.

```python
import base64
import json
import os
from pathlib import Path

from openai import OpenAI

client = OpenAI()


def encode_image(path: str | Path) -> str:
    data = Path(path).read_bytes()
    return base64.b64encode(data).decode("utf-8")


def get_diagram_spec(
    reference_image: str,
    inventory: list[dict],
) -> DiagramSpec:
    image_b64 = encode_image(reference_image)

    prompt = f"""
You are an expert architecture-diagram reconstruction planner.

Do not generate Draw.io XML.
Return a DiagramSpec.

Target canvas: 2048x1152.

Existing inventory:
{json.dumps(inventory, ensure_ascii=False, indent=2)}

Rules:
- Preserve semantic labels.
- Reconstruct zones, cards, connectors and legend.
- Use absolute coordinates.
- Use orthogonal connector waypoints.
- Do not include icon base64.
- Do not invent unsupported services.
"""

    response = client.responses.parse(
        model=os.getenv("OPENAI_MODEL", "gpt-5.6"),
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": prompt,
                    },
                    {
                        "type": "input_image",
                        "image_url": (
                            "data:image/png;base64,"
                            + image_b64
                        ),
                    },
                ],
            }
        ],
        text_format=DiagramSpec,
    )

    return response.output_parsed
```

### Cài thư viện

```bash
pip install -U openai pydantic lxml pillow
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-5.6"
```

---

## 9. Rút gọn file Draw.io cũ thành inventory

Không gửi nguyên file cũ vào model. Hãy rút ra text, tọa độ, style và quan hệ.

```python
import re
import xml.etree.ElementTree as ET
from html import unescape


TAG_RE = re.compile(r"<[^>]+>")


def clean_drawio_text(value: str) -> str:
    value = unescape(value or "")
    value = value.replace("<br>", "\n").replace("<br/>", "\n")
    value = TAG_RE.sub("", value)
    return " ".join(value.split())


def extract_inventory(drawio_path: str) -> list[dict]:
    tree = ET.parse(drawio_path)
    root = tree.getroot()

    inventory: list[dict] = []

    for cell in root.findall(".//mxCell"):
        cell_id = cell.get("id")
        value = clean_drawio_text(cell.get("value", ""))
        geometry = cell.find("mxGeometry")

        if cell.get("vertex") == "1":
            item = {
                "type": "vertex",
                "id": cell_id,
                "text": value,
                "style": cell.get("style", "")[:500],
            }

            if geometry is not None:
                item["geometry"] = {
                    "x": float(geometry.get("x", 0)),
                    "y": float(geometry.get("y", 0)),
                    "width": float(geometry.get("width", 0)),
                    "height": float(geometry.get("height", 0)),
                }

            # Bỏ các object nền không có text nếu inventory quá lớn.
            if value or "image=" not in item["style"]:
                inventory.append(item)

        elif cell.get("edge") == "1":
            inventory.append(
                {
                    "type": "edge",
                    "id": cell_id,
                    "source": cell.get("source"),
                    "target": cell.get("target"),
                    "text": value,
                    "style": cell.get("style", "")[:500],
                }
            )

    return inventory
```

### Giới hạn inventory

Bạn có thể lọc thêm:

- bỏ icon base64;
- bỏ background;
- bỏ cell không có text;
- rút style còn `fillColor`, `strokeColor`, `dashed`, `endArrow`;
- giới hạn khoảng 20.000–50.000 ký tự.

---

## 10. Bộ generator Draw.io tối thiểu

Dưới đây là code khung để chuyển `DiagramSpec` thành `.drawio`.

```python
import base64
import mimetypes
import xml.etree.ElementTree as ET
from pathlib import Path


FLOW_STYLES = {
    "mqtt": {
        "color": "#2D69B2",
        "width": 2.0,
    },
    "event": {
        "color": "#756A95",
        "width": 1.8,
    },
    "storage": {
        "color": "#AD6B66",
        "width": 1.8,
    },
    "dashboard_api": {
        "color": "#2D7D5A",
        "width": 1.8,
    },
    "security": {
        "color": "#A63A35",
        "width": 1.8,
    },
    "cicd": {
        "color": "#2D7D5A",
        "width": 1.8,
    },
    "logging": {
        "color": "#6E7A86",
        "width": 1.6,
    },
}


def style_string(**kwargs) -> str:
    parts = []
    for key, value in kwargs.items():
        key = key.replace("_", "-")
        parts.append(f"{key}={value}")
    return ";".join(parts) + ";"


def add_geometry(
    cell: ET.Element,
    x: float,
    y: float,
    width: float,
    height: float,
) -> ET.Element:
    return ET.SubElement(
        cell,
        "mxGeometry",
        {
            "x": str(round(x, 2)),
            "y": str(round(y, 2)),
            "width": str(round(width, 2)),
            "height": str(round(height, 2)),
            "as": "geometry",
        },
    )


def add_vertex(
    root: ET.Element,
    *,
    cell_id: str,
    value: str,
    x: float,
    y: float,
    width: float,
    height: float,
    style: str,
    parent: str = "1",
) -> ET.Element:
    cell = ET.SubElement(
        root,
        "mxCell",
        {
            "id": cell_id,
            "value": value,
            "style": style,
            "vertex": "1",
            "parent": parent,
        },
    )
    add_geometry(cell, x, y, width, height)
    return cell


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def zone_style(zone: Zone) -> str:
    style = (
        "rounded=1;arcSize=4;whiteSpace=wrap;html=1;"
        f"fillColor={zone.fill};"
        f"strokeColor={zone.stroke};"
        "strokeWidth=1.2;shadow=1;"
    )

    if zone.gradient:
        style += (
            f"gradientColor={zone.gradient};"
            "gradientDirection=east;"
        )

    return style


def card_style() -> str:
    return (
        "rounded=1;arcSize=8;whiteSpace=wrap;html=1;"
        "fillColor=#FFFFFF;"
        "strokeColor=#AEB4BE;"
        "strokeWidth=1;"
        "shadow=1;"
    )


def text_style(
    *,
    font_size: int = 15,
    bold: bool = False,
    align: str = "left",
) -> str:
    return (
        "text;html=1;strokeColor=none;fillColor=none;"
        f"align={align};verticalAlign=middle;"
        "whiteSpace=wrap;"
        "fontFamily=Arial;"
        f"fontSize={font_size};"
        "fontColor=#111827;"
        f"fontStyle={1 if bold else 0};"
    )


def add_service_card(
    root: ET.Element,
    node: Node,
    icon_dir: Path,
) -> None:
    add_vertex(
        root,
        cell_id=f"{node.id}_bg",
        value="",
        x=node.x,
        y=node.y,
        width=node.width,
        height=node.height,
        style=card_style(),
    )

    icon_width = min(48, node.height - 18)
    icon_x = node.x + 12
    icon_y = node.y + (node.height - icon_width) / 2

    if node.icon_key:
        icon_path = icon_dir / f"{node.icon_key}.png"
        if icon_path.exists():
            add_vertex(
                root,
                cell_id=f"{node.id}_icon",
                value="",
                x=icon_x,
                y=icon_y,
                width=icon_width,
                height=icon_width,
                style=(
                    "shape=image;html=1;aspect=fixed;"
                    f"image={data_uri(icon_path)};"
                ),
            )

    text_x = node.x + 70
    text_width = node.width - 80

    title_height = 24
    add_vertex(
        root,
        cell_id=f"{node.id}_title",
        value=node.title,
        x=text_x,
        y=node.y + 8,
        width=text_width,
        height=title_height,
        style=text_style(font_size=15, bold=True),
    )

    if node.subtitle:
        add_vertex(
            root,
            cell_id=f"{node.id}_subtitle",
            value=node.subtitle,
            x=text_x,
            y=node.y + 28,
            width=text_width,
            height=node.height - 34,
            style=text_style(font_size=12),
        )


def edge_style(edge: Edge) -> str:
    cfg = FLOW_STYLES[edge.flow_type]

    return (
        "edgeStyle=orthogonalEdgeStyle;"
        "rounded=0;"
        "orthogonalLoop=1;"
        "jettySize=auto;"
        "html=1;"
        f"strokeColor={cfg['color']};"
        f"strokeWidth={cfg['width']};"
        f"dashed={1 if edge.dashed else 0};"
        "endArrow=block;"
        "endFill=1;"
    )


def add_edge(root: ET.Element, edge: Edge) -> None:
    cell = ET.SubElement(
        root,
        "mxCell",
        {
            "id": edge.id,
            "value": edge.label,
            "style": edge_style(edge),
            "edge": "1",
            "parent": "1",
            "source": f"{edge.source}_bg",
            "target": f"{edge.target}_bg",
        },
    )

    geometry = ET.SubElement(
        cell,
        "mxGeometry",
        {
            "relative": "1",
            "as": "geometry",
        },
    )

    if edge.waypoints:
        points = ET.SubElement(geometry, "Array", {"as": "points"})
        for point in edge.waypoints:
            ET.SubElement(
                points,
                "mxPoint",
                {
                    "x": str(round(point.x, 2)),
                    "y": str(round(point.y, 2)),
                },
            )


def build_drawio(
    spec: DiagramSpec,
    output_path: str,
    icon_dir: str,
) -> None:
    mxfile = ET.Element(
        "mxfile",
        {
            "host": "app.diagrams.net",
            "version": "26.0.16",
        },
    )

    diagram = ET.SubElement(
        mxfile,
        "diagram",
        {
            "name": "Production Architecture",
            "id": "production_architecture",
        },
    )

    graph = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": str(spec.canvas.width),
            "dy": str(spec.canvas.height),
            "grid": "0",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": str(spec.canvas.width),
            "pageHeight": str(spec.canvas.height),
            "math": "0",
            "shadow": "0",
            "background": "#FFFFFF",
        },
    )

    root = ET.SubElement(graph, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    # Canvas
    add_vertex(
        root,
        cell_id="canvas",
        value="",
        x=0,
        y=0,
        width=spec.canvas.width,
        height=spec.canvas.height,
        style=(
            "rounded=0;whiteSpace=wrap;html=1;"
            "fillColor=#FFFFFF;strokeColor=none;"
        ),
    )

    # Outer panel
    add_vertex(
        root,
        cell_id="outer",
        value="",
        x=38,
        y=30,
        width=spec.canvas.width - 76,
        height=spec.canvas.height - 72,
        style=(
            "rounded=1;arcSize=9;whiteSpace=wrap;html=1;"
            "fillColor=#FFFFFF;"
            "strokeColor=#D7DEE8;"
            "strokeWidth=1.2;"
            "shadow=1;"
        ),
    )

    # Title
    add_vertex(
        root,
        cell_id="title",
        value=spec.title,
        x=450,
        y=45,
        width=1150,
        height=55,
        style=text_style(font_size=34, bold=True, align="center"),
    )

    # Zones trước để nằm dưới card.
    for zone in spec.zones:
        add_vertex(
            root,
            cell_id=zone.id,
            value="",
            x=zone.x,
            y=zone.y,
            width=zone.width,
            height=zone.height,
            style=zone_style(zone),
        )

        add_vertex(
            root,
            cell_id=f"{zone.id}_title",
            value=zone.title,
            x=zone.x + 10,
            y=zone.y + 5,
            width=zone.width - 20,
            height=28,
            style=text_style(font_size=17, bold=True),
        )

    # Card sau zone.
    icon_path = Path(icon_dir)
    for node in spec.nodes:
        add_service_card(root, node, icon_path)

    # Edge sau card hoặc trước card tùy z-order mong muốn.
    # Trong nhiều sơ đồ production, đặt edge sau background nhưng trước text
    # sẽ đẹp hơn. Nếu edge che card, hãy chèn edge trước service card.
    for edge in spec.edges:
        add_edge(root, edge)

    tree = ET.ElementTree(mxfile)
    ET.indent(tree, space="  ")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tree.write(
        output,
        encoding="utf-8",
        xml_declaration=False,
    )
```

### Lưu ý về z-order

Draw.io hiển thị object theo thứ tự cell trong XML.

Thứ tự thường dùng:

```text
canvas
outer panel
zones
connectors
card background
icons
text
legend
```

Nếu connector che text, hãy sinh connector trước card. Nếu connector cần nổi trên zone nhưng dưới card, đặt nó sau zone và trước card.

---

## 11. Validate file trước khi gửi cho người dùng

### 11.1. Validate XML

```python
import xml.etree.ElementTree as ET

ET.parse("output.drawio")
print("XML valid")
```

### 11.2. Validate ID và edge reference

```python
def validate_drawio(path: str) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    cells = root.findall(".//mxCell")

    ids = [c.get("id") for c in cells if c.get("id")]
    duplicate_ids = sorted(
        {cell_id for cell_id in ids if ids.count(cell_id) > 1}
    )

    if duplicate_ids:
        raise ValueError(f"Duplicate IDs: {duplicate_ids}")

    id_set = set(ids)

    for cell in cells:
        if cell.get("edge") != "1":
            continue

        source = cell.get("source")
        target = cell.get("target")

        if source and source not in id_set:
            raise ValueError(
                f"Edge {cell.get('id')} missing source {source}"
            )

        if target and target not in id_set:
            raise ValueError(
                f"Edge {cell.get('id')} missing target {target}"
            )

    print(
        f"Valid: {len(ids)} cells, "
        f"{sum(c.get('edge') == '1' for c in cells)} edges"
    )
```

### 11.3. Validate geometry

Nên kiểm tra:

- width và height > 0;
- card nằm trong zone;
- card không vượt canvas;
- không có hai card trùng gần như hoàn toàn;
- waypoint không nằm trong card;
- title không bị cắt.

---

## 12. QA bằng hai ảnh

Sau khi export file `.drawio` thành PNG, gửi:

1. ảnh reference;
2. ảnh preview;
3. một schema patch.

Ví dụ patch schema:

```python
class GeometryPatch(BaseModel):
    object_id: str
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None


class TextPatch(BaseModel):
    object_id: str
    title: str | None = None
    subtitle: str | None = None


class EdgePatch(BaseModel):
    edge_id: str
    waypoints: list[Point] | None = None
    label: str | None = None


class DiagramPatch(BaseModel):
    geometry: list[GeometryPatch] = []
    text: list[TextPatch] = []
    edges: list[EdgePatch] = []
    visual_notes: list[str] = []
```

Prompt QA:

```text
Compare image A, the reference diagram, with image B, the generated preview.

Do not regenerate the full diagram.
Return only a DiagramPatch.

Priorities:
1. Missing or incorrect nodes.
2. Major position and size mismatch.
3. Connector direction and routing.
4. Layer height and spacing.
5. Text clipping.
6. Minor color differences.

Do not request changes smaller than 3 pixels.
Do not change a correct semantic relationship only to mimic a visually
ambiguous crossing.
```

---

## 13. Cách export preview

Có ba lựa chọn:

### Cách 1 — Mở thủ công bằng diagrams.net

- mở `.drawio`;
- File → Export as → PNG;
- dùng scale 1x hoặc 2x.

### Cách 2 — Draw.io Desktop CLI

Tùy hệ điều hành và tên binary:

```bash
drawio \
  --export \
  --format png \
  --scale 1.5 \
  --output preview.png \
  output.drawio
```

Trên môi trường Linux headless đôi khi cần `xvfb-run`.

### Cách 3 — Trình duyệt tự động

Dùng Playwright mở diagrams.net, import file và export ảnh. Cách này phức tạp hơn nhưng phù hợp với hệ thống SaaS.

---

## 14. Chiến lược chỉnh file hiện tại thay vì tạo mới

Có hai kiểu bài toán.

### 14.1. Rebuild hoàn toàn

Dùng khi:

- file cũ có layout rất tệ;
- nhiều object thừa;
- connector rối;
- style không đồng nhất.

Giữ lại:

- service names;
- descriptions;
- relationships;
- icon assets.

Tạo mới toàn bộ geometry và style.

Đây là cách phù hợp với sơ đồ SKT TTMBS.

### 14.2. Patch file cũ

Dùng khi:

- cấu trúc semantic đã tốt;
- chỉ cần chỉnh alignment, spacing, màu, size;
- cần giữ ID để các hệ thống khác tham chiếu.

Patch trực tiếp:

```python
cell_by_id["firestore"].find("mxGeometry").set("x", "1320")
cell_by_id["firestore"].set("style", new_style)
```

Không nên rebuild nếu downstream đang dùng ID cell.

---

## 15. Quy tắc để kết quả nhìn “production”

### Layout

- Dùng lưới 8 px hoặc 12 px.
- Căn card theo hàng.
- Giữ khoảng cách card nhất quán.
- Layer title có cùng baseline.
- Không để card sát mép layer.
- Chừa khu vực routing connector.

### Typography

- Một font duy nhất.
- Title sơ đồ: 30–36 px.
- Layer title: 16–18 px.
- Card title: 14–16 px bold.
- Subtitle: 11–13 px.
- Không dùng quá nhiều độ đậm.

### Color

- Background layer nhạt.
- Card trắng.
- Border xám nhẹ.
- Connector dùng màu có ý nghĩa.
- Không dùng màu saturated cho diện tích lớn.
- Mỗi loại flow chỉ có một màu trong toàn sơ đồ.

### Connector

- Tránh đường chéo.
- Hạn chế crossing.
- Label đặt trên đoạn thẳng dài.
- Arrow direction phải đúng.
- Dùng dashed cho security/control flow nếu legend quy định.
- Waypoint nên nằm ngoài card.

### Content

- Title service ngắn.
- Subtitle mô tả vai trò, không phải đoạn văn dài.
- Không lặp tên layer trong card.
- Không thêm công nghệ không có bằng chứng.

---

## 16. Prompt dùng để yêu cầu GPT sửa một file Draw.io

```text
You are a Draw.io architecture diagram editor.

I will provide:
- a reference image;
- an existing Draw.io inventory;
- current node and edge IDs.

Produce a structured edit plan, not XML.

Objectives:
- Make the existing diagram visually match the reference.
- Preserve semantics and service names.
- Preserve existing IDs when a matching object exists.
- Create new IDs only for genuinely missing objects.
- Remove or hide objects not present in the target architecture.
- Use a 2048x1152 coordinate system.
- Separate content into background zones, service cards, connectors and
  legend.
- Use orthogonal connectors and explicit waypoints.
- Return confidence and assumptions for any uncertain relationship.

The downstream Python generator will apply the plan and validate XML.
```

---

## 17. Prompt để GPT tạo diagram mới từ mô tả text

```text
Create a production architecture DiagramSpec for the following system.

System description:
{{DESCRIPTION}}

Constraints:
- Canvas 2048x1152.
- Editable Draw.io objects.
- Left column for security, governance and CI/CD.
- Main horizontal layers for application, storage, processing, messaging
  and edge/access.
- At most 6 cards in one row.
- Use orthogonal connectors.
- Add a legend for every flow type used.
- Avoid invented services.
- Include assumptions when the input is incomplete.
- Return structured data only.
```

Sau đó Python dùng cùng generator để sinh `.drawio`.

---

## 18. Batch xử lý nhiều sơ đồ

Cấu trúc thư mục:

```text
project/
├── inputs/
│   ├── diagram_001/
│   │   ├── reference.png
│   │   └── current.drawio
│   └── diagram_002/
├── icons/
├── specs/
├── outputs/
├── previews/
└── scripts/
    ├── extract_inventory.py
    ├── analyze_reference.py
    ├── build_drawio.py
    ├── validate_drawio.py
    └── qa_preview.py
```

Pipeline:

```bash
python scripts/extract_inventory.py \
  inputs/diagram_001/current.drawio \
  > specs/diagram_001_inventory.json

python scripts/analyze_reference.py \
  --image inputs/diagram_001/reference.png \
  --inventory specs/diagram_001_inventory.json \
  --output specs/diagram_001_spec.json

python scripts/build_drawio.py \
  --spec specs/diagram_001_spec.json \
  --icons icons \
  --output outputs/diagram_001.drawio

python scripts/validate_drawio.py \
  outputs/diagram_001.drawio
```

Sau đó export preview và chạy QA.

---

## 19. Tối ưu chi phí API

- Resize ảnh còn khoảng 1600–2200 px chiều ngang.
- Không gửi ảnh 4K nếu không cần.
- Không gửi icon base64.
- Không gửi nguyên XML nhiều lần.
- Cache inventory theo hash file.
- Chỉ dùng model mạnh cho bước image analysis và QA.
- Dùng code deterministic cho XML.
- Vòng QA chỉ trả patch nhỏ.
- Dừng sau 2–3 vòng nếu sai khác chỉ còn mang tính thẩm mỹ.

Hash cache:

```python
import hashlib


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

---

## 20. Chống lỗi khi chạy production

### Retry API

```python
import time
from openai import APIConnectionError, RateLimitError


def with_retry(callable_fn, attempts: int = 5):
    delay = 2

    for attempt in range(attempts):
        try:
            return callable_fn()
        except (APIConnectionError, RateLimitError):
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2
```

### Không ghi đè file gốc

```text
current.drawio
current.backup.drawio
output_v1.drawio
output_v2.drawio
```

### Lưu spec trung gian

Luôn lưu JSON mà GPT trả về. Khi output sai, bạn có thể:

- sửa JSON thủ công;
- chạy lại generator không tốn API;
- diff giữa hai phiên bản;
- audit model đã thay đổi gì.

### Validate trước khi trả file

Không coi API call thành công là hoàn thành. Chỉ hoàn thành khi:

- parse XML được;
- không trùng ID;
- source/target hợp lệ;
- export preview thành công;
- preview đạt QA.

---

## 21. Những điểm GPT thường làm sai

### Đọc sai text nhỏ

Giải pháp:

- lấy text từ file Draw.io cũ;
- dùng ảnh chỉ để xác định layout;
- đánh dấu uncertainty.

### Tạo quá nhiều connector

Giải pháp:

- đưa edge inventory;
- yêu cầu không invent;
- schema có `source`, `target`, `flow_type`.

### Connector đi xuyên card

Giải pháp:

- explicit waypoint;
- reserved routing lanes;
- QA preview.

### Card không cùng kích thước

Giải pháp:

- normalize theo loại:
  - small: 170×62;
  - medium: 210×72;
  - large: 270×82.

### File mở được nhưng khó chỉnh

Giải pháp:

- tách card, icon và text;
- ID có ý nghĩa;
- không flatten thành ảnh;
- group hợp lý.

### Output quá lớn

Giải pháp:

- icon xử lý local;
- GPT chỉ trả JSON;
- không yêu cầu output XML có base64.

---

## 22. Checklist hoàn chỉnh

### Input

- [ ] Có ảnh reference đủ rõ.
- [ ] Có file `.drawio` hiện tại.
- [ ] Có danh sách service bắt buộc.
- [ ] Có canvas target.
- [ ] Có icon local hoặc mapping icon.

### Analysis

- [ ] Xác định zone.
- [ ] Xác định node.
- [ ] Xác định edge.
- [ ] Xác định legend.
- [ ] Ghi assumption.

### Generate

- [ ] ID ổn định.
- [ ] Style thống nhất.
- [ ] Z-order đúng.
- [ ] Icon nhúng local.
- [ ] Connector có waypoint.

### Validate

- [ ] XML parse thành công.
- [ ] Không duplicate ID.
- [ ] Edge reference hợp lệ.
- [ ] Geometry không âm.
- [ ] Object không vượt canvas.

### QA

- [ ] Preview giống hierarchy reference.
- [ ] Text không bị cắt.
- [ ] Không connector xuyên card.
- [ ] Arrow đúng chiều.
- [ ] Legend khớp line style.
- [ ] File vẫn editable.

---

## 23. Công thức thực tế nên triển khai

```text
GPT Vision
  ↓
DiagramSpec JSON
  ↓
Deterministic Draw.io generator
  ↓
XML validator
  ↓
PNG exporter
  ↓
GPT visual diff
  ↓
Patch JSON
  ↓
Final Draw.io
```

Đừng xây hệ thống theo công thức:

```text
GPT Vision → một lần → XML cuối cùng
```

Sự khác biệt giữa hai cách trên chính là sự khác biệt giữa demo và production.

---

## 24. Tóm tắt cách tôi đã áp dụng cho file của bạn

1. Dùng ảnh tham chiếu làm nguồn cho visual hierarchy.
2. Dùng file Draw.io hiện tại làm nguồn semantic và asset.
3. Chuẩn hóa canvas 2048×1152.
4. Tách rõ cột Management và năm layer chính.
5. Tạo design system thống nhất cho zone, card, title và connector.
6. Tạo lại geometry thay vì cố kéo các object cũ từng chút.
7. Nhúng icon vào file để không phụ thuộc mạng.
8. Route các luồng quan trọng bằng waypoint.
9. Thêm legend khớp với màu và line style.
10. Validate XML và tạo preview để kiểm tra trước khi giao file.

Đó là lý do file cuối trông gần ảnh production nhưng vẫn chỉnh sửa được trong Draw.io.
