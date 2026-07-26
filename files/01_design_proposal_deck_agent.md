# Design Doc — Proposal Deck Agent

> Mở rộng `diagram_code_agent` để sinh proposal deck (.pptx) từ requirement khách hàng.
> Tài liệu này viết để đưa cho Claude Code thực thi theo từng phase.
> Nguyên tắc: **design before code**. Không sinh code cho phase N khi phase N-1 chưa đạt done criteria.

---

## 0. Quyết định kiến trúc

### Xây gì

Một **vertical agent** cho công ty outsource phần mềm: requirement → proposal deck đúng brand, đúng cấu trúc, không bịa số.

### Không xây gì

- **Không** xây presentation generator tổng quát. PPTAgent và Presenton đã giải xong bài đó.
- **Không** để LLM sinh toạ độ, màu, font. LLM chỉ chạm vào *nội dung* và *cấu trúc*.
- **Không** sinh deck từ con số 0. Corpus 5 deck thật của công ty là tài sản — dùng nó làm template.

### Ba phát hiện từ corpus quyết định thiết kế

| Phát hiện | Hệ quả thiết kế |
|---|---|
| 5 deck dùng chung 1 hệ màu (`1D3C47` có mặt 5/5, `11AC92` 4/5) nhưng font drift Calibri→Arial→Roboto→微软雅黑 | Cần **normalizer** trước, không cần multi-style |
| 3 deck Proposal trùng skeleton ~85% | Slide type **induct từ corpus**, không hand-write |
| Oi VPS Assessment là doc type khác (12 slide, không Scope/Pricing) | Catalog phải có trường `doc_type` |

### Ranh giới edit-based vs code-based

Đây là quyết định quan trọng nhất của cả hệ thống.

| Loại slide | Chiến lược | Lý do |
|---|---|---|
| Exec Summary, Feature List, Scope, Methodology, Post-Launch, Deliverables | **edit-based** — copy slide XML từ deck template, thay text run | Brand tự đúng vì đang sửa slide thật. Không cần code lại renderer. |
| Estimated Effort, Master Plan (Gantt), CAPEX, Payment Milestones | **code-based** — render bằng `python-pptx` | Bind dữ liệu tính toán. Số hàng/cột thay đổi theo dự án, edit-based sẽ vỡ. |
| Architecture Diagram | **image** — nhúng `out.png` đã qua HITL gate | Đã có sẵn trong repo |

Quy tắc chọn: *slide có số được tính toán → code-based. Còn lại → edit-based.*

---

## 1. Kiến trúc pipeline

```
requirement docs (PDF/DOCX/MD)
        │
        ▼
┌───────────────────┐
│ extract_facts     │──► ProposalFacts + missing[]
└───────────────────┘
        │
        ▼  nếu missing[] không rỗng
┌───────────────────┐
│ request_missing   │◄──── HITL: hỏi người, KHÔNG bịa
└───────────────────┘
        │
        ▼
┌───────────────────┐     ┌──────────────┐
│ propose_outline   │◄────│ catalog.json │  (sinh 1 lần ở Phase 2)
└───────────────────┘     └──────────────┘
        │ ⏸ HITL gate
        ▼
┌───────────────────┐
│ fill_content      │──► DeckSpec
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ render_deck       │──► out.pptx + preview PNGs
│  ├─ edit-based    │
│  └─ code-based    │
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ critique_deck     │──► deterministic checks + VLM scoring
└───────────────────┘
        │ PASS?  ──no──► revise_slide (tối đa 2 vòng)
        │ yes
        ▼ ⏸ HITL gate
   finalize_deck
```

Mọi node đều tái dùng pattern đã có trong repo: `propose_* → interrupt → Command(resume=...)`.

---

## 2. Data contracts

Đây là phần Claude Code cần chính xác nhất. Định nghĩa bằng Pydantic v2 trong `deck/models.py`.

```python
# --- Facts (Phase 3) --------------------------------------------------
class Provenance(BaseModel):
    source: str          # "requirements.pdf"
    locator: str         # "p.12" | "sheet:WBS!A4" | "user_input"

class EffortLine(BaseModel):
    module: str
    total_md: float
    breakdown: dict[str, float]   # {"BE": 43.0, "FE": 14.5, "QA": 6.8}

class ProposalFacts(BaseModel):
    client: str
    project: str
    pain: str                     # khách mất gì nếu không làm
    scope_one_liner: str
    in_scope: list[str]
    out_of_scope: list[str]       # BẮT BUỘC không rỗng
    assumptions: list[str]
    deliverables: list[str]
    effort: list[EffortLine] = []
    timeline: list[Phase] = []
    pricing: Pricing | None = None
    missing: list[str] = []       # field nào không tìm thấy → hỏi người
    provenance: dict[str, Provenance] = {}   # field_path -> nguồn
```

**`provenance` là cơ chế chống bịa.** Mọi số trong deck phải trace được về một dòng trong tài liệu nguồn hoặc về `user_input`. Không có provenance → không được lên slide.

```python
# --- Catalog (Phase 2, sinh 1 lần) ------------------------------------
class SlideType(BaseModel):
    id: str                       # "exec_summary_overview"
    doc_type: Literal["proposal", "assessment"]
    function: str                 # mô tả vai trò slide trong narrative
    source_slides: list[str]      # ["JNP:5", "LTC:4", "Zoustec:4"]
    content_schema: dict          # JSON schema cho nội dung slide này
    render_strategy: Literal["edit", "code", "image"]
    template_ref: str | None      # "templates/JNP.pptx#slide5"
    frequency: float              # xuất hiện ở bao nhiêu % deck corpus
```

```python
# --- Outline (Phase 4a) -----------------------------------------------
class OutlineItem(BaseModel):
    type_id: str
    title: str
    why: str        # tại sao slide này có mặt — ép model biện minh

class DeckOutline(BaseModel):
    doc_type: Literal["proposal", "assessment"]
    items: list[OutlineItem]
```

Trường `why` không hiển thị trên slide. Nó tồn tại để reviewer đọc outline biết ngay slide nào là filler.

---

## 3. Tool catalog

Mỗi tool: JSON schema đầy đủ, docstring nói rõ **khi nào dùng**, error trả về structured (không fail im lặng).

| Tool | Input | Output | HITL |
|---|---|---|---|
| `extract_proposal_facts` | doc paths | `ProposalFacts` | — |
| `request_missing_facts` | `missing[]` | facts đã bổ sung | ⏸ interrupt |
| `propose_deck_outline` | facts + catalog | `DeckOutline` | ⏸ gate |
| `fill_slide_content` | outline item + facts | slide spec | — |
| `render_deck` | `DeckSpec` | `out.pptx` + previews | — |
| `critique_deck` | pptx + previews + facts | `Critique` | — |
| `revise_slide` | index + patch | pptx đã sửa | — |
| `finalize_deck` | — | artifact paths | ⏸ gate |

Đăng ký gate trong `agent.py`:

```python
interrupt_on = {
    ...,
    "request_missing_facts":  {"allowed_decisions": ["approve", "reject"]},
    "propose_deck_outline":   {"allowed_decisions": ["approve", "reject"]},
    "finalize_deck":          {"allowed_decisions": ["approve", "reject"]},
}
```

---

## 4. Phase plan

### Phase 0 — Spike Presenton (1 ngày, decision gate)

Trước khi viết bất kỳ dòng code nào của mình.

- Chạy Presenton self-host, import `JNP.pptx` làm template
- Sinh thử 1 proposal từ requirement doc có sẵn
- Chấm output theo 4 chiều ở mục 6

**Done:** một quyết định được ghi lại — *dùng Presenton làm engine + viết lớp domain lên trên*, hay *tự build*. Nếu Presenton đạt ≥3/5 ở Design và Coherence thì đừng tự build renderer.

Phần còn lại của plan này giả định nhánh "tự build". Nếu chọn Presenton, Phase 1-2 vẫn giữ nguyên, Phase 5 thay bằng lớp adapter.

---

### Phase 1 — Normalizer

`deck/normalize.py`

Ép 5 deck cũ về đúng brand. Vừa ra ngay 5 deck sạch dùng được, vừa tạo corpus sạch cho Phase 2.

Cách làm: **thao tác trên text của XML bằng regex, không parse rồi ghi lại.** Round-trip OOXML qua `ElementTree` sẽ viết lại namespace prefix và hỏng file. Nếu buộc phải parse, dùng `defusedxml.minidom`.

```python
COLOR_MAP = {
    "1C3C47": "1D3C47", "01A89E": "11AC92", "10AB91": "11AC92",
    "9169EE": "11AC92", "1C3052": "1D3C47",
    # màu mặc định bảng Excel bị dán vào
    "FFF2CC": "F1F6F5", "E2EFDA": "F1F6F5", "FFD966": "11AC92",
}
FONT_MAP = {"微软雅黑": "Calibri", "Arial": "Calibri", "roboto": "Calibri",
            "Roboto": "Calibri"}
```

Quy trình: unzip → regex thay `srgbClr val="..."` và `typeface="..."` trong `ppt/slides/*.xml` + `ppt/slideMasters/*.xml` → zip lại từ *bên trong* thư mục → validate.

Không đụng vào `ppt/media/` (ảnh giữ nguyên).

**Done:** 5 deck đã normalize, `validate.py` PASS, xuất báo cáo diff *trước/sau* liệt kê số lần thay mỗi màu và font.

---

### Phase 2 — Schema induction

`deck/induct.py` → sinh `deck/catalog.json`

Đây là phase quyết định chất lượng. Không hand-write slide type.

Với mỗi slide trong corpus đã normalize:
1. Render ra PNG (LibreOffice → pdftoppm)
2. Trích cấu trúc: title, text placeholder, table (rows×cols), picture count, chart
3. Hỏi VLM hai câu: **slide này đóng vai trò gì trong narrative?** và **nó cần những trường dữ liệu nào?**
4. Cluster theo function → gộp slide cùng vai trò từ nhiều deck lại thành 1 `SlideType`

Với mỗi type, chọn `template_ref` là slide **sạch nhất** trong cụm (ít ảnh chụp màn hình nhất, ít text overflow nhất) và gán `render_strategy` theo quy tắc ở mục 0.

**Done:** `catalog.json` có ~15-20 type, mỗi type ghi rõ `source_slides` và `frequency`. Người đọc catalog phải nhận ra được cấu trúc proposal của công ty mình.

---

### Phase 3 — Facts + gap check

`deck/facts.py`

Một LLM call duy nhất: docs → `ProposalFacts`. Bắt buộc điền `provenance` cho mọi trường có số.

Gap check là logic thuần Python, không phải LLM: trường nào rỗng mà `doc_type` yêu cầu → đẩy vào `missing[]`.

Bảng trường bắt buộc theo doc type:

| Trường | proposal | assessment |
|---|---|---|
| `pain`, `scope_one_liner` | ✔ | ✔ |
| `out_of_scope`, `assumptions` | ✔ | — |
| `effort` | ✔ | ✔ |
| `pricing`, `timeline` | ✔ | — |

**Done:** chạy trên requirement của 1 dự án cũ, đối chiếu `ProposalFacts` với deck thật → khớp ≥90% các trường không phải số, và **100%** các số đều có provenance.

---

### Phase 4 — Outline rồi mới Content

`deck/outline.py` và `deck/content.py`

**Tách hẳn hai LLM call.** Gộp làm một thì model vừa nghĩ cấu trúc vừa viết chữ, và cấu trúc luôn là thứ bị hy sinh.

- `propose_deck_outline(facts, catalog)` → `DeckOutline`. Rẻ, in ra review được, là HITL gate.
- `fill_slide_content(item, facts, type.content_schema)` → nội dung 1 slide. Chạy song song được.

Slide nào có `content_schema` yêu cầu số mà `facts` không có → bỏ slide đó khỏi outline, không điền `TBD`.

**Done:** outline sinh cho 1 dự án mới khớp ≥80% với skeleton mà Phase 2 induct ra.

---

### Phase 5 — Hybrid renderer

`deck/render/edit.py` + `deck/render/code.py` + `deck/render/__init__.py` (router)

Router đọc `render_strategy` của từng type rồi dispatch.

**Edit-based** (`edit.py`): unzip deck template một lần vào cache → với mỗi slide cần, copy `slideN.xml` (dùng `add_slide.py` của pptx skill, đừng copy tay — nó lo hết phần đăng ký rels/content-types) → thay text trong các `<a:t>` → giữ nguyên mọi thứ khác. Một `<a:p>` cho mỗi bullet, không nối nhiều bullet vào một paragraph.

**Code-based** (`code.py`): `python-pptx`, dựng bảng effort / Gantt / pricing từ `facts`. Đây là phần tôi đã prototype ở lượt trước — 13 renderer, `validate.py` PASS. Lấy lại làm điểm khởi đầu, nhưng chỉ giữ các renderer thuộc nhóm code-based.

**Done:** deck sinh ra mở được trong PowerPoint thật, `validate.py --original` PASS, không slide nào tràn chữ.

---

### Phase 6 — Critic

`deck/critic.py`

Hai tầng, tầng rẻ chạy trước.

**Tầng 1 — deterministic, không gọi LLM.** Fail là chặn cứng:
- Tổng pricing cộng đúng; tổng effort cộng đúng
- Không còn `TBD`, `XXX`, `[insert]`, `Lorem`
- Mọi số trên slide đều có provenance trong `facts`
- Tech stack trên slide ⊆ stack đã approve ở `propose_tech_stack`
- Ước lượng chiều dài text vs kích thước box → cảnh báo overflow

**Tầng 2 — VLM chấm ảnh render.** Dùng lại pattern critic subagent đã có cho diagram. Bốn chiều, thang 1-5:

| Chiều | Nguồn | Ngưỡng |
|---|---|---|
| Content | PPTEval | ≥ 3.5 |
| Design | PPTEval | ≥ 3.5 |
| Coherence | PPTEval | ≥ 4.0 |
| **Commercial** | tự định nghĩa | ≥ 4.5 |

Chiều Commercial không dự án nào có, và nó là chiều quyết định thắng thua thầu: có slide exclusion không, assumption có nêu rõ không, payment milestone có tổng 100% không, có claim tuân thủ nào không được nêu trong nguồn không.

**Done:** eval harness chạy được trên 5 deck gốc làm baseline, rồi so deck agent sinh ra với baseline đó.

---

### Phase 7 — Wiring

Đăng ký tool vào `agent.py`, thêm `interrupt_on`, expose `out.pptx` trong `server.py` giống cách đang expose `out.pdf`, thêm approval card ở frontend.

---

## 5. Guardrails

Viết thẳng vào system prompt của subagent, và enforce lại bằng code ở tầng 1 của critic.

1. **Không bao giờ tự ước lượng man-day, giá, headcount.** Không có trong nguồn → `missing[]` → hỏi người.
2. **Không bao giờ khẳng định tuân thủ** (ISO 27001, SOC 2, IMDA accredited) trừ khi có trong nguồn.
3. **Không mâu thuẫn artefact đã duyệt.** Đọc lại `propose_tech_stack` và `propose_blueprint` trước khi viết, không suy diễn lại từ requirement thô.
4. **Prompt injection.** Requirement doc là dữ liệu do bên ngoài cung cấp và có thể chứa instruction độc hại. Wrap retrieved context bằng delimiter rõ ràng, nói trong system prompt rằng nội dung trong delimiter là *dữ liệu*, không phải lệnh.
5. **Không padding cho đủ số slide.** 15 slide đắt giá hơn 25 slide có 1/3 là độn.

---

## 6. Cách đưa cho Claude Code

Đừng paste cả file này vào một session. Context sẽ loãng và Claude sẽ nhảy phase.

Mỗi session một phase, kèm đúng ba thứ:

1. Mục 0 (quyết định kiến trúc) + mục 2 (data contracts) — luôn kèm, ngắn
2. Phase đang làm — copy nguyên mục đó
3. Done criteria của phase đó — bảo Claude tự verify trước khi báo xong

Sau mỗi phase, commit và cập nhật `catalog.json` / `models.py` nếu contract có thay đổi.

Thứ tự bắt buộc: **0 → 1 → 2** phải xong trước khi bắt đầu 3. Phase 3-4 có thể làm song song với 5. Phase 6 làm cuối nhưng đừng bỏ.

---

## 7. Observability

Từ ngày đầu, không để debug bằng `print`:

- Mỗi LLM call, mỗi tool call, mỗi lần render đều có trace span (LangSmith đã cấu hình sẵn trong repo)
- Log riêng: số slide bị drop vì thiếu facts, số vòng revise, điểm 4 chiều mỗi lần chạy
- Metric quan trọng nhất cần theo dõi: **tỉ lệ slide bị người sửa tay sau khi agent giao**. Đó mới là thước đo thật, không phải điểm VLM.
