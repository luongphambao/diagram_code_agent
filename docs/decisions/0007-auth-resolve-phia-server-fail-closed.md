# 0007 — Identity resolve ở phía server, fail-closed ở production

**Ngày ghi lại:** 2026-07-26 (quyết định có từ trước, ADR hồi tố)
**Trạng thái:** accepted

## Bối cảnh

`/agui` từng đọc `userEmail` và `userRole` **từ JSON body của request**. Vì role quyết định ai được duyệt gate (`ROLE_GATE_PERMISSIONS`), bất kỳ caller nào cũng có thể tự nhận là approver và duyệt tech stack, blueprint, hay `send_email` gửi cho khách.

Bối cảnh ràng buộc: đây là hệ thống **nội bộ, một tổ chức tin cậy**. Không phải SaaS đa tenant.

## Quyết định

Identity **luôn** được resolve ở phía server (`security/auth.py`), không bao giờ từ body request. Ba chế độ:

- `AUTH_MODE=header` — đọc `AUTH_HEADER_EMAIL`/`AUTH_HEADER_ROLE` (mặc định `X-Auth-Request-Email`/`X-Auth-Request-Role`), do một reverse proxy kiểu oauth2-proxy đặt vào.
- `AUTH_MODE=bearer` — đối chiếu `AUTH_BEARER_TOKENS`.
- `AUTH_MODE=none` — chỉ dev, **bị từ chối cứng khi `APP_ENV=production`**.

Kèm theo: **quyền sở hữu thread** (`security/ownership.py`). Caller đã xác thực đầu tiên chạm vào một `thread_id` sẽ claim nó; người khác nhận **404** (không phải 403 — không tiết lộ sự tồn tại của thread). Thread chưa ai sở hữu (`owner_email = ''`) vẫn hiện với mọi người, để lần triển khai đầu không khoá người dùng cũ ra ngoài.

Cùng tư thế fail-closed áp cho CORS (`config/cors.py`) và sandbox provider (`runtime/sandbox/provider.py`): cấu hình không an toàn ở `APP_ENV=production` thì **từ chối khởi động**, không cảnh báo rồi chạy tiếp.

## Phương án đã loại

- **Auth SaaS đa tenant đầy đủ** (org, invite, RBAC theo tài nguyên) — loại tường minh: ngoài phạm vi cho một công cụ nội bộ. Ranh giới tin cậy là tổ chức.
- **Tin body request nhưng validate role theo allowlist** — loại: vẫn là client tự khai identity; allowlist chỉ giới hạn *ai được giả mạo*.
- **Cảnh báo thay vì từ chối khi cấu hình không an toàn ở prod** — loại: cảnh báo lúc khởi động không ai đọc. Fail-closed biến lỗi cấu hình thành sự cố deploy, chứ không thành sự cố bảo mật.
- **403 cho thread không sở hữu** — loại vì 403 xác nhận thread đó tồn tại.

## Hệ quả

- **Dễ hơn:** quyền duyệt gate có ý nghĩa thật; log/decision record gắn được với người thật.
- **Khó hơn:** dev cần đặt `AUTH_MODE=none` (hoặc gửi header) để chạy cục bộ, và deploy prod **bắt buộc** phải có một tầng auth phía trước đặt header vào. Không thể "tạm chạy prod chưa có auth".
- Endpoint mới nào đụng `thread_id` **phải** gọi `ensure_owner` — không có middleware nào làm hộ. Đây là điểm dễ quên nhất khi thêm router.
- Node runtime và nginx phải forward `authorization` + `x-auth-request-*`. Thêm hop proxy nào ở giữa mà quên forward là mọi request thành ẩn danh.
