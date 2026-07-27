# Nâng cấp `diagram_code_agent` lên chất lượng review-grade

> ⚠ **Đọc `REVIEW-CODEBASE-FIT.md` (cùng thư mục) TRƯỚC.** Bản phân tích dưới đây
> viết ngoài, chưa đối chiếu codebase thật — có 6 điểm sai/lỗi thời, trong đó
> một điểm (con số orphan/density đo trên `.drawio` thay vì spec) nếu implement
> y nguyên sẽ tạo vòng REVISE vô tận. Việc thi công thật theo bản đã hiệu chỉnh
> trong `plans/replicated-riding-thimble.md`, không phải 9 patch dưới đây nguyên văn.

**Repo:** `luongphambao/diagram_code_agent` · 52.389 LOC Python · 9 skill · validator 1.633 dòng · router libavoid-style
**Ngày phân tích:** 26/07/2026

Kết luận ngắn: **repo của bạn không thiếu code — nó thiếu 3 invariant và 1 phép đo.** Kiến trúc pipeline đã tốt hơn phần lớn diagram agent tôi từng thấy (có measure/place engine riêng, có A* router với nudge, có validator 1.6k dòng, có eval harness, có critic loop). Vấn đề nằm ở chỗ khác, và nó rất cụ thể.

---

## Phần 1 — Đo trên chính output của repo

Tôi parse 9 file `.drawio` trong `example/` + `new/` và tính bằng font metrics thật (Liberation Sans, cùng metric với Helvetica mà drawio dùng):

| File | Card | Edge | Edge/Card | Card không có edge | Edge không nhãn | Chữ bị wrap lại | Tràn chiều cao | Icon AWS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `ai-financial-analysis-reference-check` | 50 | 35 | 0.70 | 16 | 19 | 20 | 6 | 7 |
| `azure-browser-copilot-rpa-orchestration` | 47 | 37 | 0.79 | 20 | 11 | 23 | 5 | 3 |
| `azure-multiagent-browser-automation` | 13 | 23 | 1.77 | 3 | 0 | 4 | 4 | 0 |
| `bctc-credit-recommendation-multiagent` | 37 | 28 | 0.76 | 10 | 23 | 22 | 8 | 7 |
| `document-migration-reference-architecture` | 50 | 22 | 0.44 | 25 | 11 | 23 | 11 | 11 |
| `driver-operations-fms-platform` | 25 | 15 | 0.60 | 10 | 8 | 10 | 4 | 3 |
| `gcp-idp-rpa-finance-automation` | 51 | 17 | **0.33** | **29** | 6 | 21 | 17 | 7 |
| `odoo-service-booking-mvp` | 14 | 30 | 2.14 | 2 | 0 | 4 | 3 | 0 |
| `diagram(1)` | 13 | 14 | 1.08 | 3 | 0 | 5 | 5 | 0 |
| **TỔNG** | **300** | **221** | **0.74** | **118 = 39%** | **78 = 35%** | **132 = 44%** | **63 = 21%** | **38** |

Đọc bảng này:

- **39% card không có bất kỳ edge nào.** Đó chính xác là lỗi tôi tìm thấy trong file bạn upload — và nó **không phải trường hợp cá biệt**, nó là đặc tính của pipeline. `gcp-idp-rpa-finance-automation` có 51 card mà chỉ 17 edge: hơn nửa canvas là danh mục component, không phải kiến trúc.
- **Edge/Card = 0.74.** Một architecture diagram lành mạnh nằm khoảng **1.3–2.0**. Dưới 1.0 nghĩa là diagram đang *liệt kê* chứ không *mô tả quan hệ*. (Bản HLAS tôi làm: 45 card / 65 edge = 1.44.)
- **44% card bị drawio wrap lại** so với số dòng mà engine đã tính, và **21% tràn chiều cao** — chữ bị cắt hoặc đè viền. Đây là lỗi *hệ thống*, xem Phần 2.
- **35% edge không có nhãn.** Cộng với các nhãn placeholder kiểu `(×2 flows)` / `(all layers)` mà validator không hề chặn.
- **38 icon AWS** rải trong 6/9 file, kể cả file GCP và file on-prem.

---

## Phần 2 — Ba lỗi gốc rễ (không phải lỗi thẩm mỹ)

### 🔴 Lỗi #1 — Không bao giờ đo chữ. Toàn bộ hình học dựng trên hằng số đoán.

```python
# backend/src/prettygraph/native/layout_engine.py
:42   "w": min(260, max(120, round(max_len * 6.6 + 28))),
:212  n["w"] = max(96, min(200, (len(n.get("label") or "")) * 7 + 24))
:223  text_w = max(len(title) * 7.2, len(sub) * 5.8)
:236  title_lines = max(1, math.ceil(len(title) * 7.2 / avail))
:263  n["w"] = max(n["w"], (len(n["label"]) * 6.6) // 1 + n["pad"] * 2)
```

`len(s) * 6.6` giả định mọi ký tự rộng bằng nhau. Thực tế ở Helvetica 10.5px: `i` = 2.3px, `W` = 10.2px — **sai số 4.4×**. Chuỗi `"Illinois"` và `"WWWWWWWW"` cùng 8 ký tự nhưng rộng 30px vs 82px.

Điều làm lỗi này *nguy hiểm* thay vì chỉ *xấu*: **validator dùng đúng cùng hằng số sai đó.**

```python
# backend/src/prettygraph/native/refined.py:175
"""mirrors validate_drawio's edge-label estimate (6.6px/char × 14px)."""
:176  w = max(30.0, len(label) * 6.6)

# backend/src/domain/validation/validate_drawio.py:1198
lw = len(label) * 6.6
```

Nghĩa là: engine tính sai → router né tránh những hình chữ nhật **sai kích thước** → `_solve_label_offset` tối ưu nhãn dựa trên **hộp sai** → validator tính crossing/overlap trên **cùng con số sai** → **metric xác nhận cái bug thay vì bắt nó**. Điểm `arrow_clarity_score` 90 vẫn có thể ra diagram chữ tràn viền. Đây là lý do 44% card bị wrap mà không có gate nào kêu.

Trớ trêu là **repo đã có font metrics thật rồi**, chỉ ở sai chỗ: `slide.py:22-36` load `PIL.ImageFont` — nhưng `layout_engine.py` không bao giờ gọi tới.

### 🔴 Lỗi #2 — Không có invariant về tính liên kết. Validator chỉ kiểm hình học, không kiểm ngữ nghĩa.

Validator 1.633 dòng của bạn kiểm **rất nhiều** thứ: duplicate id, dangling parent, sibling overlap, edge xuyên node (`:799`), long-edge ratio, icon coverage, page fill, aspect ratio, AWS nesting level, subnet/AZ chain… Nhưng **không có phép tính bậc (degree) của node** ở đâu cả. Duy nhất preset BPMN có orphan check (`:867-877`).

Và `critic/SKILL.md` bị *cấm* xét đúng/sai kiến trúc — nó chỉ nói "no floating **box**" (nghĩa là box phải nằm trong cluster), chứ không phải "box phải có edge". Một node lơ lửng trong cluster đẹp đẽ sẽ pass mọi gate.

Hệ quả trực tiếp: 39% orphan rate.

### 🟠 Lỗi #3 — Design token vô hình với LLM; hai bộ từ vựng edge đánh nhau.

Các con số thật nằm ở `refined_theme.py` (`TYPE_SCALE = {title:30, card:10.5, note:9.5, …}`, `ZONE_HUES`, `EDGE_CLASSES`) — nhưng **skill text không hề có một con số nào**. LLM chỉ được cho tên semantic (`kind=compute`, `flow=data`). Nó không thể lý giải hay tự kiểm tra về khoảng cách, cỡ chữ, contrast.

Đồng thời tồn tại **hai từ vựng màu edge khác nhau**:
- `refined_theme.EDGE_CLASSES`: `data #1D4ED8`, `execution #536174`, `outcome #15803D`, `monitoring dashed`…
- `prompts/_blocks.py:446-457` (nhánh raw-graphviz): `request/UI #2E5BBA`, `AI/LLM #2E8B57`, `data/query #7A7A7A`, `result #1F3A93`

Rơi vào nhánh nào thì legend contract vỡ ngầm. Cộng thêm: **skill bị duplicate và đã drift** — `backend/skills/pro-style/SKILL.md` (32.565 B) ≠ `backend/skills/drawer/pro-style/SKILL.md` (33.393 B). Load bản nào thì hành vi khác bản đó → không deterministic.

### Và điều khiến diagram "không pro" nhất

Repo bạn **đã sinh ra** trade-off scoring, `nfr_mapping`, ADR pack, evidence store, capacity sizing, risk per layer. Nhưng tất cả nằm trong JSON/report. **Trang vẽ chỉ có title, subtitle, zone số và legend edge.** Không có NFR panel, không có interface register, không có assumptions, không có document control.

Đó chính là khác biệt lớn nhất giữa bản HLAS tôi làm và output hiện tại của repo — không phải màu sắc, mà là **diagram có mang theo bằng chứng để phản biện được hay không.**

---

## Phần 3 — 9 patch, xếp theo đòn bẩy

### Patch 1 · Đo chữ thật (đòn bẩy cao nhất, ~120 dòng)

Tạo `backend/src/prettygraph/text_metrics.py`:

```python
"""Font metrics thật cho layout engine. Phải khớp font mà drawio render."""
from __future__ import annotations
import functools, os
from PIL import ImageFont

# drawio mặc định fontFamily=Helvetica; Liberation Sans metric-compatible với Helvetica/Arial
_CANDIDATES = {
    False: ["/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    True:  ["/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
}
LINE_HEIGHT = 1.2   # mxConstants.LINE_HEIGHT — đừng đổi, drawio dùng đúng số này

@functools.lru_cache(maxsize=256)
def _font(size_q: int, bold: bool):
    for p in _CANDIDATES[bold]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size_q)          # size_q = size*4
    return ImageFont.load_default()

@functools.lru_cache(maxsize=20000)
def text_width(s: str, size: float, bold: bool = False) -> float:
    """Bề rộng px. Đo ở 4× rồi chia để có độ chính xác sub-pixel."""
    return _font(int(round(size * 4)), bold).getlength(s) / 4.0

def wrap(s: str, max_w: float, size: float, bold: bool = False) -> list[str]:
    """Greedy wrap giống drawio. Tôn trọng \\n có sẵn."""
    out = []
    for para in str(s).split("\n"):
        cur = ""
        for w in para.split():
            cand = f"{cur} {w}".strip()
            if text_width(cand, size, bold) <= max_w or not cur:
                cur = cand
            else:
                out.append(cur); cur = w
        out.append(cur)
    return out

def block_height(s: str, max_w: float, size: float, bold: bool = False) -> float:
    return len(wrap(s, max_w, size, bold)) * size * LINE_HEIGHT

def fits(s: str, box_w: float, box_h: float, size: float, bold: bool = False,
         pad_x: float = 0, pad_y: float = 0) -> bool:
    return block_height(s, box_w - pad_x, size, bold) <= box_h - pad_y
```

Rồi thay 6 chỗ trong `layout_engine.py`:

```python
from ..text_metrics import text_width, wrap, block_height, LINE_HEIGHT

# :42  _auto_box
w = min(260, max(120, max(text_width(l, size) for l in lines) + 28))
h = max(44, block_height("\n".join(lines), w - 28, size) + 26)

# :212 _m_icon
n["w"] = max(96, min(200, text_width(n.get("label") or "", size) + 24))

# :223-237 _m_card  ← chỗ quan trọng nhất
text_w = max(text_width(title, title_size, bold=True), text_width(sub, sub_size))
title_lines = len(wrap(title, avail, title_size, bold=True)) if title else 0
sub_lines   = len(wrap(sub,   avail, sub_size))               if sub   else 0
```

Và **cùng lúc** sửa validator + refined để hết đồng thuận với bug:

```python
# validate_drawio.py:1198  và  refined.py:176
from ...prettygraph.text_metrics import text_width
lw = max(30.0, text_width(label, edge_font_size) + 8)
```

> Sửa Patch 1 mà không sửa validator là tự bắn chân: metric sẽ bắt đầu báo lỗi ở những chỗ **đúng**.

**Kỳ vọng:** re-wrap 44% → gần 0%; tràn chiều cao 21% → 0%; và các con số crossing/overlap của validator bắt đầu có nghĩa.

### Patch 2 · Bốn invariant HARD FAIL về ngữ nghĩa (~80 dòng)

Thêm vào `validate_drawio.py`, đưa vào bucket `errors` (không phải advice):

```python
_WEAK_LABEL = re.compile(
    r"^(data|calls?|uses?|flow[s]?|sync|api|request|response|link|connect(s|ion)?|"
    r"n/?a|tbd|todo|misc|other|various)$", re.I)
_PLACEHOLDER = re.compile(
    r"\(\s*(all layers|×?\s*\d+\s*flows?|x\d+\s*flows?|multiple|various|etc\.?)\s*\)|"
    r"\ball layers\b|\bmultiple flows\b", re.I)

def audit_semantics(nodes, edges, spec=None):
    """Bốn invariant. Vi phạm = REVISE, không phải advice."""
    errs = []

    # I1 — không có node cô lập
    deg = {}
    for e in edges:
        for k in ("source", "target"):
            if e.get(k): deg[e[k]] = deg.get(e[k], 0) + 1
    leaves = [n for n in nodes if n.get("is_leaf") and not n.get("is_annotation")]
    orphans = [n["id"] for n in leaves if deg.get(n["id"], 0) == 0]
    if orphans:
        errs.append(f"I1 orphan: {len(orphans)}/{len(leaves)} component không có edge nào "
                    f"({', '.join(orphans[:6])}). Mỗi component phải có ≥1 quan hệ, "
                    f"hoặc bị xoá, hoặc gộp vào một component khác.")

    # I2 — mật độ quan hệ
    if leaves:
        ratio = len(edges) / len(leaves)
        if ratio < 1.0:
            errs.append(f"I2 density: edge/component = {ratio:.2f} (< 1.00). Đây là danh mục "
                        f"component, chưa phải kiến trúc. Bổ sung quan hệ hoặc giảm số component.")

    # I3 — chất lượng nhãn edge trên primary path
    bad = [e["id"] for e in edges if e.get("primary") and (
           not (e.get("label") or "").strip()
           or _WEAK_LABEL.match((e.get("label") or "").strip())
           or _PLACEHOLDER.search(e.get("label") or ""))]
    if bad:
        errs.append(f"I3 label: {len(bad)} edge chính có nhãn rỗng/vô nghĩa/placeholder "
                    f"({', '.join(bad[:6])}). Nhãn phải là hợp đồng: protocol + auth "
                    f"(vd 'HTTPS · mTLS', 'AMQP · at-least-once', 'TDS 1.4').")

    # I4 — một họ icon cho mỗi diagram
    fams = {}
    for n in nodes:
        m = re.search(r"mxgraph\.(aws4|azure\w*|gcp\w*|kubernetes|veeam|cisco\w*)\.", n.get("style",""))
        if m: fams.setdefault(m.group(1).split("_")[0], []).append(n["id"])
    if len(fams) > 1:
        errs.append(f"I4 icon family: trộn {sorted(fams)} trong một diagram. "
                    f"Chọn một họ theo hosting thật, hoặc dùng shape trung tính.")
    if spec and str(spec.get("hosting","")).lower() in {"onprem","on-premises","on-prem"} \
       and "aws4" in fams:
        errs.append(f"I4 icon family: dùng {len(fams['aws4'])} icon AWS cho một kiến trúc "
                    f"on-premises. Đây là mâu thuẫn tự phá uy tín trước review board.")
    return errs
```

Nối vào verdict:

```python
# trong critic loop / gate
sem = audit_semantics(nodes, edges, spec)
if sem:
    result["errors"].extend(sem)
    result["ok"] = False          # I1–I4 luôn ép REVISE
```

Và sửa `critic/SKILL.md`: `"**EVERY node belongs to a cluster**"` → thêm dòng `"**EVERY leaf node has at least one edge.** A component with no relationship is not architecture — delete it, merge it, or connect it. This is a functional finding, severity high."`

### Patch 3 · Bắt buộc anchor exit/entry (~20 dòng, nhưng chữa một lỗ ngầm nghiêm trọng)

Router **có** phát ra `exitX/entryX` (`router.py:809-810`) nhưng **chỉ khi** `d.contract == "bake"`. Khi thiếu, validator giả định 0.5:

```python
# validate_drawio.py:1107
fx if fx is not None else 0.5
```

→ nó tính crossing trên **một tuyến mà drawio sẽ không vẽ**. Người dùng mở file ra thấy đường đi khác hoàn toàn so với PNG preview.

```python
def audit_anchors(edges):
    loose = [e["id"] for e in edges
             if e.get("waypoints") and not re.search(r"exitX=", e.get("style",""))]
    if loose:
        return [f"I5 anchor: {len(loose)} edge có waypoint nhưng không có exitX/entryX. "
                f"drawio sẽ tự re-route và bỏ layout đã tính. "
                f"Luôn phát cả anchor khi đã bake waypoint."]
    return []
```

Trong router, luôn bake anchor bất kể contract — tính fraction từ điểm đầu/cuối so với bbox của node:

```python
def anchor_frac(box, pt):
    x, y, w, h = box
    return (round(min(1, max(0, (pt[0]-x)/w)), 4),
            round(min(1, max(0, (pt[1]-y)/h)), 4))
```

Thêm `exitPerimeter=0;entryPerimeter=0;` để drawio không bù lại vị trí.

### Patch 4 · Một từ vựng edge duy nhất = hợp đồng, không phải "flow purpose"

Taxonomy hiện tại (`data | control | serving | registry | monitoring | security`) là *mục đích*, không phải *hợp đồng*. Nó không phân biệt được đồng bộ/bất đồng bộ, nội bộ/bên thứ ba — hai thứ mà mọi security reviewer sẽ hỏi đầu tiên.

Thay bằng 7 class, đặt ở **một chỗ duy nhất** (`refined_theme.py`) và **inject vào prompt**:

```python
EDGE_CONTRACTS = {
    # class:      (color,     w,   dash,        legend label,                       ràng buộc)
    "sync":      ("#1B4FBF", 1.7, None,        "Synchronous request / response",
                  "HTTPS + mTLS · timeout có giới hạn · circuit breaker"),
    "async":     ("#6127B8", 1.7, (7, 3.5),    "Asynchronous event / job",
                  "at-least-once · consumer idempotent · retry + DLQ"),
    "data":      ("#0A6B45", 1.5, None,        "Data access / persistence",
                  "mã hoá đường truyền · service account least-privilege"),
    "control":   ("#A9640A", 1.4, (2.6, 2.6),  "Identity / secrets / config plane",
                  "KHÔNG mang business data"),
    "telemetry": ("#5F6B7A", 1.25, (1.2, 2.6), "Telemetry / audit evidence",
                  "append-only · một chiều"),
    "external":  ("#B4342A", 1.7, None,        "Cross trust-boundary (third party)",
                  "egress allowlist · payload có signature · lưu evidence"),
    "batch":     ("#0A6C82", 1.5, (10, 4),     "Scheduled batch / reconciliation",
                  "có checkpoint · có break report"),
}
```

Ba việc kèm theo:
1. **Xoá bộ hex ở `_blocks.py:446-457`**, cho nhánh raw-graphviz dùng cùng dict này.
2. Sinh legend **tự động từ tập class thực dùng** — không để LLM tự viết legend. Legend không thể lệch nếu nó là hàm của dữ liệu.
3. Gate: `edge.contract` là **required field**. Không có contract = không vẽ được.

### Patch 5 · Đưa design token vào prompt

LLM đang bị yêu cầu "làm cho đẹp" mà không được cho một con số nào. Sinh block token từ code, chèn vào system prompt:

```python
# backend/src/prompts/_blocks.py
def design_token_block() -> str:
    from ..prettygraph.refined_theme import TYPE_SCALE, ZONE_HUES, EDGE_CONTRACTS
    lines = ["## Design tokens (KHÔNG được tự bịa giá trị khác)",
             "Type scale (px): " + " · ".join(f"{k}={v}" for k, v in TYPE_SCALE.items()),
             "Zone accents: " + " · ".join(f"{k}={v[2]}" for k, v in ZONE_HUES.items()),
             "Edge contracts: " + " · ".join(EDGE_CONTRACTS),
             "Radius: card=9 zone=12 pill=7 · Stroke: card=1.1 zone=1.2 boundary=1.6",
             "Grid: 4px. Mọi x/y/w/h phải là bội số của 4.",
             "Bạn KHÔNG chọn toạ độ. Bạn khai báo cấu trúc; engine tính hình học."]
    return "\n".join(lines)
```

Và **hợp nhất skill bị duplicate**: giữ một bản, bản còn lại thành symlink. Skill drift = hành vi không deterministic, không debug được.

### Patch 6 · Đa mức trừu tượng thay cho "density knob"

Hiện tại `standard 12-18 / detailed 32-48 / poster 25-45` là **cùng một view ở các độ mịn khác nhau** — nên diagram 48 node vừa quá rối cho lãnh đạo vừa quá thô cho dev.

Thay bằng planner sinh **một bộ view**:

```python
VIEWS = {
    "context":   dict(level=1, nodes=(6, 12),  shows="actors + system boundary + externals",
                      audience="exec / board"),
    "container": dict(level=2, nodes=(25, 50), shows="deployable units, tech stack, zones",
                      audience="architecture review board"),
    "flow":      dict(level=2, nodes=(10, 18), shows="numbered steps in swimlanes, decision gates",
                      audience="business + risk"),
    "deployment":dict(level=3, nodes=(0, 0),   shows="node inventory, interface register, matrices",
                      audience="security / ops / audit"),
}
```

Ràng buộc nhất quán giữa các view (gate được):
- Mọi node ở `context` phải là ancestor của ≥1 node ở `container`.
- Mọi bước ở `flow` phải reference `node_ids` tồn tại trong `container`.
- Mọi edge `container` phải có một dòng trong interface register của `deployment`.

Đây là thứ biến 4 hình rời rạc thành **một bộ tài liệu**.

### Patch 7 · Đưa evidence lên trang vẽ

Bạn đã có dữ liệu. Chỉ cần renderer. Thêm các block kind vào layout engine:

```python
EVIDENCE_BLOCKS = {
    "nfr_panel":      "từ spec.nfr_mapping → bảng NFR | target | mechanism | node_ids",
    "adr_list":       "từ export_adr_pack() → ADR-nn | decision | rationale",
    "interface_reg":  "từ chính edges → ID | interface | protocol+auth | dir | SLA | owner",
    "assumptions":    "từ spec.assumptions → bullet, có badge severity",
    "risk_panel":     "từ spec.risks → H/M/L chip + mô tả",
    "doc_control":    "version | date | author | reviewers | approver | status | classification",
    "legend":         "sinh từ tập edge contract thực dùng",
    "kpi_row":        "từ spec.outcomes → 3-4 tile số lớn",
}
```

Layout: dành **dải dưới ~20% chiều cao trang** cho evidence panel, phần trên là diagram. Interface register là món quan trọng nhất — nó cho phép nhãn edge ngắn gọn mà thông tin vẫn đầy đủ và truy được.

Gate mới: `security_level in {high, critical}` → **bắt buộc** có `doc_control` + `assumptions` + `interface_reg`.

### Patch 8 · Preview sinh từ chính geometry model (bỏ phụ thuộc mạng)

Hiện tại PNG đi qua drawio CLI (cần xvfb + Electron) hoặc Playwright → `viewer.diagrams.net` (**cần outbound HTTPS**). Hai vấn đề: môi trường client/CI thường chặn, và preview đến từ renderer khác với model → không phát hiện được lỗi của model.

Thêm một emitter SVG thứ hai từ **cùng element list** (đây chính là cách tôi làm bản HLAS — nó bảo đảm PNG và drawio khớp nhau và chạy offline):

```python
def to_svg(page) -> str:
    """Cùng model → SVG. Dùng chung text_metrics nên chữ nằm đúng chỗ."""
    ...   # rect / text / image / polyline + arrowhead

def render_png(page, path, scale=2):
    """SVG → PNG qua Chromium local (Playwright đã có sẵn), không cần mạng."""
    html = f"<!doctype html><style>body{{margin:0}}</style>{to_svg(page)}"
```

Hai lưu ý khi emit drawio mà tôi đã phải xử lý:

```python
# 1) drawio parse style bằng split(';') → dấu ';' trong data URI làm vỡ style.
#    PHẢI dùng convention của drawio: data:image/png,<base64>  (KHÔNG có ";base64")
uri = "data:image/png," + base64.b64encode(png_bytes).decode()

# 2) rounded rect: absoluteArcSize cho radius theo px thật, không theo %
style = f"rounded=1;absoluteArcSize=1;arcSize={radius*2:g};"
```

Nếu bạn dùng SVG glyph, rasterize sang PNG trước khi nhúng vào drawio (`cairosvg`, 96px là đủ).

### Patch 9 · Critic được phép nói kiến trúc sai

Hiện `critic/SKILL.md` bị *cấm* "scope-policing the blueprint" và mọi finding thẩm mỹ "NEVER force REVISE". Kết quả: một thiết kế **đẹp nhưng sai** luôn pass. Thêm một critic thứ hai, tách biệt:

```markdown
## architecture-critic (chạy song song với visual critic)

Bạn KHÔNG xét thẩm mỹ. Bạn xét thiết kế có đúng không. Với mỗi phát hiện: đưa
ra kịch bản lỗi cụ thể (input/state → hậu quả), không nói chung chung.

Bắt buộc kiểm:
1. Ingress path — có node nào nhận traffic internet mà không có authn/WAF phía trước?
2. Single point of failure — có tier stateful nào chỉ 1 instance mà không có failover?
3. Data in transit — có hop nào chở PII mà không ghi rõ mã hoá?
4. Trust boundary — mọi lời gọi ra bên thứ ba có đi qua một điểm egress được kiểm soát?
5. Blast radius — credential rò ở một zone thì lấy được gì ở zone khác?
6. Observability — mọi thay đổi trạng thái có sinh audit event không thể sửa?
7. Failure path — mỗi lời gọi đồng bộ ra ngoài có timeout + fallback? mỗi consumer có DLQ?
8. Reversibility — rule/model/schema đổi rồi rollback được không?

Verdict: bất kỳ phát hiện nào ở mục 1–4 → REVISE.
```

Cho hai critic chạy song song rồi hợp nhất verdict. Visual critic đảm bảo diagram *đọc được*; architecture critic đảm bảo nó *đúng*.

---

## Phần 4 — Thứ tự thực hiện (4 sprint)

| Sprint | Nội dung | Effort | Kết quả đo được |
|---|---|---|---|
| **1** | Patch 1 (text metrics, cả engine + validator) · Patch 2 (I1–I4) · hợp nhất skill duplicate | 3–4 ngày | re-wrap 44%→<3% · tràn 21%→0 · orphan 39%→0 |
| **2** | Patch 3 (anchor) · Patch 4 (edge contract + legend tự sinh) · Patch 8 (SVG emitter offline) | 4–5 ngày | preview khớp drawio 100% · legend không thể lệch · render không cần mạng |
| **3** | Patch 7 (evidence panel) · Patch 5 (token vào prompt) | 5–6 ngày | mọi diagram security_level cao đều có doc control + interface register |
| **4** | Patch 6 (multi-view) · Patch 9 (architecture critic) | 6–8 ngày | một brief → bộ 4 view nhất quán, đã qua review đúng/sai |

Làm Sprint 1 trước và đừng nhảy cóc: Patch 1 phải xong thì các metric hiện có mới bắt đầu nói thật, và mọi patch sau đều đứng trên nó.

---

## Phần 5 — Definition of done mới (gate được, không cảm tính)

Thêm vào `evals/diagram_quality/` — fail thì không xuất file:

```python
GATES = {
    # liên kết & ngữ nghĩa
    "orphan_leaf_nodes":            ("== 0",     "hard"),
    "edge_per_leaf_ratio":          (">= 1.0",   "hard"),
    "primary_edges_with_contract":  ("== 100%",  "hard"),
    "weak_or_placeholder_labels":   ("== 0",     "hard"),
    "icon_families_per_page":       ("<= 1",     "hard"),
    # tính toàn vẹn hình học (giờ mới đo được thật)
    "text_rewrapped_cards":         ("<= 2%",    "hard"),
    "vertical_overflow_cards":      ("== 0",     "hard"),
    "edges_missing_anchors":        ("== 0",     "hard"),
    "edge_through_unrelated_node":  ("== 0",     "hard"),
    "leaf_node_overlaps":           ("== 0",     "hard"),
    "label_overlap_area_px":        ("== 0",     "hard"),
    # mức độ hoàn chỉnh của tài liệu
    "legend_matches_used_classes":  ("== 100%",  "hard"),
    "has_doc_control":              ("true",     "hard nếu security_level cao"),
    "has_assumptions_panel":        ("true",     "hard nếu security_level cao"),
    "interface_register_coverage":  ("== 100%",  "hard nếu multi-view"),
    "nfr_to_node_traceability":     (">= 80%",   "warn"),
    # thẩm mỹ (không bao giờ ép REVISE)
    "content_aspect_ratio":         ("1.2 .. 2.2", "warn"),
    "page_fill":                    (">= 65%",   "warn"),
    "distinct_font_sizes":          ("<= 8",     "warn"),
    "crossings_per_edge":           ("<= 0.30",  "warn"),
}
```

Nguyên tắc đặt gate: **tính liên kết và tính toàn vẹn hình học là hard fail; thẩm mỹ là warn.** Diagram hơi rối nhưng đúng thì vẫn dùng được; diagram đẹp mà có 29 component lơ lửng thì không.

---

## Phụ lục — Bốn thứ tôi làm ở bản HLAS mà repo chưa có, xếp theo giá trị

1. **Hành lang routing dành riêng.** Trước khi đặt card, chốt trước vài cột x không bao giờ có card (tôi dùng `x=1138`). Mọi đường dài đi xuyên nhiều band đều dùng hành lang đó. Router A* của bạn *tìm* khe hở; bảo lưu hành lang *bảo đảm* có khe hở — khác nhau về bản chất ở diagram dày.
2. **Nhãn có halo trắng.** Mọi annotation vẽ kèm một rect trắng phía sau và **vẽ sau edge**. Không bao giờ có đường kẻ xuyên qua chữ. Rẻ, hiệu quả ngay.
3. **Đường bus cho quan hệ cross-cutting.** Vault → mọi service là 40 mũi tên rối. Vẽ **1 đường ray dọc có nhãn** kèm dot ở mỗi band. Trung thực hơn (nó *là* một plane) và sạch hơn.
4. **Boundary crossing là một dải, không phải một đường.** Chỗ mọi lời gọi ra ngoài cắt qua trust boundary, vẽ một dải ngang ghi tên các control (`DMZ egress proxy · FQDN allowlist · TLS inspection · signed evidence`), với marker ổ khoá tại từng điểm cắt. Security reviewer đọc một lần là hiểu.

Cả 4 đều là ~50–100 dòng trong layout engine của bạn, và đều nằm ở tầng bạn *đã* kiểm soát.

---

## Phần 6 — Kết quả chạy thật của bộ gate (`semantic_gates.py`)

Tôi viết xong module và chạy nó ở chế độ standalone trên chính output của repo:

```
$ python semantic_gates.py example/*.drawio new/*.drawio
→ 9/9 file: VERDICT: REVISE
```

Một số phát hiện tiêu biểu, nguyên văn:

```
=== gcp-idp-rpa-finance-automation.drawio
    51 leaf components · 17 edges · ratio 0.33
HARD I1-orphan:      16/38 components have no edge
HARD I2-density:     edge/component = 0.45 — đây là danh mục component, chưa phải kiến trúc
HARD I3-placeholder: 8 nhãn là placeholder tự sinh:
       'statements (all layers)'
       'extracted document (grouped) (×2 flows)'
       'workflow control (×5 flows)'
       'systems sync (×2 flows)'
       'governed APIs (×3 flows)'
HARD I6-overflow:    7 card có chữ cao hơn hộp → bị cắt hoặc tràn viền
HARD I6-rewrap:      21 card sẽ bị drawio wrap lại
```

Chú ý các nhãn placeholder: `(all layers)`, `(×N flows)`, `governed APIs`, `systems sync`. **Chính xác cùng bộ chuỗi tôi tìm thấy trong file `diagram 18.drawio` bạn upload sáng nay.** Nó xác nhận: lỗi không nằm ở một lần sinh không may — nó nằm ở template, và không có gate nào chặn.

### Và bộ gate cũng bắt lỗi trong file HLAS tôi giao cho bạn

Đây là phần đáng tin nhất của một cái gate: nó không thiên vị ai.

```
=== HLAS-Underwriting-Architecture-v2.drawio :: 2 · Container Architecture
    44 leaf components · 65 edges · ratio 1.48          ← mật độ tốt
HARD I1-orphan: 11/44 components have no edge  [ch0, ch1, ch2, ch3, ch4, egress, …]
HARD I5-anchor: 2 edges carry waypoints but no exitX/entryX
```

Hai phát hiện này **đúng, không phải false positive:**

1. **`ch0…ch4`** — 5 card channel bên trái tôi nối vào firewall bằng một "bus" hội tụ vẽ bằng `poly` (polyline tự do, không có `source`/`target`). Nhìn thì đúng, nhưng **về cấu trúc chúng là orphan**: kéo card trong drawio thì đường không đi theo. Sửa: đổi 5 polyline thành edge thật có source/target, giữ nguyên waypoint.
2. **`egress` (Outbound Egress Proxy)** — tôi đã có ý thức đánh đổi lúc dựng: card này không có edge nào, chỉ được nhắc trong dải trust-boundary. Gate nói đúng: hoặc nối nó (Integration Gateway → Egress Proxy), hoặc gộp nó vào card firewall.
3. **`I5-anchor`** — 2 đường ray cross-cutting (control plane / telemetry plane) là polyline tự do nên không có anchor. Ở đây là *chủ ý* (chúng là plane, không nối 2 node cụ thể) → đúng chỗ để đánh dấu `waiver` có lý do, chứ không phải nới lỏng gate.

Nói bạn rõ để bạn khỏi tin tôi quá: bản HLAS tốt hơn output hiện tại của repo về mật độ (1.48 vs 0.74) và về nhãn, nhưng nó **không sạch tuyệt đối** — và tôi chỉ biết điều đó *sau khi* có gate. Đó chính là lý do phải build gate chứ không dựa vào mắt.

Nếu bạn muốn, tôi patch 3 điểm trên trong file HLAS (khoảng 15 phút) và gửi lại v2.1.

### Một bài học về chỗ đặt gate

Chạy `semantic_gates.py` trên file `.drawio` là **triage** — adapter phải suy luận đâu là component, đâu là annotation, edge nào là primary, nên có nhiễu (nó báo `I3-unlabelled 69%` trên file HLAS, nhưng phần lớn đó là các hop ngắn trong cùng zone mà tôi *cố ý* không gắn nhãn).

Chỗ đúng để gate là **bên trong pipeline**, nơi bạn đã biết chắc:

```python
sem = audit(
    nodes,                       # có is_leaf, is_annotation, lines=[(text,size,bold)]
    edges,                       # có primary, contract, waypoints
    hosting=spec["hosting"],     # để bắt I4 icon mismatch
    legend_classes=legend_used,  # để bắt I7 legend lệch
)
if any(f.severity == "hard" for f in sem):
    return revise(sem)           # đưa nguyên văn finding vào prompt sửa
```

Ba field bạn cần bổ sung vào spec để gate hoạt động đúng (đều rẻ):
- `node.is_annotation` — legend, note, title, KPI tile không phải component.
- `edge.primary` — chỉ primary path bị soi nhãn; side-channel được phép trống.
- `node.lines = [(text, size, bold)]` — engine đã biết những giá trị này, chỉ cần đừng bỏ chúng đi sau khi vẽ.

Và **cho phép waiver có lý do**, đừng cho phép nới gate:

```python
# render_spec.json
"waivers": [
  {"code": "I5-anchor", "ids": ["rail_control", "rail_telemetry"],
   "reason": "cross-cutting plane, deliberately not bound to two nodes",
   "approved_by": "solution-architecture"}
]
```

Waiver có người ký thì audit được. Hạ threshold thì không.
