# Định hướng tạo PowerPoint nhiều visual bằng Code-first và MCP

## 1. Kết luận nhanh

Với agent hiện tại, không nên dùng MCP làm renderer chính cho toàn bộ deck.

Kiến trúc phù hợp nhất là:

```text
Python Agent
  ├── Phân tích requirement
  ├── Phân tích codebase
  ├── Thiết kế architecture
  ├── Sinh WBS
  ├── Sinh business narrative
  └── Xuất VisualSpec JSON
             ↓
Node.js PowerPoint Renderer
  ├── PptxGenJS
  ├── pptx-automizer
  ├── SVG builders
  ├── Native charts
  └── Visual component library
             ↓
out.pptx
             ↓
Visual QA
  ├── Kiểm tra cấu trúc PPTX
  ├── Render slide thành PNG
  └── Vision critic
             ↓
Optional final editing
  ├── PowerPoint MCP trên Windows
  └── Office.js Add-in
```

Nguyên tắc chính:

> Code-first generator chịu trách nhiệm tạo slide ổn định và đồng nhất.  
> MCP chỉ nên dùng để chỉnh sửa trực tiếp, review hoặc hoàn thiện deck sau cùng.

---

## 2. Các repository và công cụ đáng cân nhắc

### 2.1. PptxGenJS

Repository:

- https://github.com/gitbrent/PptxGenJS

PptxGenJS là lựa chọn phù hợp nhất để tạo PowerPoint bằng code-first trong TypeScript hoặc JavaScript.

Có thể tạo:

- Native PowerPoint shapes
- Text và rich text
- Tables
- Native charts
- Images
- SVG
- Slide masters
- Custom geometry
- Speaker notes
- File `.pptx` có thể chỉnh sửa trong PowerPoint

Phù hợp để tạo các visual như:

- Metric cards
- Three-pillar layouts
- Process flows
- Timelines
- Roadmaps
- Pricing summaries
- Risk matrices
- Architecture layers
- Feature grids
- Native bar, line, donut và pie charts

Ví dụ:

```ts
import pptxgen from "pptxgenjs";

const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE";

const slide = pptx.addSlide();

slide.background = { color: "F7FAFC" };

slide.addText("Finance automation without replacing the ERP", {
  x: 0.7,
  y: 0.45,
  w: 11.8,
  h: 0.55,
  fontFace: "Aptos Display",
  fontSize: 28,
  bold: true,
  color: "14394B",
});

const cards = [
  {
    title: "Fragmented Inputs",
    body: "Documents arrive through email, portals, EDI, scans and e-invoice channels.",
  },
  {
    title: "Controlled Automation",
    body: "IDP, orchestration and business rules process transactions consistently.",
  },
  {
    title: "Finance Outcomes",
    body: "Faster reconciliation, traceable approvals and fewer manual touchpoints.",
  },
];

cards.forEach((card, index) => {
  const x = 0.7 + index * 4.15;

  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y: 1.55,
    w: 3.75,
    h: 3.3,
    fill: { color: "FFFFFF" },
    line: { color: "D9E5EA", width: 1 },
    shadow: {
      type: "outer",
      color: "A7B8C2",
      opacity: 0.16,
      blur: 2,
      angle: 45,
      distance: 1,
    },
  });

  slide.addText(`${index + 1}`, {
    x: x + 0.25,
    y: 1.85,
    w: 0.48,
    h: 0.48,
    shape: pptx.ShapeType.ellipse,
    fill: { color: "00AFC1" },
    color: "FFFFFF",
    bold: true,
    align: "center",
    valign: "mid",
    fontSize: 15,
    margin: 0,
  });

  slide.addText(card.title, {
    x: x + 0.25,
    y: 2.55,
    w: 3.15,
    h: 0.55,
    bold: true,
    fontSize: 20,
    color: "14394B",
  });

  slide.addText(card.body, {
    x: x + 0.25,
    y: 3.25,
    w: 3.15,
    h: 1.05,
    fontSize: 13,
    color: "536571",
    valign: "top",
    margin: 0,
  });
});

await pptx.writeFile({
  fileName: "finance-automation.pptx",
});
```

Toàn bộ card, text và shapes vẫn có thể chỉnh sửa trong PowerPoint.

---

### 2.2. pptx-automizer

Repository:

- https://github.com/singerla/pptx-automizer

`pptx-automizer` phù hợp khi đã có một PowerPoint template được thiết kế sẵn.

Công cụ này hỗ trợ:

- Load PowerPoint template
- Clone slide
- Clone shape
- Merge nhiều template
- Giữ slide master và theme
- Thay đổi nội dung trong shape có sẵn
- Kết hợp template với các shape tạo bằng PptxGenJS

Kiến trúc sử dụng:

```text
BnK template.pptx
        ↓
pptx-automizer
        ├── Clone cover slide
        ├── Clone section divider
        ├── Clone branded detail slide
        └── Preserve master/theme
                ↓
PptxGenJS
        ├── Add cards
        ├── Add diagrams
        ├── Add native charts
        ├── Add SVG
        └── Add timelines
                ↓
out.pptx
```

Đây là lựa chọn tốt nếu muốn giữ nguyên nhận diện BnK nhưng vẫn thêm nhiều visual code-first.

---

### 2.3. python-pptx

Repository:

- https://github.com/scanny/python-pptx

Agent hiện tại đã sử dụng `python-pptx`.

Nên tiếp tục dùng cho:

- Orchestration phía Python
- Đọc metadata PPTX
- Structural audit
- Một số slide hoặc table đơn giản
- Compatibility với pipeline hiện tại

Tuy nhiên, khi số lượng custom visual tăng mạnh, PptxGenJS thường thuận tiện hơn cho renderer.

Không nhất thiết phải bỏ `python-pptx`. Có thể giữ Python làm agent và chuyển riêng phần rendering sang Node.js.

---

## 3. PowerPoint MCP

### 3.1. ppt-mcp

Repository:

- https://github.com/ykuwai/ppt-mcp

Repo này điều khiển PowerPoint đang chạy thông qua Windows COM automation.

Có thể sử dụng để:

- Chọn slide
- Thêm hoặc xóa shape
- Sửa text
- Di chuyển và resize shape
- Tạo tables và charts
- Thêm animation
- Thao tác SmartArt
- Căn chỉnh các phần tử
- Chỉnh slide trực tiếp trong PowerPoint

Phù hợp với bước:

```text
Code-first deck generation
          ↓
Open deck in Microsoft PowerPoint
          ↓
MCP final polish
```

Không nên dùng theo cách:

```text
LLM gọi MCP để đặt từng rectangle, line và textbox cho toàn bộ deck
```

Lý do:

- Cần Windows
- Cần cài Microsoft PowerPoint
- Khó scale thành backend
- Có thể cần quá nhiều tool calls
- Dễ chậm và không ổn định khi sinh 20–30 slide

---

### 3.2. Office-PowerPoint-MCP-Server

Repository:

- https://github.com/GongRzhe/Office-PowerPoint-MCP-Server

Repo này cung cấp các MCP tools dựa trên `python-pptx`.

Có thể tham khảo:

- MCP tool schema
- Slide management
- Template operations
- Mapping tool action sang `python-pptx`

Tuy nhiên, không nên phụ thuộc trực tiếp nếu repository không còn được duy trì tích cực.

---

## 4. PowerPoint Office.js API

Tài liệu chính thức:

- https://learn.microsoft.com/en-us/office/dev/add-ins/powerpoint/

Office.js phù hợp khi muốn phát triển một PowerPoint Add-in hoàn chỉnh.

Ví dụ giao diện:

```text
PowerPoint Add-in Sidebar

[Generate this slide]
[Improve visual]
[Convert table to chart]
[Apply BnK style]
[Fix spacing]
[Regenerate selected shapes]
```

Office.js có thể tương tác với:

- Presentation
- Slides
- Shapes
- Text
- Tables
- Layouts
- Slide masters

Ví dụ:

```ts
await PowerPoint.run(async (context) => {
  const slide = context.presentation
    .getSelectedSlides()
    .getItemAt(0);

  const card = slide.shapes.addGeometricShape(
    PowerPoint.GeometricShapeType.roundRectangle
  );

  card.left = 80;
  card.top = 120;
  card.width = 240;
  card.height = 110;

  card.fill.setSolidColor("#FFFFFF");
  card.lineFormat.color = "#D9E5EA";

  card.textFrame.textRange.text = "Document Intelligence";
  card.textFrame.textRange.font.bold = true;

  await context.sync();
});
```

Office.js nên là hướng phát triển sản phẩm lâu dài, không nhất thiết là bước đầu tiên.

---

## 5. VisualSpec làm trung gian

Python agent không nên gửi lệnh đặt từng shape.

Thay vào đó, agent xuất ra một semantic visual specification.

```python
from typing import Any, Literal
from pydantic import BaseModel, Field


class VisualSpec(BaseModel):
    type: Literal[
        "hero_message",
        "metric_cards",
        "three_pillars",
        "problem_impact_solution",
        "process_flow",
        "before_after",
        "feature_grid",
        "architecture_overview",
        "architecture_zoom",
        "timeline",
        "gantt",
        "risk_matrix",
        "comparison",
        "pricing_summary",
        "donut_chart",
        "bar_chart",
        "table",
    ]

    headline: str
    takeaway: str = ""

    items: list[dict[str, Any]] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)

    density: Literal["low", "medium", "high"] = "medium"
    emphasis_index: int | None = None
    icon_queries: list[str] = Field(default_factory=list)

    source_refs: list[str] = Field(default_factory=list)
```

Ví dụ:

```json
{
  "type": "problem_impact_solution",
  "headline": "Finance automation without replacing the core ERP",
  "takeaway": "BnK orchestrates documents, approvals and integrations around SAP or Oracle.",
  "items": [
    {
      "role": "problem",
      "title": "Fragmented Operations",
      "description": "Documents and finance activities span multiple channels and systems."
    },
    {
      "role": "impact",
      "title": "Slow and Risky",
      "description": "Manual matching, reconciliation and approvals increase delay and error exposure."
    },
    {
      "role": "solution",
      "title": "Unified Automation",
      "description": "IDP, orchestration and exception handling automate processes end-to-end."
    }
  ]
}
```

Renderer chỉ cần map `type` sang đúng hàm.

```ts
const renderer = VISUAL_RENDERERS[slideSpec.type];

if (!renderer) {
  throw new Error(`Unsupported visual type: ${slideSpec.type}`);
}

renderer({
  pptx,
  slideSpec,
  theme,
  assets,
});
```

---

## 6. Giao tiếp Python Agent và Node Renderer

Python ghi `deck_spec.json`:

```json
{
  "theme": "bnk-modern",
  "slides": [
    {
      "id": "executive-summary",
      "type": "problem_impact_solution",
      "title": "Automate finance without replacing the ERP",
      "items": [
        {
          "title": "Fragmented Inputs",
          "description": "Finance data enters through disconnected channels."
        },
        {
          "title": "Controlled Automation",
          "description": "IDP and orchestration process transactions consistently."
        },
        {
          "title": "Business Outcomes",
          "description": "Faster close, fewer errors and traceable approvals."
        }
      ]
    }
  ]
}
```

Python gọi Node renderer:

```python
import json
import subprocess
from pathlib import Path


def render_pptx(deck_spec: dict, output_path: Path) -> None:
    spec_path = output_path.with_suffix(".json")

    spec_path.write_text(
        json.dumps(
            deck_spec,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "node",
            "ppt-renderer/dist/cli.js",
            "--spec",
            str(spec_path),
            "--output",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"PPT renderer failed:\n"
            f"{result.stderr or result.stdout}"
        )
```

---

## 7. Có nên viết MCP riêng không?

Có, nhưng nên expose tools ở mức semantic.

Không nên expose các low-level tools như:

```text
add_rectangle
add_textbox
move_shape
set_font
add_line
```

Các tool nên là:

```text
create_deck
render_slide
replace_slide
convert_slide_visual
apply_theme
audit_deck
fix_slide
open_deck
```

Ví dụ tool schema:

```json
{
  "name": "render_slide",
  "description": "Render or replace one slide from a semantic VisualSpec.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "deck_path": {
        "type": "string"
      },
      "slide_id": {
        "type": "string"
      },
      "visual_spec": {
        "type": "object"
      }
    },
    "required": [
      "deck_path",
      "slide_id",
      "visual_spec"
    ]
  }
}
```

Lợi ích:

```text
Một LLM tool call cho một slide
```

thay vì:

```text
30–100 LLM tool calls để đặt từng shape
```

---

## 8. Code-first visual library nên có

### Nhóm P0

- Hero message
- Metric cards
- Three pillars
- Problem–Impact–Solution
- Feature grid
- Horizontal process flow
- Architecture overview
- Architecture zoom
- Timeline
- Gantt
- Pricing summary
- Risk matrix
- Before/after

### Nhóm P1

- Capability map
- Circular lifecycle
- Stakeholder ecosystem
- Data journey
- Compliance shield
- Comparison matrix
- Case study
- Geographic deployment
- Roadmap staircase
- Native bar chart
- Native donut chart

Chỉ cần khoảng 15–20 visual archetypes tốt là có thể tạo rất nhiều deck khác nhau.

---

## 9. Folder structure đề xuất

```text
backend/
  domain/
    deck/
      visual_spec.py
      visual_selector.py
      content_compressor.py
      slide_splitter.py
      visual_budget.py

ppt-renderer/
  src/
    cli.ts
    renderer.ts

    theme/
      tokens.ts
      bnk-modern.ts

    layouts/
      master-layouts.ts
      template-loader.ts

    renderers/
      base.ts
      hero.ts
      cards.ts
      metrics.ts
      process.ts
      architecture.ts
      timeline.ts
      charts.ts
      pricing.ts
      risks.ts
      tables.ts

    assets/
      icon-registry.ts
      svg-builder.ts
      chart-builder.ts

    quality/
      overlap-audit.ts
      density-audit.ts
      alignment-audit.ts
```

---

## 10. Thứ tự triển khai

### Sprint 1 — Renderer foundation

- Tạo `VisualSpec`
- Tạo Node renderer
- Cấu hình PptxGenJS
- Load template bằng pptx-automizer
- Tạo theme tokens
- Tạo 6 visual renderers:
  - Metric cards
  - Three pillars
  - Problem–Impact–Solution
  - Process flow
  - Pricing summary
  - Risk matrix

### Sprint 2 — Architecture và charts

- Architecture overview
- Architecture zoom
- Layered tech stack
- Native bar chart
- Native donut chart
- Timeline và Gantt
- Feature grid

### Sprint 3 — Visual QA

- Structural PPTX audit
- Render slide thành PNG
- Vision critic
- Per-slide regeneration
- Deck-wide diversity check
- Final patch workflow

### Sprint 4 — Optional MCP

- Wrap semantic renderer thành MCP
- `render_slide`
- `replace_slide`
- `audit_deck`
- `fix_slide`
- Tích hợp PowerPoint COM hoặc Office.js nếu cần live editing

---

## 11. Stack khuyến nghị cuối cùng

```text
Python Deep Agent
+ Pydantic VisualSpec
+ PptxGenJS
+ pptx-automizer
+ Code-generated SVG
+ Native PowerPoint charts and shapes
+ Existing icon resolver
+ PNG visual QA
+ Optional PowerPoint MCP
```

Quyết định quan trọng nhất:

```text
Không dùng MCP để đặt từng shape
```

Thay vào đó:

```text
LLM tạo semantic VisualSpec
           ↓
Code renderer tạo toàn bộ visual
           ↓
MCP chỉ chỉnh sửa hoặc polish
```

Đây là hướng cân bằng tốt nhất giữa:

- Chất lượng visual
- Tính ổn định
- Khả năng chỉnh sửa PowerPoint
- Tốc độ generation
- Khả năng scale
- Dễ kiểm thử
- Dễ tích hợp vào codebase agent hiện tại
