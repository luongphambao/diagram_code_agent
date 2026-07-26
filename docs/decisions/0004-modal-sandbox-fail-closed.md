# 0004 — Modal Sandbox cho code sinh ra, fail-closed, không fallback về local

**Ngày ghi lại:** 2026-07-26 (quyết định có từ trước, ADR hồi tố)
**Trạng thái:** accepted

## Bối cảnh

Đường codegen sinh ra code Python (`diagrams`, Graphviz) rồi **thực thi** nó. Code đó do LLM viết, và LLM đọc dữ liệu do người dùng cung cấp — tài liệu upload, kết quả web research. Chạy nó trong process backend nghĩa là chạy code có thể bị tác động bởi kẻ tấn công trên chính host đang giữ khoá API.

## Quyết định

Thực thi trong **Modal Sandbox**, `block_network=True`, chọn bằng `SANDBOX_PROVIDER=modal` (mặc định).

`SANDBOX_PROVIDER=local` (subprocess) tồn tại **chỉ cho dev** và bị **từ chối cứng khi `APP_ENV=production`**.

**Không có try/except fallback từ Modal về local.** Modal chết thì render fail.

Seam là **file-based**: sandbox nhận/trả file (`out.png`, `out.dot`, `.drawio`), không phải một contract byte-in/byte-out đầy đủ.

Output của sandbox là **dữ liệu không tin cậy kể cả khi exit code 0** — `.drawio`, SVG, DOT, tên file, stdout đều phải qua validate trước khi phục vụ, nhúng vào PDF, hay import vào draw.io.

## Phương án đã loại

- **Docker-in-Docker, gVisor tự host, nsjail, Firecracker** — loại vì gánh nặng vận hành, cho một đội nội bộ không có SRE chuyên trách.
- **Fallback tự động Modal → local khi Modal lỗi** — loại: đúng lúc hạ tầng đang trục trặc lại là lúc chạy code không tin cậy trên host API. Một lần render fail rẻ hơn nhiều so với một lần thực thi lọt.
- **Contract byte-in/byte-out đầy đủ** — loại: phải sửa lại **mọi** call site đang đọc/ghi `out.png`/`out.dot`. Blast radius lớn hơn nhiều so với mục tiêu thật (cô lập việc thực thi). Seam theo file đạt mục tiêu bảo mật với thay đổi tối thiểu.
- **Chỉ tin exit code** — loại; xem mục "output không tin cậy" ở trên.

## Hệ quả

- **Dễ hơn:** sandbox bị compromise không đồng nghĩa credential bị lộ — khoá nằm ở process server, không bao giờ ở sandbox.
- **Khó hơn:** render phụ thuộc một dịch vụ ngoài. Cần `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET` để chạy test đụng render, hoặc set `SANDBOX_PROVIDER=local`. Đây là nguyên nhân của lỗi `AuthError: Token missing` hay gặp — xem `gotchas.md`.
- **Bẫy hạ tầng đã biết:** DNS proxy nhúng của Docker xử lý sai zone `*.w.modal.host` → render treo ~300s rồi fail. `docker-compose.yml` pin `dns: [8.8.8.8, 1.1.1.1]` trên service backend. Đừng xoá.
- Chế độ `local` không có isolation gì cả. Nó tồn tại được là nhờ dev có human-in-the-loop; đừng bao giờ để nó lọt lên môi trường có dữ liệu thật.
