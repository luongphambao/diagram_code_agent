# Implementation Plan: MCP Stencil Upgrade Pass

## Mục tiêu

Sau khi `diagrams`-as-code tạo ra baseline `out.drawio` (với icon embed dạng base64 PNG raster), chạy một **MCP improvement pass** để:

1. Thay thế từng icon raster bằng native draw.io vector stencil (qua `resolve_stencil`)
2. Validate XML structure (qua `validate_drawio`)
3. Render bản improved để verify (qua `render_drawio_png`)

Kết quả: file `.drawio` mở trong draw.io editor trông đẹp hơn nhiều (vector icons, đúng cloud provider style) thay vì PNG blur khi zoom.

---

## Bức tranh hiện tại

### Flow hiện tại

```
LLM viết diagram.py
    ↓ render_diagram()
subprocess chạy diagram.py
    ↓
out.png + out.dot + out.nodes.json     ← baseline raster
    ↓ export_drawio()
prettygraph.dot_to_drawio()  hoặc  gv_to_drawio.convert()
    ↓
out.drawio  (nodes có style: shape=label;image=data:image/png,<base64>...)
    ↓ validate_drawio_output()  [optional, LLM hay skip]
MCP validate_drawio  ← chỉ tool này gọi MCP, 3 tools còn lại bỏ ngỏ
```

### Vấn đề

- `out.drawio` embed icon dưới dạng base64 PNG — bị pixel khi zoom trong draw.io editor
- MCP server có `resolve_stencil`, `search_stencils`, `render_drawio_png` nhưng **chưa ai gọi**
- Warning ở `server.py:63` tự ghi nhận: "mcp_client.py exists but is never called"

### Dữ liệu sẵn có

**`out.nodes.json`** (từ prettygraph) — chứa metadata mỗi node:
```json
{
  "nodes": {
    "ec2_server": {
      "label": "EC2",
      "kind": "compute",
      "fill": "#E8F4FD",
      "stroke": "#2E86C1",
      "icon": "/icons/aws/compute/ec2.png"
    }
  }
}
```

Icon path encode sẵn `provider` và `keyword` → `/icons/<provider>/<category>/<name>.png`

**`out.drawio`** — mỗi node là một `mxCell`:
```xml
<mxCell id="n42" value="EC2" style="shape=label;html=1;rounded=1;...
  image=data:image/png,<base64>...;imageWidth=34;..." vertex="1" .../>
```

Cell ID dùng format `n{gvid}`, match với DOT JSON object's `_gvid`.

---

## Implementation

### Bước 1 — Extend `_write_sidecar()` để lưu gvid mapping

**File**: `backend/src/diagram_mcp/prettygraph.py`

Thêm `gvid` vào từng node entry trong sidecar, sau khi render DOT → JSON để lấy mapping `node_name → gvid`:

```python
def _write_sidecar(self, path: str, dot_path: str | None = None) -> None:
    # ... existing code ...
    # Thêm gvid mapping bằng cách parse dot -Tjson
    gvid_map: dict[str, int] = {}
    if dot_path and Path(dot_path).exists():
        try:
            import subprocess, json as _json
            js = subprocess.run(
                ["dot", "-Tjson", dot_path], capture_output=True, text=True
            ).stdout
            g = _json.loads(js)
            for o in g.get("objects", []):
                if "name" in o and "_gvid" in o:
                    gvid_map[o["name"]] = o["_gvid"]
        except Exception:
            pass

    for node_id, meta in node_meta.items():
        if node_id in gvid_map:
            meta["cell_id"] = f"n{gvid_map[node_id]}"
```

Hoặc đơn giản hơn: match theo `label` thay vì `cell_id` (nhiều node cùng label thì update tất cả — acceptable).

### Bước 2 — Tạo tool `upgrade_drawio_stencils()`

**File**: `backend/src/diagram_mcp/tools.py`

```python
@tool
async def upgrade_drawio_stencils() -> str:
    """Replace raster PNG icons in out.drawio with native draw.io vector stencils.

    Reads out.nodes.json to identify provider/service for each node, calls MCP
    resolve_stencil to get native stencil styles, patches out.drawio XML, then
    validates via MCP validate_drawio. Falls back gracefully if MCP is offline.
    Call this AFTER export_drawio() succeeds.
    """
    out = WORKSPACE / "out.drawio"
    sidecar = WORKSPACE / "out.nodes.json"

    if not out.exists():
        return "No out.drawio — call export_drawio first."
    if not sidecar.exists():
        return "No out.nodes.json — prettygraph sidecar missing (plain style?). Skipping upgrade."

    nodes_data = json.loads(sidecar.read_text(encoding="utf-8"))
    xml = out.read_text(encoding="utf-8")

    # Build label → (provider, keyword) from icon paths
    label_to_stencil_key: dict[str, tuple[str, str]] = {}
    for meta in nodes_data.get("nodes", {}).values():
        label = (meta.get("label") or "").strip()
        icon = meta.get("icon") or ""
        if not label or not icon:
            continue
        # /icons/aws/compute/ec2.png → ("aws", "ec2")
        parts = Path(icon).parts
        try:
            icons_idx = next(i for i, p in enumerate(parts) if p in
                             ("aws", "azure", "gcp", "k8s", "alibabacloud",
                              "ibm", "network", "cisco", "onprem"))
            provider = parts[icons_idx]
            keyword = Path(parts[-1]).stem.replace("-", " ")
            label_to_stencil_key[label] = (provider, keyword)
        except StopIteration:
            pass

    if not label_to_stencil_key:
        return "No icon paths found in nodes.json — nothing to upgrade."

    try:
        from .mcp_client import mcp_tools
        from xml.etree import ElementTree as ET

        async with mcp_tools() as tools:
            resolver = next((t for t in tools if "resolve_stencil" in t.name), None)
            validator = next((t for t in tools if "validate" in t.name.lower()), None)

            if resolver is None:
                return "MCP resolve_stencil not available — skipping upgrade."

            # Resolve stencils for each unique (provider, keyword)
            stencil_cache: dict[tuple[str, str], str | None] = {}
            for label, key in label_to_stencil_key.items():
                if key not in stencil_cache:
                    try:
                        result = await resolver.ainvoke(
                            {"provider": key[0], "keyword": key[1]}
                        )
                        text = str(result)
                        # parse "style:    shape=mxgraph..." from result text
                        style_line = next(
                            (l.split("style:")[1].strip()
                             for l in text.splitlines() if "style:" in l), None
                        )
                        stencil_cache[key] = style_line
                    except Exception:
                        stencil_cache[key] = None

            # Patch XML: replace image=data:image/png,... with stencil style
            upgraded = 0
            for label, key in label_to_stencil_key.items():
                stencil_style = stencil_cache.get(key)
                if not stencil_style:
                    continue
                # Find all mxCell with this value + raster image
                import re
                pattern = (
                    r'(<mxCell[^>]*value="' + re.escape(html.escape(label)) + r'"[^>]*'
                    r'style=")([^"]*image=data:image/png,[^;]+;[^"]*)(")'
                )
                def replacer(m, stencil=stencil_style):
                    old_style = m.group(2)
                    # Keep fill/stroke colors from prettygraph, swap shape+image
                    fill = re.search(r'fillColor=([^;]+)', old_style)
                    stroke = re.search(r'strokeColor=([^;]+)', old_style)
                    shadow = ";shadow=1" if "shadow=1" in old_style else ""
                    new_style = stencil
                    if fill:
                        new_style += f";fillColor={fill.group(1)}"
                    if stroke:
                        new_style += f";strokeColor={stroke.group(1)}"
                    new_style += shadow
                    return m.group(1) + new_style + m.group(3)

                new_xml, n = re.subn(pattern, replacer, xml, flags=re.DOTALL)
                if n > 0:
                    xml = new_xml
                    upgraded += n

            if upgraded == 0:
                return "No raster icons found to upgrade (already native or no match)."

            # Validate the upgraded XML
            validation_note = ""
            if validator:
                try:
                    val_result = await validator.ainvoke({"xml": xml})
                    val_text = str(val_result)
                    if "fixed" in val_text.lower():
                        # Extract fixed XML if validator auto-fixed something
                        fixed_match = re.search(r'Fixed XML:\n(.+)', val_text, re.DOTALL)
                        if fixed_match:
                            xml = fixed_match.group(1).strip()
                    validation_note = f" Validation: {val_text[:120]}"
                except Exception as e:
                    validation_note = f" (validation skipped: {e})"

            out.write_text(xml, encoding="utf-8")
            return (
                f"Upgraded {upgraded} node(s) to native stencils in out.drawio."
                + validation_note
            )

    except Exception as exc:
        return (
            f"MCP upgrade failed ({exc.__class__.__name__}: {exc}) — "
            "out.drawio unchanged (still usable with raster icons)."
        )
```

### Bước 3 — Thêm vào `DRAWER_TOOLS` và update prompt

**File**: `backend/src/diagram_mcp/tools.py`

```python
DRAWER_TOOLS = [
    resolve_icons, search_icons, fetch_logo,
    render_diagram, export_drawio,
    upgrade_drawio_stencils,   # ← thêm vào đây
    validate_drawio_output,    # ← giữ lại (validate sau upgrade)
]
```

**File**: `backend/src/diagram_mcp/prompts.py` — thêm vào `_DRAWER_TOOLS_BLOCK`:

```
- `upgrade_drawio_stencils()` — call this AFTER export_drawio() succeeds.
  Replaces raster PNG icons in out.drawio with native draw.io vector stencils
  by calling the MCP resolve_stencil service. Falls back gracefully if offline.
  Improves how the file looks when opened in the draw.io editor.
- `validate_drawio_output()` — call this AFTER upgrade_drawio_stencils()
  to do a final XML validation check.
```

Và update drawer job flow (step 6 trong `## Your job`):

```
6. Call `export_drawio()`, then `upgrade_drawio_stencils()` to swap raster icons
   for native vector stencils, then `validate_drawio_output()` for final check.
   If MCP is offline, any of these degrade gracefully — never block on them.
```

### Bước 4 — Remove stale warning

**File**: `backend/src/diagram_mcp/server.py`, xóa `logger.warning(...)` ở dòng 63-68.

---

## Flow sau khi implement

```
diagrams code → render_diagram() → out.png + out.dot + out.nodes.json
                                                    ↓
                            export_drawio() → out.drawio (baseline, raster icons)
                                                    ↓
                    upgrade_drawio_stencils() → MCP resolve_stencil per node
                                             → patch XML styles
                                             → MCP validate_drawio
                                             → out.drawio (native vector stencils ✓)
                                                    ↓
                        validate_drawio_output() → final XML check
```

---

## Edge cases & fallback

| Tình huống | Xử lý |
|---|---|
| MCP server offline | Tool return warning, `out.drawio` unchanged |
| Node label không match nodes.json | Skip node đó |
| `resolve_stencil` không tìm thấy stencil | `search_stencils` fallback (optional phase 2) |
| `gv_to_drawio` path (plain style, no nodes.json) | Tool return early "no sidecar" |
| Multiple nodes cùng label | Update tất cả (đúng vì chúng có cùng service type) |
| Slide style — `out.drawio` từ `render_slide()` | Giống như prettygraph, nodes.json tồn tại → upgrade bình thường |

---

## Phạm vi không nằm trong plan này

- **`render_drawio_png` verification**: render bản improved để compare với baseline — có thể thêm sau
- **Manual stencil hint từ blueprint**: dùng blueprint.json để override provider detection
- **`search_stencils` fallback**: khi `resolve_stencil` miss, thử fuzzy search
- **`gv_to_drawio` (plain style) support**: cần parse DOT JSON để lấy node `image` attr thay vì nodes.json

---

## Files cần thay đổi

| File | Thay đổi |
|---|---|
| `backend/src/diagram_mcp/tools.py` | Thêm `upgrade_drawio_stencils()`, update `DRAWER_TOOLS` |
| `backend/src/diagram_mcp/prompts.py` | Update `_DRAWER_TOOLS_BLOCK` + drawer job steps |
| `backend/src/diagram_mcp/server.py` | Xóa stale warning ở dòng 63-68 |
| `backend/src/diagram_mcp/prettygraph.py` | (Optional) thêm `cell_id` vào sidecar để match chính xác hơn |
