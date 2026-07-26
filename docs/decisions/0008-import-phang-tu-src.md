# 0008 — Import phẳng từ `backend/src`, và `backends.py` phải ở lại là module thật

**Ngày ghi lại:** 2026-07-26 (quyết định có từ trước, ADR hồi tố)
**Trạng thái:** accepted

## Bối cảnh

Backend từng là vài file phẳng lớn (`agent.py` 1544 dòng, `tools.py`, `config.py`) trong `backend/src`, import bằng tên top-level: `import backends`, `from tools import ...`. Đợt refactor modular chia chúng thành các package (`agent/`, `tools/`, `domain/*`, `runtime/`, `memory/`, `session/`), làm **thuần cấu trúc, không đổi hành vi**.

Đổi luôn sang import theo package đủ chuẩn (`from domain.wbs import wbs_tools`) sẽ đụng vào hàng trăm call site và mọi file test — biến một thay đổi an toàn thành một thay đổi rủi ro.

## Quyết định

Giữ **import phẳng top-level**. `backend/src` là import root (`[tool.hatch.build] sources = ["src"]`), và các thư mục domain nằm **thẳng** trên `sys.path` qua `[tool.pytest.ini_options].pythonpath` (`src`, `src/domain/{diagram,deck,reporting,wbs,validation}`), có `[tool.pyright].extraPaths` phản chiếu.

Nên `import wbs_tools` chạy được dù file nằm ở `domain/wbs/wbs_tools.py`.

Hai luật đi kèm:

1. **`backends.py` phải ở lại là module thật, top-level** — không được biến thành shim re-export.
2. **Không được có `backend/src/agent.py`** — một module phẳng sẽ *che* package `agent/` và trở thành code chết mà người ta vẫn sửa nhầm. Test canh: `tests/test_no_legacy_agent_module.py`.

## Phương án đã loại

- **Import theo package đủ chuẩn** — loại **cho đợt này**. Đúng về mặt kiến trúc nhưng trộn một thay đổi rủi ro vào một refactor cấu trúc thuần. Có thể làm sau, thành một change riêng, có test đi kèm.
- **Shim re-export ở đường dẫn cũ cho mọi module đã di chuyển** — dùng cho phần lớn module (`csm.py`, `evidence.py`, `email_tools.py`… đều là shim 5–27 dòng), nhưng **loại cho `backends.py`**: test monkeypatch trực tiếp `backends.WORKSPACE` / `backends._current_workspace`, và shim tách đôi module globals nên patch mất tác dụng **trong im lặng**. Bài học này đã cắn nhiều lần trong đợt refactor.
- **Xoá luôn `src/config.py` và `src/runtime/backends.py`** (hai bản cũ bị package che) — chưa làm; chúng là code chết vô hại. Nhưng chúng **là** bẫy: sửa vào đó thì không có hiệu lực gì. Ghi trong `gotchas.md`.

## Hệ quả

- **Dễ hơn:** refactor cấu trúc không đụng call site; test và import cũ vẫn chạy.
- **Khó hơn — và phải nhớ:** thêm subpackage `domain/` mới thì phải thêm đường dẫn vào **cả** `pythonpath` **và** `extraPaths`. Quên là pytest không collect được và pyright báo lỗi giả.
- Tên module là **không gian phẳng toàn cục**. Hai file cùng tên ở hai thư mục domain khác nhau sẽ va nhau. Đặt tên module phải đủ đặc trưng.
- Bất biến ContextVar: `_current_workspace` chỉ được định nghĩa ở **đúng một** module. Hai bản = rò rỉ workspace chéo thread. Canh bằng `tests/test_workspace_isolation.py`.
