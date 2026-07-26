# Architecture Decision Records

Quyết định đã chốt, kèm bối cảnh và phương án đã loại. Đọc trước khi "sửa" thứ trông kỳ lạ — phần lớn chúng cố ý như vậy.

| # | Quyết định | Trạng thái |
|---|---|---|
| [0001](0001-memory-la-file-qdrant-la-tool.md) | Memory là file; Qdrant chỉ là tool truy xuất | accepted |
| [0002](0002-tat-general-purpose-subagent.md) | Tắt subagent `general-purpose` ngầm của deepagents | accepted |
| [0003](0003-native-drawio-engine.md) | Engine draw.io tất định; `DiagramSpec` thay vì nới `Blueprint` | accepted |
| [0004](0004-modal-sandbox-fail-closed.md) | Modal Sandbox cho code sinh ra, fail-closed | accepted |
| [0005](0005-cong-lint-ci-hep-co-chu-dich.md) | Cổng lint CI hẹp, phần còn lại chỉ báo cáo | accepted |
| [0006](0006-copilotkit-runtime-hop.md) | Hop Node CopilotKit runtime giữa browser và backend | accepted |
| [0007](0007-auth-resolve-phia-server-fail-closed.md) | Identity resolve phía server, fail-closed ở prod | accepted |
| [0008](0008-import-phang-tu-src.md) | Import phẳng từ `backend/src`; `backends.py` là module thật | accepted |

## Viết ADR mới

Đánh số tiếp theo, dùng khung ở `../instruction.md` Phụ lục C:

```markdown
# 00NN — <Quyết định>

**Ngày:** YYYY-MM-DD
**Trạng thái:** accepted | superseded by 00XX

## Bối cảnh
<Ràng buộc gì buộc phải quyết định lúc đó.>

## Quyết định
<Chọn gì.>

## Phương án đã loại
- <A> — loại vì …

## Hệ quả
<Cái gì trở nên khó hơn / dễ hơn.>
```

Quyết định bị thay thế thì **không xoá** — đổi trạng thái thành `superseded by 00XX` và để nguyên. Giá trị của ADR nằm ở chỗ nó ghi lại cái đã bị loại và vì sao.
