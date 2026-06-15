# Diagram linh hoạt kiểu "flow" (diagram 12), bỏ lưới cứng

## Context
Đợt trước đã làm poster dày đặc (`grid_cluster` + auto `constraint=false` + LR). Kết quả
`diagram (19).png`: **mọi cluster bằng nhau, xếp cứng, không có liên kết** giữa các vùng.
User muốn linh hoạt như `diagram (12).png`: cluster **co giãn theo nội dung** (1, 2, 4 node tùy
vùng), vị trí do **cạnh thật kéo** (flow), và **có đường nối rõ ràng** giữa các vùng.

Nguyên nhân gốc trong engine (`prettygraph.py`):
1. **Dòng 555-561**: khi có `cluster_grids`, MỌI cạnh cross-cluster bị ép `constraint=false`
   → cạnh không còn kéo layout → mất liên kết + các cluster chỉ xếp chồng đều nhau.
2. **`grid_cluster` áp dụng đồng loạt** mọi cluster → ép cùng số cột → mọi vùng cùng bề rộng.
3. **Spacing `0.18/0.45`** quá chặt, không chừa chỗ cho cạnh nối có nhãn.

`diagram (12)` ngược lại: `direction='LR'`, cạnh `constraint=true` kéo flow ngang (landscape),
cluster tự co theo số node, hầu như không ép lưới.

## Nguyên tắc cốt lõi (BẮT BUỘC)
- **TUYỆT ĐỐI KHÔNG hard-code** số node, kích thước box, số cột, ngưỡng cứng nhắc. Mọi giá trị
  **suy ra thích ứng** từ kiến trúc đầu vào (số node thực, số cluster, số node/cluster).
- **Chi tiết theo đúng thiết kế**: nếu kiến trúc thực sự phức tạp thì vẽ đủ chi tiết — KHÔNG cắt
  bớt nội dung để ép vừa trang. "Vừa một trang" đạt được bằng **scale-to-fit thích ứng** (thu nhỏ
  cả diagram để lọt khung), không phải bằng cách bỏ bớt node.

## Quyết định (theo trả lời user)
- **Độ dày**: ~20-28 node là **mức gợi ý mặc định** cho phần lớn hệ (ưu tiên sạch như diagram 12),
  KHÔNG phải trần cứng — hệ phức tạp được phép nhiều hơn, miễn còn đọc được sau khi scale vừa trang.
- **Cluster lớn**: **lai** — flow thật kéo macro layout; cluster "đủ lớn" mới đóng lưới bên trong,
  cluster nhỏ co giãn tự nhiên → kích thước cluster khác nhau. Ngưỡng "đủ lớn" là default hợp lý
  (suy từ số node con), không phải magic number rải rác.

## Yêu cầu thêm (user gửi sau)
- **Bỏ phần hero xanh** ("Enterprise Architecture Blueprint" + dải gradient xanh trên đầu) — không
  cần thiết. → `include_hero=False` thành mặc định, output chỉ còn diagram trên nền trắng.
- **Diagram phải vừa GỌN trong MỘT trang slide** (vì user dán vào slide). → canvas là **một trang
  landscape 16:9** cố định, scale toàn bộ body để VỪA trong khung (không tràn thành portrait dài).
  Đây là lý do nữa để chọn flow LR landscape + độ dày vừa (~20-28 node).

## Mục tiêu
House style mặc định = **flow linh hoạt** (như diagram 12): LR landscape, cluster co theo nội dung,
cạnh thật nối các vùng (liên kết rõ), chỉ vùng lớn mới gói lưới gọn bên trong. Vẫn giữ chi tiết:
logo thật + sublabel tech + vùng đánh số. Poster lưới-cứng (diagram 19) trở thành **tùy chọn** khi
được yêu cầu rõ.

## Thay đổi

### A. Engine — flow-driven layout + lưới chọn lọc (`backend/src/diagram_mcp/prettygraph.py`)
1. **Thêm cờ `flow_layout: bool = True`** vào dataclass `Pretty` (cạnh `cluster_grids`, ~dòng 188).
   - `True` (mặc định) = flow linh hoạt: cạnh cross-cluster GIỮ `constraint=true` để kéo layout.
   - `False` = poster lưới-cứng (giữ hành vi cũ: relax cạnh để lưới điều khiển layout).
2. **Sửa auto-relax (dòng 555-561)**: chỉ relax khi `self.grid_rows` (poster_grid legacy) **HOẶC**
   (`self.cluster_grids and not self.flow_layout`). Ở flow mode mặc định → KHÔNG relax → cạnh thật
   kéo flow + hiện rõ liên kết. (Drawer vẫn có thể đặt `constraint=False` thủ công cho cạnh
   back/feedback để tránh staircase.)
3. **Lưới chọn lọc trong `_grid_block` (dòng 245-266)**: chỉ đóng lưới khi cluster "đủ lớn".
   Ngưỡng là một **default có thể chỉnh** (vd hằng số module `FLOW_GRID_MIN` thay vì số rải trong
   code), ở flow mode dùng ngưỡng này, poster cứng dùng ngưỡng tối thiểu (gói cả vùng nhỏ). Số cột
   **suy từ số node con** (đã có logic count→cols ở `plan_style_sizes`), không cố định.
4. **Spacing (dòng 442-450)**: tách theo mode, dùng hằng số đặt tên (không magic). Flow + lai: spacing
   vừa để cạnh nối có chỗ thở; chỉ poster cứng (`cluster_grids and not flow_layout`) mới dùng chặt.
   Giá trị spacing là default theme, không phụ thuộc số node cụ thể.

### B. Default density + hướng dẫn (`tools.py`, `prompts.py`, 2× `pro-style/SKILL.md`)
1. **`Blueprint.density` (tools.py ~1384)**: đổi mặc định `"poster"` → **`"detailed"`** và **định
   nghĩa lại "detailed" = house style flow linh hoạt**: số node **theo độ phức tạp thực của kiến
   trúc** (~20-28 là vùng thoải mái mặc định, không phải trần — hệ phức tạp được nhiều hơn),
   `direction='LR'`, `flow_layout=True`, cluster co theo nội dung, cạnh thật nối vùng (BẮT BUỘC có
   liên kết), `grid_cluster` chỉ cho vùng đủ lớn, logo+sublabel, vùng đánh số. Giữ `"poster"` = wall
   lưới-cứng (`flow_layout=False`) cho khi user yêu cầu rõ; `"standard"` = hệ nhỏ. Mô tả field nêu rõ
   "chọn density theo kiến trúc, không cắt chi tiết để vừa trang — engine tự scale vừa slide".
2. **`plan_style_sizes` (tools.py ~785-896)**: nhánh mặc định/"detailed" hướng dẫn: `direction='LR'`,
   `flow_layout=True`, gọi `grid_cluster` chỉ cho vùng lớn (≥4 node), vẽ các cạnh thật cho flow
   chính. Nhánh `"poster"` đặt `flow_layout=False` + lưới mọi vùng (như cũ).
3. **`prompts.py`** `_PRETTY_DIAGRAM_DETAIL` (~454-506) + "Blueprint quality" (~674-679): viết lại
   recipe mặc định theo flow linh hoạt — LR, cluster co nội dung, **đường nối giữa vùng là yêu cầu**
   (đây là "sự liên kết" user thiếu), lưới chỉ cho vùng lớn. Poster mô tả là biến thể dày tùy chọn.
4. **2× `backend/skills/pro-style/SKILL.md` + `backend/skills/drawer/pro-style/SKILL.md`**: cập nhật
   ví dụ sang flow recipe (LR, `flow_layout=True`, cạnh thật, `grid_cluster` chỉ vùng lớn).

### C. Audit & cảnh báo (`tools.py`)
1. **`audit_diagram_code` (~428-456)**: hiện ÉP có lưới + number khi ≥6 cluster (giả định poster).
   Sửa: với default flow, KHÔNG đòi lưới mọi vùng; thay vào đó **cảnh báo nếu diagram nhiều cluster
   mà KHÔNG có cạnh cross-cluster** (bắt đúng lỗi "không liên kết"). Vẫn khuyến nghị `grid_cluster`
   cho vùng lớn + number cho vùng. Yêu cầu lưới đầy đủ chỉ áp cho `density='poster'`.
2. **Cảnh báo density (~1791-1808)**: cập nhật theo default mới ("detailed"); poster chỉ cảnh báo
   khi user chọn rõ mà hệ quá nhỏ.
3. **`_layout_audit` PANEL FILL (~157-185)**: gợi ý chấp nhận flow landscape (đừng chỉ đẩy "thêm cột/
   lưới"); với flow, fill thấp → gợi ý LR + thêm node/cạnh hoặc gom vùng.

### D. Slide vừa một trang + bỏ hero xanh (`backend/src/diagram_mcp/prettygraph.py`, `prompts.py`)
1. **Bỏ hero mặc định**: `render_slide` / `_compose_slide_png` / `_compose_slide_drawio` đổi mặc định
   `include_hero=False` (dòng 1024, 1240). Khi đó KHÔNG vẽ dải gradient xanh + brand/kicker/title to.
   Giữ caption nhỏ trong panel (không xanh) + legend.
2. **Một trang landscape 16:9, fit-inside (scale thích ứng)**: trong `_compose_slide_png`
   (1036-1054) đổi từ "fill width rồi cao động" sang **trang tỉ lệ slide 16:9** (suy từ `SLIDE_SIZE`
   theo tỉ lệ đặt tên `SLIDE_PAGE_RATIO`, KHÔNG hard-code 1152) và scale body **vừa cả 2 chiều**:
   `scale = min(max_w/body.w, max_h/body.h)` — body to/nhỏ tùy nội dung, luôn lọt trang, căn giữa,
   nền trắng. **Bỏ growth `2.05*SLIDE_SIZE`** (gây portrait dài tràn slide). Diagram nhiều node →
   tự thu nhỏ để vừa (không cắt node). `panel_fill_pct` tính theo trang; `slide_h` truyền sang
   `_compose_slide_drawio`.
3. **Hướng dẫn**: `prompts.py` (~459-462, 512, 601-602) + skills: mặc định gọi `render_slide(...,
   include_hero=False)`, `direction='LR'` landscape để vừa một trang 16:9; không truyền kicker/brand
   hero. Audit có thể nhắc nếu body bị thu quá nhỏ (quá nhiều node cho một trang) → giảm node/gom vùng.

## File chính sửa
- `backend/src/diagram_mcp/prettygraph.py` — `flow_layout`, auto-relax có điều kiện, lưới ngưỡng, spacing, **bỏ hero mặc định, fit một trang 16:9**
- `backend/src/diagram_mcp/tools.py` — default density, plan_style_sizes, audit, cảnh báo
- `backend/src/diagram_mcp/prompts.py` — recipe flow mặc định, yêu cầu liên kết
- `backend/skills/pro-style/SKILL.md` + `backend/skills/drawer/pro-style/SKILL.md` — ví dụ flow

## Verification
1. Render thử bằng prettygraph: `direction='LR'`, `flow_layout=True`, `include_hero=False`, ~22 node,
   vài vùng nhỏ (1-3 node) + 1-2 vùng lớn (≥4 node có `grid_cluster`), nối các vùng bằng cạnh thật.
   Mở `out.png`: xác nhận **(a) không còn dải xanh hero**, **(b) toàn bộ diagram VỪA trong một trang
   16:9 landscape**, **(c) cluster kích thước khác nhau + có đường nối rõ giữa vùng** — giống
   `diagram (12).png`, không còn band bằng nhau / portrait dài như `diagram (19).png`.
2. Render thử `density='poster'` (`flow_layout=False`) để xác nhận chế độ wall lưới-cứng vẫn hoạt động.
3. `python -m py_compile` cho 3 module; mở `out.drawio` kiểm tra hợp lệ + đúng kích thước một trang.
4. (Tùy chọn) chạy full pipeline qua agent với mô tả hệ thực để xác nhận tự ra flow linh hoạt + liên
   kết + vừa một trang, không hero.
