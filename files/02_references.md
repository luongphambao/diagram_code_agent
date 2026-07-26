# References — Proposal Deck Agent

Nguồn tham khảo đã sàng lọc. Dùng cho hai mục đích: người đọc để hiểu prior art, và nạp vào `web_research` / RAG để agent tìm kiếm có định hướng.

---

## 1. Prior art — repo cần đọc

Sắp theo mức độ liên quan. Cột "đọc gì" chỉ ra file/thư mục cụ thể, đừng đọc cả repo.

| Repo | Vì sao liên quan | Đọc gì |
|---|---|---|
| **icip-cas/PPTAgent**<br>`github.com/icip-cas/PPTAgent` | Đúng kiến trúc bạn cần: two-stage edit-based, induct slide-level functional type + content schema từ deck tham chiếu | Module induction (Phase 2 của bạn), tập API edit action, prompt của PPTEval |
| **PPTAgent / DeepPresenter (PyPI)**<br>`pypi.org/project/pptagent/` | Bản mới hơn: MCP server, sandbox Docker, 20+ tool, CLI `uvx pptagent generate` | `config.yaml.example`, `mcp.json.example` — xem họ tổ chức tool spec thế nào |
| **presenton/presenton**<br>`github.com/presenton/presenton` | Self-host, import PPTX thành template và giữ nguyên màu/typography/spacing, xuất PPTX editable, có MCP server | Pipeline import template — đây là thứ bạn spike ở Phase 0 |
| **hugohe3 / ppt-master** | Agent skill, shape native + chart + hỗ trợ template .pptx riêng | Cách họ mô tả skill để agent gọi đúng |
| **SlideSpeak agent skill**<br>`slidespeak.co/blog/agent-skills-presentations-powerpoint-ai` | pptxgenjs cho deck mới, unpack + ghi lại slide XML khi sửa, render ra ảnh để tự kiểm layout | Vòng self-check bằng ảnh — trùng Phase 6 tầng 2 |
| **chenxingqiang/ppt-agents** | Markdown → pptx, đơn giản, dễ đọc | `layout_analyzer.py` |
| **odin-slides** | Word dài → slide có tổ chức | Cách nén tài liệu dài thành outline |

---

## 2. Papers

| Paper | arXiv | Lấy gì |
|---|---|---|
| PPTAgent: Generating and Evaluating Presentations Beyond Text-to-Slides | `2501.03936` | Kiến trúc 2 giai đoạn + **PPTEval** (Content / Design / Coherence). Đọc bảng ablation: bỏ Outline làm Coherence rơi 4.48→3.36 — đó là bằng chứng cho quyết định "tách outline khỏi content" ở Phase 4 |
| DeepPresenter: Environment-Grounded Reflection for Agentic Presentation Generation | `2602.22839` | Vòng reflection có grounding vào môi trường render |
| UniPPTBench: A Unified Benchmark for Presentation Generation | `2605.17356` | Bảng so sánh failure mode của các hệ thống hiện có — đọc để biết trước mình sẽ vấp gì |
| DeckBench: Benchmarking Multi-Agent Frameworks for Slide Generation and Editing | `2602.13318` | Cách đo phần *editing*, không chỉ generation |
| X+Slides: Benchmarking Audience-Conditioned Slide Generation | `2606.19256` | Điều kiện hoá theo audience — proposal cho CTO khác proposal cho CFO |
| MemSlides: Hierarchical Memory Driven Agent for Personalized Slide Generation | `2606.17162` | Multi-turn local revision — trùng `revise_slide` của bạn |
| AutoPresent / SlidesBench | (tìm theo tên) | Sinh slide bằng code Python — nhánh code-based |

Ưu tiên đọc **PPTAgent trước**, hai lần: một lần lấy kiến trúc, một lần lấy prompt của PPTEval.

---

## 3. Docs kỹ thuật

| Thứ | Nguồn | Dùng ở phase |
|---|---|---|
| python-pptx | `python-pptx.readthedocs.io` | 5 (code-based) |
| pptxgenjs | `gitbrent.github.io/PptxGenJS` | 5, nếu chọn nhánh Node |
| ECMA-376 / OOXML spec | `ecma-international.org` — phần PresentationML | 1, 5 (edit-based) |
| LangGraph interrupt & resume | `langchain-ai.github.io/langgraph` — phần Human-in-the-loop | 7 |
| Deep Agents | docs của `deepagents` | 7 |

**Lưu ý OOXML quan trọng cho Phase 1 và 5:** thao tác trên *text* của XML bằng regex, đừng parse rồi ghi lại. Round-trip qua `xml.etree.ElementTree` viết lại namespace prefix và làm hỏng deck. Nếu buộc phải parse, dùng `defusedxml.minidom`.

---

## 4. Search query patterns cho `web_research`

Agent của bạn giới hạn ≤3 lần search/session. Đừng để nó tự nghĩ query. Nạp sẵn template theo stage.

**Khi induct catalog (Phase 2):**
```
"{industry} software proposal deck structure"
"statement of work presentation sections"
"RFP response deck outline software development"
```

**Khi verify tech stack (đã có sẵn trong repo):**
```
"{technology} latest stable version {current_year}"
"{technology} end of life support timeline"
"{technology} vs {alternative} production tradeoffs"
```

**Khi cần benchmark effort/pricing — cẩn thận:**
```
"software development man-day rate {country} {year}"
"{project_type} typical effort estimate breakdown"
```
> Kết quả loại này **chỉ dùng để sanity-check** con số khách đã cung cấp, tuyệt đối không dùng để *sinh ra* con số. Vi phạm guardrail #1.

**Khi domain-specific (ví dụ deck JNP):**
```
"Peppol BIS billing 3.0 Singapore mandatory document types"
"IMDA InvoiceNow accreditation requirements"
```

---

## 5. Domain allowlist cho Tavily

Ưu tiên nguồn gốc, chặn nguồn tổng hợp SEO.

**Ưu tiên:** `arxiv.org` · `github.com` · `*.readthedocs.io` · docs chính chủ của vendor (`docs.aws.amazon.com`, `spring.io`, `postgresql.org`) · trang chính phủ / cơ quan quản lý (`.gov`, `.gov.sg`, `imda.gov.sg`, `peppolguide.sg`)

**Hạ ưu tiên:** blog tổng hợp "top 10 best…", trang so sánh có affiliate, nội dung Medium không có tác giả rõ ràng

---

## 6. Corpus nội bộ — tài sản lớn nhất

Không nguồn bên ngoài nào thay được. Index vào RAG:

```
corpus/
├── decks_raw/          # 5 deck gốc
├── decks_normalized/   # output Phase 1
├── requirements/       # requirement doc gốc của từng dự án
├── wbs/                # file WBS Excel tương ứng
└── outcomes.csv        # deck nào đã ký được hợp đồng ← signal quý nhất
```

`outcomes.csv` là thứ không repo open-source nào có. Khi đã đủ ~20 dự án, nó cho phép trả lời được câu hỏi thật sự quan trọng: *cấu trúc deck nào thắng thầu*.

---

## 7. Thứ tự đọc đề xuất

1. PPTAgent README + paper `2501.03936` — 2 giờ, lấy kiến trúc và PPTEval
2. Presenton — cài và chạy thử, không cần đọc code (chính là Phase 0)
3. UniPPTBench `2605.17356` — mục failure mode
4. OOXML PresentationML — chỉ tra khi vướng ở Phase 1/5

Ba mục còn lại tra khi cần, đừng đọc trước.
