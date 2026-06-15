# Fix: Drawer 400 Error – `text` not set với Mimo-v2.5

## Context

Mimo-v2.5 từ chối image blocks trong **tool messages** với lỗi `400: 'text' is not set`.
Code đã có class `InjectVisionAsUserEdit` (agent.py:98) để handle bằng cách:
1. Strip image blocks ra khỏi ToolMessage của `render_diagram`
2. Inject relay HumanMessage chứa `{"type": "image_url", ...}` ngay sau đó

Tuy nhiên lỗi vẫn xảy ra. Qua phân tích, relay HumanMessage được inject có dạng:
```json
[
  {"type": "text", "text": "[VISION_RELAY] Rendered diagram image:"},
  {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
]
```

Mimo yêu cầu field `text` trên **mọi** content block – kể cả `image_url` type. Block `image_url` thiếu `"text"` → mimo cũng trả về `'text' is not set`.

## Fix Chính – Thêm `"text": ""` vào image_url block

**File**: `backend/src/diagram_mcp/agent.py`  
**Vị trí**: `InjectVisionAsUserEdit.apply()` ~line 162

Thay:
```python
relay_content.append({
    "type": "image_url",
    "image_url": {"url": f"data:{mime};base64,{b64}"},
})
```

Thành:
```python
relay_content.append({
    "type": "image_url",
    "text": "",           # mimo requires text on every content block
    "image_url": {"url": f"data:{mime};base64,{b64}"},
})
```

## Fix Fallback – Nếu mimo không nhận image trong user messages

Nếu fix trên vẫn lỗi (mimo không support `image_url` trong user messages), thay đổi trong `build_agent()` ~line 551:

```python
if drawer_vision_relay:
    # Disable images entirely — mimo can't handle them anywhere
    os.environ["RENDER_INCLUDES_IMAGE"] = "0"
    logger.info("Images disabled for drawer model %s (vision_in_tools=False)", drawer_model)
```

Drawer sẽ hoạt động chỉ dựa vào text audit output từ `render_diagram`, không có visual feedback. Less ideal nhưng không có 400 errors.

## Critical Files

- `backend/src/diagram_mcp/agent.py` – `InjectVisionAsUserEdit.apply()` (line ~162), `build_agent()` (line ~550)

## Verification

1. Start server với mimo config
2. Tạo một diagram request
3. Quan sát drawer agent không còn throw 400 errors
4. Nếu fix chính hoạt động: drawer vẫn nhận được visual feedback qua relay messages
5. Nếu fallback: drawer hoạt động nhưng không có visual feedback
