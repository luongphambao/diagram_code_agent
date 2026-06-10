# Phân tích kiến trúc next-ai-draw-io

> Phân tích sâu codebase `next-ai-draw-io` — luồng AI agent vẽ diagram, xử lý icon, MCP server và cơ chế phối hợp.

---

## Mục lục

1. [Tổng quan kiến trúc](#1-tổng-quan-kiến-trúc)
2. [Luồng end-to-end: Prompt → Diagram](#2-luồng-end-to-end-prompt--diagram)
3. [4 Tools của AI Agent](#3-4-tools-của-ai-agent)
4. [System Prompts](#4-system-prompts)
5. [Client-side Tool Handlers](#5-client-side-tool-handlers)
6. [Xử lý XML: wrap, validate, auto-fix](#6-xử-lý-xml-wrap-validate-auto-fix)
7. [Icon & Shape Libraries](#7-icon--shape-libraries)
8. [MCP Server (packages/mcp-server)](#8-mcp-server-packagesmcp-server)
9. [VLM Validation](#9-vlm-validation)
10. [Điểm mạnh & Điểm yếu](#10-điểm-mạnh--điểm-yếu)
11. [Cơ hội cải thiện cho agent mới](#11-cơ-hội-cải-thiện-cho-agent-mới)

---

## 1. Tổng quan kiến trúc

```
┌─────────────────────────────────────────────────────────────┐
│                    next-ai-draw-io (Next.js)                  │
│                                                               │
│  ┌──────────────────┐         ┌────────────────────────────┐ │
│  │   Chat Panel     │  POST   │   /api/chat (route.ts)     │ │
│  │  (React)         │────────>│   streamText() + tools     │ │
│  │                  │  SSE    │   AI SDK (Vercel)          │ │
│  │  + Tool Handlers │<────────│                            │ │
│  └────────┬─────────┘         └────────────────────────────┘ │
│           │ XML                                               │
│           ▼                                                   │
│  ┌──────────────────┐                                         │
│  │  DiagramContext  │                                         │
│  │  drawioRef.load()│                                         │
│  └────────┬─────────┘                                         │
│           │ iframe postMessage                                │
│           ▼                                                   │
│  ┌──────────────────┐                                         │
│  │  embed.diagrams  │ ← draw.io (react-drawio)               │
│  │  .net iframe     │   renders mxGraph XML                  │
│  └──────────────────┘                                         │
└─────────────────────────────────────────────────────────────┘
```

**Tech stack:**
- **Framework:** Next.js 16 + React 19
- **AI SDK:** Vercel AI SDK v6 (`streamText`, `useChat`, `useObject`)
- **Diagram renderer:** `react-drawio` (iframe embed tới `embed.diagrams.net`)
- **Diagram format:** draw.io mxGraph XML
- **Validation:** VLM (vision model) + structural XML validation
- **Observability:** Langfuse tracing

---

## 2. Luồng end-to-end: Prompt → Diagram

```
User types prompt
      │
      ▼
[chat-panel.tsx:830-862]
  → onFetchChart() — snapshot XML hiện tại
  → xmlSnapshotsRef — lưu lịch sử multi-turn
      │
      ▼
[/api/chat POST] — gửi:
  messages, currentXML, previousXML,
  sessionId (Langfuse), model config
      │
      ▼
[route.ts:500-776] streamText()
  ├── system prompt (getSystemPrompt)
  ├── allMessages (history + XML context)
  ├── stopWhen: stepCountIs(5)      ← max 5 tool calls
  ├── experimental_repairToolCall   ← tự sửa JSON bị cắt
  └── tools: [display_diagram, edit_diagram,
              append_diagram, get_shape_library]
      │
      ▼ (streaming tool calls qua SSE)
[use-diagram-tool-handlers.ts]
  ├── display_diagram  → wrapWithMxFile → loadDiagram
  ├── edit_diagram     → applyDiagramOperations → loadDiagram
  ├── append_diagram   → gộp XML fragment → loadDiagram
  └── get_shape_library → (server-side, trả docs)
      │
      ▼
[diagram-context.tsx] loadDiagram()
  → validateAndFixXml()
  → drawioRef.current.load({ xml })
      │
      ▼
draw.io iframe renders diagram
      │
      ▼ (nếu VLM validation bật)
captureValidationPng() → validateDiagram()
  → nếu fail: gửi error feedback → AI retry (max 3 lần)
```

---

## 3. 4 Tools của AI Agent

Tất cả định nghĩa trong [`app/api/chat/route.ts:606-769`](next-ai-draw-io/app/api/chat/route.ts).

### 3.1 `display_diagram` — tạo diagram mới

```typescript
// route.ts:608-644
display_diagram: {
    description: "Display a diagram on draw.io. Pass ONLY the mxCell elements...",
    inputSchema: z.object({
        xml: z.string()  // Chỉ mxCell elements, KHÔNG có wrapper
    }),
    // Không có execute → client-side handler
}
```

**AI phải sinh:** chỉ `<mxCell .../>` elements, không có `<mxfile>`, `<root>`, `<mxGraphModel>`.  
**Client tự thêm:** wrapper `<mxfile><diagram><mxGraphModel><root>...`

### 3.2 `edit_diagram` — sửa diagram theo cell ID

```typescript
// route.ts:646-686
edit_diagram: {
    inputSchema: z.object({
        operations: z.array(z.object({
            operation: z.enum(["update", "add", "delete"]),
            cell_id: z.string(),
            new_xml: z.string().optional(),
        }))
    })
}
```

**Flow:** fetch XML hiện tại → `applyDiagramOperations()` (DOM-based) → validate → load.

### 3.3 `append_diagram` — tiếp tục XML bị cắt

```typescript
// route.ts:688-706
append_diagram: {
    description: "Continue generating diagram XML when previous was truncated...",
    inputSchema: z.object({ xml: z.string() })
}
```

**Khi nào dùng:** `display_diagram` bị cắt giữa chừng (hit token limit) → AI gọi `append_diagram` để tiếp tục. Client gộp các fragment lại.

### 3.4 `get_shape_library` — tra cứu icon syntax (**server-side**)

```typescript
// route.ts:708-769
get_shape_library: {
    inputSchema: z.object({ library: z.string() }),
    execute: async ({ library }) => {
        // Đọc /docs/shape-libraries/{library}.md
        // Trả về markdown docs với syntax chính xác
    }
}
```

**Đây là tool DUY NHẤT có `execute` server-side.** AI phải gọi trước khi dùng bất kỳ icon nào.

---

## 4. System Prompts

### 4.1 Lựa chọn prompt theo model

```typescript
// lib/system-prompts.ts:375-410
function getSystemPrompt(modelId, minimalStyle) {
    // Extended (4400 tokens): cho claude-opus-4-5, claude-haiku-4-5
    // Default (1900 tokens): cho mọi model khác
    let prompt = EXTENDED_PROMPT_MODEL_PATTERNS.some(p => modelId.includes(p))
        ? EXTENDED_SYSTEM_PROMPT
        : DEFAULT_SYSTEM_PROMPT

    // Prepend MINIMAL_STYLE nếu bật, hoặc append STYLE_INSTRUCTIONS
    prompt = minimalStyle ? MINIMAL_STYLE + prompt : prompt + STYLE_INSTRUCTIONS
    return prompt.replace("{{MODEL_NAME}}", modelName)
}
```

### 4.2 Layout constraints quan trọng

```
- x: 0-800, y: 0-600 (single page viewport)
- Container max width: 700px, max height: 550px
- Start at margins: x=40, y=40
```

### 4.3 Edge routing rules (7 rules)

1. Nhiều edges giữa 2 node KHÔNG được chung path
2. Bidirectional A↔B dùng OPPOSITE sides
3. **Luôn** specify `exitX, exitY, entryX, entryY`
4. Route AROUND obstacles, KHÔNG xuyên qua
5. Lên kế hoạch layout TRƯỚC khi sinh XML
6. Dùng nhiều waypoints cho complex routing
7. Natural connection points (không phải corners)

**Waypoint example:**
```xml
<mxCell style="edgeStyle=orthogonalEdgeStyle;..." edge="1">
    <mxGeometry relative="1" as="geometry">
        <Array as="points">
            <mxPoint x="750" y="80"/>
            <mxPoint x="750" y="150"/>
        </Array>
    </mxGeometry>
</mxCell>
```

### 4.4 Icon rules (critical)

```
get_shape_library TRƯỚC KHI dùng bất kỳ icon library nào.
KHÔNG ĐƯỢC đoán syntax icon — luôn look it up first.
```

Đây là **nguyên nhân gốc rễ icon bị broken**: system prompt chỉ là lời nhắc, không có cơ chế enforce. AI vẫn có thể bỏ qua và đoán sai.

---

## 5. Client-side Tool Handlers

File: [`hooks/use-diagram-tool-handlers.ts`](next-ai-draw-io/hooks/use-diagram-tool-handlers.ts)

### 5.1 `handleDisplayDiagram` flow

```
Nhận xml từ AI
    │
    ▼
isMxCellXmlComplete(xml)?
    ├── NO → store partial, request append_diagram
    └── YES
        │
        ▼
wrapWithMxFile(xml) → fullXml
        │
        ▼
onDisplayChart(fullXml) [validate + load]
        │
        ├── ERROR → trả error về model
        └── OK
            │
            ▼
VLM validation bật? [captureValidationPng + validateDiagram]
            ├── PASS → success
            ├── FAIL + retries < 3 → gửi feedback → AI retry
            └── FAIL + retries >= 3 → accept anyway ("skipped")
```

**Validation states:** `capturing → validating → success | success_with_warnings | failed | skipped | error`

### 5.2 `handleEditDiagram` flow

```
Lấy XML hiện tại (3 priority: original ref > cached > fetch từ iframe)
    │
    ▼
applyDiagramOperations(currentXml, operations)
    │   [DOM-based: build cellMap → add/update/delete]
    ▼
Có errors? → trả error + current XML về model
    │
    ▼
onDisplayChart(editedXml) → validate
    │
    ▼
Success → onExport() + return success
```

### 5.3 `handleAppendDiagram` flow

```
Kiểm tra fragment có phải "fresh start"? (bắt đầu bằng <mxGraphModel>, <root>, ...)
    ├── YES → error: "bạn đang restart thay vì tiếp tục"
    └── NO
        │
        ▼
Gộp: partialXml += xml
        │
        ▼
isMxCellXmlComplete(partialXml)?
        ├── YES → wrapWithMxFile → validate → display
        └── NO  → "vẫn chưa xong, gọi append_diagram nữa"
```

---

## 6. Xử lý XML: wrap, validate, auto-fix

File: [`lib/utils.ts`](next-ai-draw-io/lib/utils.ts)

### 6.1 `wrapWithMxFile()` — thêm wrapper

AI chỉ sinh mxCell elements. Client thêm toàn bộ structure:

```typescript
// lib/utils.ts:326-371
wrapWithMxFile(xml) {
    const ROOT_CELLS = '<mxCell id="0"/><mxCell id="1" parent="0"/>'
    
    // Handle: bare mxCells | <root> | <mxGraphModel> | <mxfile> đã có
    // Strip trailing LLM wrapper tags (Anthropic, DeepSeek, etc.)
    // Remove root cells (id="0","1") nếu AI lỡ thêm
    
    return `<mxfile><diagram name="Page-1" id="page-1">
        <mxGraphModel><root>
            ${ROOT_CELLS}${content}
        </root></mxGraphModel>
    </diagram></mxfile>`
}
```

### 6.2 `isMxCellXmlComplete()` — truncation detection

```typescript
// lib/utils.ts:66-87
// Tìm vị trí cuối cùng của /> hoặc </mxCell>
// Kiểm tra suffix sau đó có phải chỉ closing tags không
// Regex: /^(\s*<\/[^>]+>)*\s*$/
```

### 6.3 `validateMxCellStructure()` — 10 loại lỗi

1. CDATA wrapper ở root
2. Duplicate structural attributes (`edge`, `parent`, `source`, `target`, `vertex`)
3. Unescaped `<` trong attribute values
4. Duplicate IDs
5. Tag mismatches (unclosed/mismatched)
6. Invalid character references (`&#xNN;`)
7. Invalid comment syntax (`--` inside comments)
8. Invalid entity references (chỉ cho phép: lt, gt, amp, quot, apos)
9. Empty id attributes
10. Nested mxCell tags

### 6.4 `autoFixXml()` — 27-step auto-repair

| Nhóm | Fix |
|------|-----|
| Encoding | JSON-escaped XML, CDATA removal |
| Structure | Strip trailing LLM tags, remove text before XML |
| Attributes | Duplicate attr removal, space fixes, quote fixes |
| Entities | `&` → `&amp;`, double-escaped entities, malformed quotes |
| Tags | Malformed closing tags, typos (`<Cell>` → `<mxCell>`) |
| Cleanup | Foreign tag removal, unclosed/extra tags, trailing garbage |
| IDs | Nested mxCell flattening, duplicate ID renaming, empty ID generation |
| Nuclear | Aggressive cell dropping (drop unfixable cells iteratively) |

**Valid draw.io tags:**
```
mxfile, diagram, mxGraphModel, root, mxCell, mxGeometry,
mxPoint, Array, Object, mxRectangle
```

### 6.5 `applyDiagramOperations()` — DOM-based edit

```typescript
// lib/utils.ts:498-731
// Build cellMap: Map<id, Element>
// update: findById → replaceChild (validate id match)
// add: check không duplicate → appendChild  
// delete: cascade delete (descendants + referencing edges + edge labels)
//         bảo vệ root cells id="0", id="1"
```

---

## 7. Icon & Shape Libraries

File: [`docs/shape-libraries/`](next-ai-draw-io/docs/shape-libraries/)

### 7.1 Tổng quan 33 thư viện

| Category | Libraries | Shapes |
|----------|-----------|--------|
| Cloud Providers | aws4, azure2, gcp2, alibaba_cloud, openstack, digitalocean, salesforce | ~2,400 |
| Networking | cisco19, network, arista, kubernetes, rack, vvd | ~479 |
| Business | bpmn, eip, lean_mapping | ~88 |
| General | flowchart, basic, arrows2, infographic, sitemap | ~177 |
| Enterprise | citrix, sap, mscae, atlassian | ~294 |
| Engineering | fluidpower, electrical, pid, cabinets, floorplan | ~411 |
| Icons | webicons, material_design | ~477 |
| **Total** | **33** | **~4,281** |

### 7.2 AWS4 (1,032 shapes) — syntax phức tạp nhất

```xml
<!-- Resource icon: cần CẢ HAI shape + resIcon -->
<mxCell value="EC2"
    style="shape=mxgraph.aws4.resourceIcon;
           resIcon=mxgraph.aws4.ec2;
           fillColor=#ED7100;strokeColor=#ffffff;
           verticalLabelPosition=bottom;verticalAlign=top;align=center;"
    vertex="1" parent="1">
    <mxGeometry x="0" y="0" width="60" height="60" as="geometry"/>
</mxCell>

<!-- Simple shape (không phải resource icon) -->
<mxCell style="shape=mxgraph.aws4.vpc;fillColor=#232F3D;" .../>
```

**Đây là nguồn lỗi chính:** AI thường quên `resIcon`, hoặc nhầm giữa resource icon và simple shape.

### 7.3 Azure2 (648 shapes) — image path

```xml
<mxCell value="VM"
    style="image;aspect=fixed;
           image=img/lib/azure2/compute/Virtual_Machine.svg;
           verticalLabelPosition=bottom;verticalAlign=top;align=center;"
    vertex="1" parent="1">
    <mxGeometry x="0" y="0" width="60" height="60" as="geometry"/>
</mxCell>
```

**Lưu ý:** Dùng relative path `img/lib/azure2/...` — chỉ hoạt động trong draw.io embed context.

### 7.4 GCP2 (298 shapes) — mxgraph prefix

```xml
<mxCell style="shape=mxgraph.gcp2.bigquery;
               fillColor=#4285F4;strokeColor=none;..." .../>
```

### 7.5 Material Design (300 icons) — CDN dependency

```xml
<mxCell
    style="image;aspect=fixed;html=1;
           image=https://fonts.gstatic.com/s/i/materialicons/settings/v6/24px.svg;..."
    vertex="1" parent="1">
    <mxGeometry x="0" y="0" width="48" height="48" as="geometry"/>
</mxCell>
```

**Vấn đề:** Phụ thuộc CDN `fonts.gstatic.com` — sẽ fail nếu offline hoặc CDN thay đổi URL.

### 7.6 Tại sao icon bị broken — phân tích gốc rễ

| Nguyên nhân | Chi tiết |
|-------------|----------|
| **Syntax phức tạp** | AWS cần 2 attributes (`shape` + `resIcon`); AI hay quên một trong hai |
| **Chỉ là lời nhắc** | System prompt nói "gọi get_shape_library trước", nhưng AI có thể bỏ qua |
| **Không có validation** | XML validator không check icon name tồn tại hay không |
| **Azure path** | Relative path chỉ hoạt động trong draw.io embed, không portable |
| **Material CDN** | URL CDN có thể fail (offline, CORS, URL thay đổi) |
| **VLM không phát hiện** | Validation schema không có category "icon_rendering" |

---

## 8. MCP Server (`packages/mcp-server`)

### 8.1 Kiến trúc tổng thể

```
Claude Desktop/Cursor
       │ stdio (MCP protocol)
       ▼
@next-ai-drawio/mcp-server (Node.js)
       │ HTTP (localhost:6002)
       ▼
Embedded HTTP Server
       │ poll (mỗi 2s)
       ▼
Browser (draw.io embed iframe)
```

### 8.2 State management

```typescript
// http-server.ts
interface SessionState {
    xml: string
    version: number
    lastUpdated: Date
    svg?: string          // cached SVG từ browser
    syncRequested?: number // timestamp, browser cần push state
    exportFormat?: "png" | "svg"
    exportData?: string   // base64 data từ browser export
}

// stateStore: Map<sessionId, SessionState>
// Session TTL: 60 phút
```

### 8.3 State sync mechanism

```
MCP calls get_diagram:
    requestSync(sessionId) → đánh dấu cần sync
    waitForSync(sessionId, 3000ms) → block chờ browser

Browser polling (mỗi 2s):
    GET /api/state → thấy syncRequested
    → postMessage({action: 'export', format: 'xml'}) → draw.io iframe
    → draw.io trả XML → POST /api/state {xml, svg}
    → syncRequested cleared

MCP tool nhận được fresh state.
```

### 8.4 Export pipeline

```
export_diagram(format=png/svg):
    setState(exportFormat = "png")
    
Browser polling:
    thấy exportFormat → postMessage({action:'export', format:'png', scale:2})
    → draw.io iframe render + encode base64
    → POST /api/state {exportData: "data:image/png;base64,..."}
    
MCP server:
    waitForSync(sessionId, 10000ms)
    → decode base64 → writeFile
```

**Critical:** PNG/SVG export **BẮT BUỘC có browser tab mở**. Headless server = không export được PNG/SVG. Chỉ `export_diagram(format=drawio)` (ghi XML thuần) không cần browser.

### 8.5 5 Tools của MCP server

| Tool | Mô tả | Server-side requirements |
|------|--------|--------------------------|
| `start_session` | Mở browser, tạo session | Cần `open` package |
| `create_new_diagram(xml)` | Tạo mới từ mxGraphModel XML | Không cần browser |
| `edit_diagram(operations[])` | Update/add/delete by cell ID | Cần get_diagram trước (30s TTL) |
| `get_diagram()` | Fetch fresh XML từ browser | Cần browser mở (sync) |
| `export_diagram(path, format)` | Lưu file | PNG/SVG cần browser; drawio không cần |

### 8.6 Single-session limitation

```typescript
// index.ts:55-60
// Server giữ currentSession in-process (một session duy nhất)
let currentSession: { id: string; xml: string; version: number; ... } | null = null
```

**Hậu quả:** Mỗi process chỉ server **một session** — không an toàn cho multi-tenant.

### 8.7 `validateAndFixXml()` trong MCP server

Tương tự `lib/utils.ts` của Next.js app — 27-step auto-repair, valid draw.io tags set, truncation detection.

---

## 9. VLM Validation

### 9.1 Flow

```typescript
// hooks/use-validate-diagram.ts
// Dùng useObject() với ValidationResultSchema

// hooks/use-diagram-tool-handlers.ts:213-356
if (enableVlmValidation) {
    await delay(100)  // chờ diagram render xong
    capturedPngData = await captureValidationPng()  // PNG từ draw.io iframe
    result = await validateDiagram(capturedPngData, sessionId)
    
    if (!result.valid && retryCount < MAX_VALIDATION_RETRIES) {
        // Gửi error feedback → AI tự sửa và gọi display_diagram lại
        retryCount++
    }
}
```

### 9.2 Validation schema

```typescript
// lib/validation-schema.ts
ValidationResultSchema = z.object({
    valid: z.boolean(),
    issues: z.array(z.object({
        type: z.enum(["overlap", "edge_routing", "text", "layout", "rendering"]),
        severity: z.enum(["critical", "warning"]),
        description: z.string(),
    })),
    suggestions: z.array(z.string()),
})
```

### 9.3 Vấn đề với icon validation

Schema có type `"rendering"` nhưng VLM validation prompt không hướng dẫn detect icon cụ thể.  
→ Blank icon box thường pass validation (trông như ô trống, không phải lỗi rõ ràng).

---

## 10. Điểm mạnh & Điểm yếu

### Điểm mạnh

| Aspect | Chi tiết |
|--------|----------|
| **XML robustness** | 27-step auto-fix; truncation repair; cascade delete; LLM wrapper tag stripping |
| **Layout chất lượng** | Edge routing rules rõ ràng; waypoint patterns; viewport constraints |
| **Multi-turn editing** | edit_diagram theo cell ID — không mất state người dùng |
| **Multi-provider** | 23 AI providers; reasoning model support cho mọi provider |
| **Multi-step flow** | append_diagram xử lý output bị cắt; max 5 steps |
| **VLM validation** | Visual feedback loop với retry |
| **Shape library docs** | 33 thư viện với docs markdown → AI có thể tra cứu |
| **MCP server** | Cho phép Claude Desktop/Cursor dùng như tool |

### Điểm yếu

| Aspect | Chi tiết |
|--------|----------|
| **Icon fragile** | AI phải tự gõ syntax stencil → đoán sai tên thường xuyên |
| **Không enforce icon lookup** | "Gọi get_shape_library trước" là lời nhắc, không enforce |
| **Material icon CDN** | `fonts.gstatic.com` — fail khi offline/CORS |
| **Azure path** | Relative `img/lib/azure2/...` — không portable |
| **VLM không detect icon** | Blank icon box pass validation |
| **Browser dependency** | PNG/SVG export cần browser mở — không headless-friendly |
| **Single-session MCP** | Không concurrent, không multi-tenant |
| **Stdio transport** | LangChain khuyến cáo không dùng stdio trong web-server context |
| **Output là mxGraph XML** | Không phải native "diagram code" — ít readable, khó debug |

---

## 11. Cơ hội cải thiện cho agent mới

### 11.1 Fix gốc rễ vấn đề icon

**Hiện tại:** LLM tự gõ `shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.ec2`  
**Nên làm:** Server-side icon resolver tool

```
AI gọi: resolve_icon(name="aws ec2", size=60)
Server: tìm trong pack/manifest → trả về mxCell style đã verify
AI chỉ paste style vào XML — không bao giờ tự gõ stencil name
```

Nguồn icon tốt hơn:
- **Backend pack:** 2,462 PNG icons từ `resources/icons/` (19 providers) → embed base64 data-URI
- **draw.io stencil catalog:** Map semantic name → `mxgraph.aws4.*` đã verify → vector
- **Iconify SVG:** Rasterize → data-URI → self-contained, không CDN

### 11.2 Headless rendering

**Hiện tại:** PNG export cần browser tab  
**Nên làm:** drawio-desktop CLI hoặc Playwright headless render → cho phép:
- Critic soi PNG = output thật
- Export không cần user browser

### 11.3 HTTP transport cho MCP

**Hiện tại:** stdio → single-session, không concurrent  
**Nên làm:** HTTP/SSE transport → multi-session, an toàn cho agent backend

### 11.4 Thêm validation category "icon_broken"

```typescript
type: z.enum(["overlap", "edge_routing", "text", "layout", "rendering", "icon_broken"])
```

VLM detect: "box có label nhưng không có icon visual → icon name sai"

### 11.5 Kết hợp hai luồng render

```
Luồng A (chất lượng cao, local):
  resolve_icon → mxGraph XML với data-URI → draw.io render → critic review

Luồng B (fallback, browser):
  LLM sinh XML → load vào draw.io embed → user tự sửa
```

---

*Phân tích dựa trên codebase tại `/home/baoluong/projects/diagram_code_agent/next-ai-draw-io`*  
*Key files: `app/api/chat/route.ts`, `lib/system-prompts.ts`, `lib/utils.ts`, `hooks/use-diagram-tool-handlers.ts`, `packages/mcp-server/src/`*
