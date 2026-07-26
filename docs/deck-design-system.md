# Deck design system — rút từ corpus slide BnK

> Tài liệu này trả lời một câu hỏi cụ thể: *slide do BnK người-thật làm trông như thế nào, và
> deck agent hiện sinh ra khác gì*. Đây là quan sát + phân tích khoảng cách — **không phải**
> đặc tả implement. Đọc trước khi đụng `domain/reporting/ppt_reporting.py`,
> `domain/deck/deck_sections.py`, hoặc thêm preset màu / block slide mới.

## 1. Nguồn & phương pháp

| Nguồn | Số lượng | Dùng để |
|---|---|---|
| `DATA/SLIDE/*.pptx` (file gốc) | 76 file đọc được bằng `python-pptx` (trên tổng ~90, phần còn lại là `.pdf`/`.docx`) | Trích **deterministic** màu/font/layout qua OOXML — không cần LLM |
| `DATA/SLIDE_IMAGES/*/slide_NNN.png` | 2.083 ảnh, 78 deck | Quan sát bố cục trực quan (đã đọc trực tiếp ~15 ảnh chọn lọc trải 8 deck, nhiều thời kỳ) |
| `backend/templates/bnk_proposal_template.pptx` | Template renderer đang dùng thật | Toạ độ placeholder chính xác — nguồn xác thực cho "vùng an toàn" |

**Giới hạn đã biết:** mọi PNG có watermark "Evaluation only — Aspose.Slides" đè lên giữa slide
(rendering pipeline dùng `aspose.slides`, xem `DATA/analyze_slide.py`) → không sample màu theo
pixel PNG được. Màu ở §2 lấy từ `<a:solidFill><a:srgbClr>` thẳng trong XML của `.pptx` gốc,
chính xác tuyệt đối, không qua render. Corpus không đồng nhất: 76 file trải nhiều nguồn gốc
(template BnK chuẩn, export Google Slides, template khách tự đưa) — vì vậy phần layout-geometry
ở §2.3 lấy từ đúng `bnk_proposal_template.pptx` (cái renderer thật sự vẽ lên), không cố ép một
lưới chung từ 76 file không đồng chất.

Trước đây (xem `analyze_slide.py` docstring) việc viết `analysis.md` do Claude làm ad-hoc trong
chat, không lưu prompt/schema — nên 84 file phân tích hiện có chỉ nói nội dung nghiệp vụ, câu duy
nhất về thiết kế trong toàn bộ corpus là *"màu xanh teal + navy"* (`_BnK_ Template Deck/analysis.md`).
Tài liệu này là lần đầu tiên câu hỏi "trông thế nào" được trả lời có hệ thống.

---

## 2. Hệ thiết kế BnK rút từ corpus

### 2.1 Palette thật (đo trên 76 file, đếm tần suất `srgbClr` trong toàn bộ slide XML, đã loại đen/trắng/xám thuần)

| Cụm màu | Hex đại diện | Xuất hiện | Số deck có mặt (top-6/deck) |
|---|---|---|---|
| **Navy** (chữ tiêu đề, header bảng, nền dark section) | `#193D4F` (x3.835) — biến thể `#1D3C47` `#1C3C47` `#1B3B46` `#0C2834` `#163652` | cụm đông nhất toàn corpus | **63/76 deck** |
| **Teal/cyan** (accent, header bảng, số liệu nhấn) | `#11AC92` (x1.902) — biến thể `#01A89E` `#00B8AA` `#10AB91` `#19A887` `#008179` `#00A3AA` | cụm đông thứ 2 | **69/76 deck** |
| Card nền nhạt | `#E2E8F0` | x1.112 | phổ biến trong deck 2026 |
| Đỏ cảnh báo | `#FF0000` / `#C00000` | x535 / x154 | dùng cho risk/pain-point |
| Xanh dương phụ | `#0070C0` / `#007FAE` | x174 / x167 | ít hơn hẳn navy/teal |
| Vàng nhạt / xanh lá nhạt (nền bảng zebra) | `#FFF2CC` / `#E2EFDA` | x160 / x154 | bảng Gantt, bảng chi phí |

**Kết luận quan trọng nhất:** navy + teal **không phải** màu riêng của một khách hàng — nó lặp
lại trong 63–69/76 deck độc lập → đây là bản sắc BnK thật, đúng với câu nhận xét duy nhất trong
`analysis.md` cũ.

**Đối chiếu với 4 preset đang hardcode ở `ppt_reporting.py:38-79`:**

| Preset | Hex khai báo | Có xuất hiện trong corpus không |
|---|---|---|
| `corporate` (mặc định khi không chọn `deck_style`) | `blue=#1F4E78`, `cyan=#009FDF` | **0 lần trong 76 file** |
| `modern` | `blue=#102A43`, `cyan=#14B8A6` | **0 lần** |
| `minimal` | `blue=#2B2B2B`, `cyan=#6B7A8F` | **0 lần** |
| `vip` | `blue=#0B1A2F`, `cyan=#19A887` | `cyan` khớp đúng `#19A887`, **249 lần** trong corpus — duy nhất trong 4 preset từng được đối chiếu với deck thật |

Tức là: **preset mặc định (`corporate`) — cái deck nào không chỉ định `deck_style` sẽ dùng —
dùng bộ màu không hề xuất hiện trong bất kỳ deck BnK thật nào.** `vip` là preset duy nhất bắt
đúng identity thật, nhưng chỉ kích hoạt khi model chủ động truyền `deck_style="vip"` theo yêu
cầu tường minh của người dùng (`reporting_gates.py:150-158`, `prompts/ppt_generator_agent.py:29-32`).

### 2.2 Typography

| | Kết quả đo (76 file × 2 slot font/theme) |
|---|---|
| Major font (heading) | `Calibri Light` — 151/152 lần đo. `Aptos Display` chỉ xuất hiện ở 24 lần, toàn bộ đến từ một lô deck mới hơn (default Office 2024+ chưa được style lại) — tín hiệu drift, không phải chủ đích. |
| Minor font (body) | `Calibri` — 144/152 lần. `Aptos` 24 lần cùng lô nói trên. `Inter` chỉ 12 lần — đến từ đúng batch làm nền cho preset `vip` (khớp ghi chú `font: "Inter"` ở `ppt_reporting.py:75`). |

→ `Calibri` / `Calibri Light` đúng là chuẩn thật, không phải giả định. Nhưng đây cũng là nguồn
của **bug đã tìm thấy**: `deck_visual_qa.py:33` khai `_BNK_FONTS = frozenset({"Calibri",
"Calibri Light"})` — cứng, không tính `Inter`. Preset `vip` (đúng bộ màu thật nhất!) tự động bị
gắn cờ QA `font_drift` trên **mọi** deck nó tạo ra.

### 2.3 Lưới & vùng an toàn — đo trực tiếp trên `bnk_proposal_template.pptx`

Khổ slide: **13.333 × 7.5 in** (16:9). Toạ độ placeholder của từng layout (in), lấy từ chính
file template renderer đang dùng:

| Layout | Placeholder | left | top | w | h |
|---|---|---|---|---|---|
| `Detail-01` / `Detail-02` | Title | 0.226 | 0.281 | 12.799 | 0.449 |
| `Detail-01` / `Detail-02` | **Body (vùng nội dung)** | **0.325** | **1.065** | **12.701** | **6.154** |
| `Detail-01` | Decorative card slot (góc phải, dành cho ảnh/case-study) | 9.732 | 3.608 | 5.369 | 5.45 |
| `Cover-01` | Title | 0.682 | 3.75 | 7.76 | 1.45 |
| `Head Page` / `Head-01` (divider) | Title | 0.727 | 4.3 | 12.747 | 1.45 |
| `Overview-01` | Title + Subtitle | 0.917 / 1.667 | 1.539 / 3.038 | 11.5 / 10.0 | 1.45 / 1.811 |

**Phát hiện định lượng:** vùng nội dung mà chính template dành riêng cho `Detail-01` là
**0.325–13.026 in ngang × 1.065–7.219 in dọc** (diện tích 78,2 in²). Renderer hiện dùng hằng số
riêng ở `ppt_reporting.py:764-767`:

```
_CONTENT_X = 0.6   _CONTENT_Y = 1.35   _CONTENT_W = 12.1   _CONTENT_H = 5.35
```

→ vùng renderer thực sự vẽ (0.6–12.7 in ngang × 1.35–6.7 in dọc, diện tích 64,7 in²) chỉ chiếm
**~83% diện tích mà chính template của mình đã chừa sẵn**. Phần bị bỏ trống nằm ở đáy slide
(1.35→6.7 dừng sớm hơn vùng an toàn 7.219 gần **0.52 in**, tức ~7% chiều cao slide) — khớp
chính xác với quan sát trực quan ở §3 (khoảng trống đáy `slide_05.png`, `slide_11.png`).

---

## 3. Thư viện archetype slide

Mỗi archetype: khi nào dùng · dẫn chứng ảnh đã đọc trực tiếp · block/renderer gần nhất trong code.

### 3.1 Stat/KPI band *(ưu tiên #1)*

Dải 3–4 thẻ số liệu đậm màu ở **đáy** slide nội dung — pattern tái diễn dày nhất trong toàn
corpus (thấy ở `BnK-Modena…/slide_016.png`, `BnK_CMA…/slide_005.png` dạng 2-thẻ, và lặp lại
ở hầu hết deck có phần "Expected Outcomes"/"KPIs").

```
┌─────────────────────────────────────────────┐
│ [chip #] Tiêu đề                             │
│ ───                                          │
│  Nội dung phía trên (bullet / 2 cột)         │
│                                               │
│ ┌────────┬────────┬────────┬────────┐        │
│ │  100%  │  100%  │  >95%  │  >700  │  ← nền │
│ │ caption│ caption│ caption│ caption│    đặc  │
│ └────────┴────────┴────────┴────────┘        │
└─────────────────────────────────────────────┘
```

Nền thẻ = màu teal đặc (`#11AC92`-family) chữ trắng, số lớn 28-32pt bold + caption 10-12pt.
Block gần nhất: `kpis` — đã có `SectionContract` (`deck_sections.py`, section `appendix`) nhưng
nằm trong `NEW_BLOCKS` (`deck_sections.py:839`), **chưa có renderer**. Primitive `_add_stat_block`
đã tồn tại (`ppt_reporting.py:630`) và đang dùng dở cho pricing/delivery-effort — chỉ thiếu một
block độc lập gọi nó thành dải kín đáy slide.

### 3.2 Two-column contrast *(ưu tiên #2)*

Cột trái/phải đối lập, mỗi cột có thanh header màu đặc. Thấy ở `BnK-Modena…/slide_016.png`
("Challenges | Deployment solution"), `BnK_ESG…/slide_008.png` biến thể bảng đơn nhưng cùng tinh
thần phân vùng bằng header màu đặc.

```
┌──────────────────────┬──────────────────────┐
│▓▓ Challenges ▓▓▓▓▓▓▓▓│▓▓ Deployment sol. ▓▓▓│ ← header đặc, 2 màu
│  • điểm 1             │  Nội dung dạng bullet │
│  • điểm 2             │  có cấu trúc con      │
└──────────────────────┴──────────────────────┘
```

Ánh xạ gần nhất trong `deck_sections.py`: `risk_table` (section `risks`), `goals_value`
(section `executive_summary`), `change_request` (section `scope`) — cả ba đều `new_block`,
chưa renderer.

### 3.3 Icon grid có kỷ luật *(ưu tiên #3 — đang vỡ)*

So sánh trực tiếp: deck thật không có ví dụ icon-grid xấu (BnK dùng bảng `Layer|Tech|Description`
nhiều hơn icon-grid), nhưng renderer hiện tại tự chọn nhánh icon-grid
(`_tech_stack_icon_slide`, `ppt_reporting.py:967`) và **vỡ**:
`slide/preview/slide_11.png` — 5 icon dồn góc trên-trái, nhãn cắt cụt (`NVIDIA DeepStrea`,
`Memorystore Redi`), ~70% canvas trống. Nguyên nhân: toán vị trí hardcode
(`x=3.15`, `x += 1.5`, ngắt dòng khi `x > 12.6`, `Pt(6.5)` cho nhãn) không cộng dồn theo số
lượng thực tế item và không co giãn theo `_CONTENT_W`.

### 3.4 Space-fill / nhịp dọc *(ưu tiên #4 — nguyên nhân gốc của nhiều archetype khác)*

Không phải một block cụ thể mà là **quy tắc còn thiếu ở tầng renderer chung**: mọi block hiện
bám cứng `_CONTENT_Y = 1.35` làm điểm bắt đầu và một `h` cố định, không hỏi "còn lại bao nhiêu
chỗ trống, có nên giãn dòng / thêm khoảng đệm / phóng to card để lấp đủ khung `_CONTENT_H`
(hoặc tốt hơn, khung thật của template — xem §2.3) hay không". Hệ quả nhìn thấy ở cả
`slide_05.png` (bullet trên cùng, 60% dưới trắng trơn) lẫn `slide_11.png` (icon-grid vỡ). Deck
thật không có "block trống nửa dưới" — kể cả slide ít nội dung nhất cũng được cân bằng bằng
minh hoạ (`BnK_CMA…/slide_005.png`: text ít bên trái được bù bằng diagram + 2 stat-card bên phải).

### 3.5 Các archetype khác đã quan sát (tham khảo, không nằm trong 4 ưu tiên)

| Archetype | Dẫn chứng | Ghi chú |
|---|---|---|
| Cover | `Proposal - Charm Website/slide_002.png` | Thanh tiêu đề màu đặc + agenda đánh số — biến thể khác với `Cover-01` template (chip số + gạch chân) đang dùng |
| Divider | `BnK_CMA…/slide_012.png`, `Makalot…/slide_005.png` | Ảnh nền full-bleed tối màu + gradient hình học + số La Mã — khớp khá sát với `_section_slide` hiện tại (`slide_17.png` của ta đã đạt) |
| Full-bleed screenshot | `BnK-Modena…/slide_009.png` | Ảnh sản phẩm chiếm toàn khung, chip số nhỏ đè lên |
| Text + visual 40/60 | `BnK_CMA…/slide_005.png` | Chữ trái hẹp, minh hoạ phải rộng — không có slide nội dung nào trong corpus chỉ có chữ suông |
| Bảng có header-band màu theo giai đoạn | `Makalot…/slide_010.png`, `Proposal - Charm Website/slide_009.png` | Gantt/scope table với dải màu theo Tháng/Sprint — khớp gần đúng với `_gantt_slide` đã implement (`ppt_reporting.py:1307`) |

---

## 4. Gap analysis

| Archetype/vấn đề | Trạng thái code | Vì sao vỡ / thiếu | Chạm vào đâu nếu implement |
|---|---|---|---|
| Stat/KPI band | Không có renderer | `kpis` ở `NEW_BLOCKS` | `deck_sections.py:839` (bỏ khỏi NEW_BLOCKS), renderer mới dùng `_add_stat_block` (`ppt_reporting.py:630`), dispatch thêm nhánh trong `_render_block` (`ppt_reporting.py:1795`) |
| Two-column contrast | Không có renderer | `risk_table`/`goals_value`/`change_request` ở `NEW_BLOCKS` | như trên, 3 block riêng biệt |
| Icon grid vỡ | Có renderer, sai toán | `_tech_stack_icon_slide` (`ppt_reporting.py:967`) toạ độ hardcode không co giãn | viết lại toán lưới trong chính hàm này |
| Space-fill / nhịp dọc | Không tồn tại khái niệm | Mọi renderer bám `_CONTENT_X/Y/W/H` cố định (`ppt_reporting.py:764-767`), không đối chiếu vùng an toàn thật của template (§2.3) | cần một layer tính "chiều cao còn lại" dùng chung, nằm trước `_render_block` |
| Preset màu mặc định sai identity | `corporate` là default, 0/76 deck thật dùng màu này | `_STYLE_PRESETS["corporate"]` (`ppt_reporting.py:39-48`) tự chế, chưa từng đối chiếu corpus | thay giá trị `corporate` bằng cụm `#193D4F`/`#11AC92` đo được ở §2.1, hoặc đổi default sang `vip` |
| `vip` (preset đúng nhất) bị QA gắn cờ sai | Bug thật | `_BNK_FONTS = {"Calibri","Calibri Light"}` (`deck_visual_qa.py:33`) không có `"Inter"` dù `vip` dùng Inter (`ppt_reporting.py:75`) | thêm `"Inter"` vào `_BNK_FONTS`, hoặc đổi audit đọc font theo preset đang active |
| `case_library.json` không bao giờ được nạp | Bug thật, không liên quan style nhưng chặn cả archetype "Success Story" | `_refresh_deck_plan` (`reporting_gates.py:297-307`) gọi `build_deck_plan(...)` thiếu `library=` → `_pick_case_study_keyword` luôn nhận `[]` | truyền `library=load_case_library()` (tên hàm cần verify) vào lời gọi |
| Rò text nội bộ ra slide khách | Content hygiene, không phải style | `slide_05.png`: *"Slide 3 liệt kê 4 vấn đề…"*, *"Reference effort: … (past project, not this quote)"* lọt vào bullet client-facing | nguồn dữ liệu ở `deck_resolver._case_to_params`, cần lọc câu meta trước khi đưa vào `params["context_paragraph"]`/`outcome` |
| Trộn VI/EN cùng slide | Content hygiene | Cùng file `slide_05.png` | không có validation ngôn ngữ nhất quán ở `deck_visual_qa.py` hiện tại |
| Nhãn icon-grid bị cắt cụt | Trực tiếp do §3.3 | `_tech_stack_icon_slide` cỡ chữ `Pt(6.5)` + không đo độ dài text trước khi vẽ | cùng chỗ sửa với icon grid |

---

## 5. Chính sách ảnh case study

Ảnh `image_ref` trong block `case_study` (`ppt_reporting.py:1501-1541`) hiện trỏ thẳng vào
`DATA/SLIDE_IMAGES/<deck khác>/slide_NNN.png` — tức là **ảnh chụp slide của một khách hàng khác**,
và mọi PNG trong kho này đều có watermark "Evaluation only — Aspose.Slides" đè giữa ảnh
(xem `slide_005.png`, `slide_009.png` ở §1). Nhúng nguyên trạng vào deck của khách hàng mới là
không chấp nhận được cho client-facing artifact.

**Quyết định:** giữ ảnh minh hoạ (không tắt hẳn `image_ref`), nhưng thay nguồn ảnh:

1. **Re-render sạch** — không dùng lại PNG watermark trong `DATA/SLIDE_IMAGES/`. Convert lại
   trực tiếp từ `.pptx` gốc trong `DATA/SLIDE/` bằng LibreOffice
   (`soffice --headless --convert-to pdf` rồi `pdftoppm`), khác hẳn `aspose.slides` (nguồn
   watermark) đang dùng ở `DATA/analyze_slide.py`. Output đặt vào một thư mục ảnh sạch riêng
   (ví dụ `backend/data/case_images_clean/`), **không** ghi đè `DATA/SLIDE_IMAGES/` gốc.
2. **Bắt buộc bước duyệt/che thông tin khách** trước khi một ảnh case-study được phép nhúng vào
   deck của khách hàng khác — logo/tên khách trong ảnh phải được xác nhận (che hoặc giữ nguyên
   có chủ đích) bởi người duyệt, không phải tự động 100%. Đây là gate mới, chưa tồn tại trong
   `pick_case_studies` (`deck_resolver.py:612`) hiện tại — hàm này chọn ảnh hoàn toàn tự động,
   không có điểm dừng duyệt.
3. **Rủi ro còn lại nêu thẳng:** re-render sạch loại được watermark nhưng không tự động loại
   được logo/tên khách hàng nằm *trong* nội dung slide (ví dụ slide có tên công ty ở header) —
   bước duyệt thủ công ở (2) là lớp chặn thật, không phải re-render kỹ thuật.

---

## 6. Luật scorecard đề xuất (để implement sau, không phải luật đang enforce)

| Luật | Ngưỡng đề xuất | Vì sao |
|---|---|---|
| Tỷ lệ lấp canvas | Nội dung phải phủ ≥ 90% vùng an toàn thật của layout (đo theo §2.3, không phải hằng số `_CONTENT_*` hiện tại) | Trực tiếp vá lỗi không gian trống ở `slide_05.png`/`slide_11.png` |
| Mọi slide nội dung phải có neo thị giác | Có ít nhất 1 trong {diagram, ảnh, icon, stat-card, bảng màu} — không được là bullet-only quá 6 dòng | Không slide nào trong corpus tham chiếu là bullet thuần |
| Nhãn không được cắt giữa từ | Cỡ chữ auto-fit theo độ dài chuỗi thực tế, hoặc rút gọn có `…` ở ranh giới từ | Vá `NVIDIA DeepStrea` |
| Một ngôn ngữ mỗi deck | Không trộn VI/EN trong cùng bullet/slide trừ thuật ngữ kỹ thuật | Vá `slide_05.png` |
| Không rò text nội bộ | Cấm chuỗi tham chiếu tới "slide N", "(not this quote)", số thứ tự nội bộ trong bất kỳ field client-facing | Vá `slide_05.png` |
| Font khớp preset đang active | So khớp với `font` của `_palette()` hiện hành, không phải set cứng `{Calibri, Calibri Light}` | Vá bug `vip`/`font_drift` ở §4 |
| Màu preset phải khớp corpus | Bất kỳ preset mới nào thêm vào `_STYLE_PRESETS` nên đối chiếu tần suất hex với §2.1 trước khi merge | Tránh lặp lại tình trạng `corporate`/`modern`/`minimal` hiện tại (0/76) |

Các luật này thuộc phạm vi mở rộng `deck_visual_qa.py` — hiện file đó mới có 6 luật cấu trúc/typo
đơn giản (`title_too_long`, `too_many_bullets`, `table_overflow`, `tiny_font`, `font_drift`,
`empty_body`, xem `deck_visual_qa.py:6-11`), chưa có luật nào thuộc lớp bố cục/thị giác.
