# 0006 — Chèn một hop Node (CopilotKit runtime) giữa browser và backend

**Ngày ghi lại:** 2026-07-26 (quyết định có từ trước, ADR hồi tố)
**Trạng thái:** accepted

## Bối cảnh

Frontend dùng CopilotKit v2 nói giao thức AG-UI. Backend Python đã phơi `POST /agui` và có thể phục vụ browser trực tiếp. Nhưng ba vấn đề xuất hiện:

1. Payload SSE mang file nhị phân base64 — PNG sơ đồ, PDF, PPTX, Excel WBS. Chúng làm phình stream và buộc client phải `atob` những khối rất lớn.
2. Cần theo dõi run đang chạy theo `threadId` để nối lại/huỷ đúng.
3. Cần kiểm tra toàn vẹn message (byte-identity của message người dùng cuối trước/sau chuẩn hoá) — thuộc về tầng giao thức, không thuộc về backend.

## Quyết định

Chạy `runtime/` — một service Node ESM dùng `@copilotkit/runtime` — như một hop riêng. Browser gọi `/api/copilotkit`; runtime gọi `POST /agui` của backend. **Backend không đổi gì.**

Runtime làm ba việc:
- **Artifact substitution** — thay `png_base64`, `pdf_base64`, `pptx_base64`, `wbs_xlsx_base64` bằng `ArtifactRef` phục vụ tại `GET /api/artifacts/:key`. `drawio` giữ inline vì cần nguyên văn trong URL fragment mở draw.io.
- **`PassthroughRunner`** — theo dõi run đang chạy theo `threadId`.
- **Kiểm tra toàn vẹn message** (`ASSERT_MESSAGE_INTEGRITY`).

Mọi thứ đi qua **same-origin**: nginx (prod) / vite proxy (dev) định tuyến `/api/copilotkit` và `/api/backend`. Header auth (`x-auth-request-email`, `x-auth-request-role`, `authorization`) được forward xuyên suốt.

## Phương án đã loại

- **Browser gọi thẳng `/agui`** — loại: mất chỗ để offload artifact và theo dõi run; và phải bake `VITE_BACKEND_URL` lúc build, hoặc mở CORS.
- **Hiện thực offload artifact trong backend Python** — loại: nó là quan tâm của tầng vận chuyển, không phải của agent; và CopilotKit runtime vốn đã ngồi đúng chỗ đó.
- **Bake `VITE_BACKEND_URL` lúc build frontend** — giữ lại làm override deprecated trong một release, nhưng đường mặc định là same-origin: URL tương đối chạy đúng ở mọi môi trường mà không cần build lại.

## Hệ quả

- **Dễ hơn:** payload SSE nhỏ; UI tải artifact qua URL bình thường (cache được, mở tab mới được); backend không phải biết gì về chuyện phân phối artifact.
- **Khó hơn — và đây là cái giá thật:** `runtime/` **stateful**. Map run và artifact store (LRU in-memory, 512 MB, TTL 30 phút) đều nằm trong process. Nghĩa là **chạy đúng một replica**. Scale out cần sticky session theo `threadId` cộng store dùng Redis. Ghi rõ trong `runtime/README.md`.
- Link artifact chết sau khi runtime restart hoặc sau TTL 30 phút. Đã biết, chấp nhận với quy mô nội bộ.
- Thêm một service phải deploy, và một chỗ nữa để đứt SSE nếu proxy bật buffering.
- `@ag-ui/client`/`@ag-ui/core` phải pin **cùng version chính xác** ở cả `frontend/` và `runtime/`, vì có một cast `as unknown as AbstractAgent` bắc qua khe lệch type-identity. `runtime/src/__tests__/agent-shape.test.ts` là chốt canh.
