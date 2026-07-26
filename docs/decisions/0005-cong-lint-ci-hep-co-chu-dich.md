# 0005 — Cổng lint CI hẹp, tập trung vào bug; phần còn lại chỉ báo cáo

**Ngày ghi lại:** 2026-07-26 (quyết định có từ trước, ADR hồi tố)
**Trạng thái:** accepted

## Bối cảnh

Khi dựng CI, codebase đã có sẵn ~500 hit `ruff --select ALL` và 228 lỗi pyright — phần lớn đến từ việc deepagents/LangChain là API duck-typed mà type checker không mô tả nổi. Bật chặn từ ngày đầu sẽ làm **mọi** PR đỏ vì nợ kỹ thuật không liên quan, và kết cục quen thuộc là cả đội học cách bỏ qua CI.

## Quyết định

Tách "cổng" khỏi "báo cáo".

**Chặn:**
- `ruff format --check .`
- `ruff check .` với `select = ["E9", "F821", "F822", "F823"]` — lỗi cú pháp và tên không tồn tại. Toàn là bug thật, không phải chuyện phong cách.
- `pytest tests/ -q --cov=src --cov-fail-under=60` (đo được 65% lúc thêm vào).
- `uv sync --frozen` — lockfile cũ phải làm đỏ CI.
- Assertion `backend/.env` **không** có trong Docker image.
- Gitleaks.

**Không chặn (chỉ báo cáo):** `ruff check --select ALL --exit-zero`, `pyright`, pip-audit, npm audit, Trivy.

`line-length = 110`, `target-version = "py311"`.

## Phương án đã loại

- **`select = ["ALL"]` chặn ngay** — loại: 500 hit tồn đọng, mọi PR đỏ vì lý do không liên quan.
- **Pyright chặn** — loại: 228 lỗi phần lớn là hệ quả của API duck-typed; sửa hết nghĩa là bọc thư viện bằng type stub, chi phí không tương xứng lợi ích.
- **Không có cổng nào cả** — loại: `F821` (tên không tồn tại) là loại lỗi thật sự làm chết production và ruff bắt được trong một giây.
- **Sửa hết nợ trước rồi mới bật CI** — loại: nợ sẽ không bao giờ được ưu tiên, và trong lúc chờ thì không có CI nào cả.

## Hệ quả

- **Dễ hơn:** CI xanh nghĩa là "không có bug rõ ràng nào mới", tín hiệu này đáng tin nên không ai bỏ qua. Báo cáo không-chặn vẫn cho thấy nợ đang tăng hay giảm.
- **Khó hơn:** vi phạm phong cách vẫn lọt vào. Chấp nhận — `ruff format` đã đảm bảo phần lớn tính nhất quán.
- **Đừng làm mấy việc sau, chúng đánh thẳng vào mục đích của quyết định này:**
  - hạ `--cov-fail-under=60` để làm build xanh;
  - đổi `uv sync --frozen` thành có fallback;
  - tắt assertion `.env`-không-có-trong-image;
  - mở rộng blocking select vì "trông sạch hơn".
- Muốn siết dần thì thêm **một** rule mới vào blocking set **sau khi** đã dọn sạch vi phạm của rule đó, trong một PR riêng.
