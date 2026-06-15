# Fix: Màn hình đen khi gate approval render (React crash)

## Context

Sau khi nâng cấp backend schema (trade-off matrix, Well-Architected pillars, NFR mapping — theo plan `lexical-cooking-marble.md`), frontend bị **đen toàn màn hình mỗi khi một bước hoàn thành** và gate approval render ra.

### Root cause (đã xác minh chính xác)

1. **Crash trực tiếp**: Backend `tools.py:1062-1082` đổi `alternatives` của mỗi tech-stack layer từ `string[]` thành object `{name, why_rejected, criteria?}`. Backend `server.py` `_card_for()` / `_normalize_tech_stack()` (dòng ~443-490) truyền nguyên object này vào card `techstack_approval`. Frontend [TechStackApproval.tsx:69-75](frontend/src/components/TechStackApproval.tsx#L69-L75) render `{alt}` trực tiếp làm React child (và `key={alt}`) → React throw **"Objects are not valid as a React child"**.

2. **Không có ErrorBoundary**: `main.tsx` render `<App/>` trần. Khi một component throw lúc render, React unmount **toàn bộ** cây → chỉ còn `body { background: #0f1117 }` (index.css) → màn hình đen tuyền, không có thông báo lỗi nào.

Crash xảy ra đúng lúc bước "propose tech stack" xong → khớp 100% triệu chứng "mỗi khi xong một bước nó render ra thì đen".

## Changes

### 1. `frontend/src/hooks/useDiagramAgent.ts` — cập nhật types khớp backend

- Thêm interface `TechAlternative { name: string; why_rejected?: string; criteria?: Record<string, number> }`.
- `TechStackLayer.alternatives: Array<string | TechAlternative>` (chấp nhận cả 2 dạng — conversation cũ trong DB vẫn còn dạng string).
- `Blueprint`: thêm optional `pillar_coverage?: Record<string, { addressed_by?: string[]; gaps?: string[] }>`, `nfr_mapping?: Array<{ nfr: string; mechanism?: string; node_ids?: string[] }>`.

### 2. `frontend/src/components/TechStackApproval.tsx` — fix crash site (dòng 67-78)

```tsx
{info.alternatives.map((alt, i) => {
  const name = typeof alt === "string" ? alt : alt?.name ?? "";
  const why = typeof alt === "object" ? alt?.why_rejected : undefined;
  return (
    <span key={`${name}-${i}`} title={why || undefined} className="...">
      {name}
    </span>
  );
})}
```
- Tooltip `title` hiển thị `why_rejected` (tận dụng data mới, không thêm UI phức tạp).
- Guard `Array.isArray(info.alternatives)` thay cho check hiện tại.

### 3. `frontend/src/components/ErrorBoundary.tsx` — MỚI (safety net hệ thống)

Class component chuẩn React với `componentDidCatch` / `getDerivedStateFromError`:
- Fallback UI: card nền tối hiển thị "Something went wrong rendering the UI" + message lỗi + nút "Reload".
- Mục đích: mọi crash render trong tương lai hiện **thông báo lỗi đọc được** thay vì màn hình đen câm.

### 4. `frontend/src/main.tsx` — bọc `<ErrorBoundary><App/></ErrorBoundary>`

Có thể bọc thêm quanh `ChatSidebar` và `DiagramCanvas` trong `App.tsx` để crash 1 panel không kéo sập panel kia (2 boundary nhỏ, fallback gọn).

### 5. (Nhỏ, cùng nhóm) `frontend/src/components/BlueprintApproval.tsx`

Blueprint card hiện không crash nhưng "mù" với data mới. Thêm 2 dòng tóm tắt compact (chỉ khi có data):
- `nfr_mapping`: "NFRs mapped: N" + danh sách nfr ngắn.
- `pillar_coverage`: chips 6 pillar, pillar có gaps đánh dấu màu amber.

Không đụng BlueprintViewer (chỉ là preview phụ, không crash).

## Rebuild & Deploy (Docker)

App chạy qua Docker Compose, frontend là static build (Vite bake lúc build):

```powershell
docker compose build frontend
docker compose up -d frontend
```

## Verification

1. `npm run build` trong `frontend/` (tsc phải pass với types mới).
2. Rebuild + restart container như trên, hard-refresh trình duyệt (`Ctrl+Shift+R`).
3. Chạy flow thật: gửi yêu cầu kiến trúc → đợi đến gate **Tech Stack Recommendation** → card phải render đủ layers + chips alternatives (hover thấy why_rejected), **không đen màn hình**.
4. Tiếp tục approve → gate Blueprint render bình thường (kèm tóm tắt NFR/pillar nếu có).
5. Test ErrorBoundary: tạm không cần — chỉ cần xác nhận app render bình thường; boundary là passive safety net.

## Out of scope

- Render đầy đủ trade-off matrix (criteria scores 1-5 dạng bảng) trong gate card — data đã có trong payload, có thể làm sau nếu muốn.
- Các warning validator (pillar gaps, unmapped NFRs) hiển thị tại gate — backend đã trả trong tool result, chưa wire lên UI.
