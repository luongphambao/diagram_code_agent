# Tải data các lần chạy từ LangSmith

Có. Với **toàn bộ các lần chạy trong project**, cách ổn nhất là dùng SDK Python hoặc LangSmith CLI.

Project ID trong URL:

```text
08f3d52e-8f5e-41e0-bd18-1cd9e38e79cd
```

Trace/run đang mở:

```text
019f1ce7-e5b4-7d23-8191-b776d5766137
```

LangSmith coi mỗi node như LLM/tool/chain là một **run/span**. Vì vậy export “all runs” sẽ gồm cả các node con; thêm `is_root=True` nếu bạn chỉ muốn một dòng cho mỗi execution/trace. SDK hỗ trợ query theo `project_id`, `trace_id`, `is_root`, thời gian và filter.

Nguồn tham khảo: https://docs.langchain.com/langsmith/trace-query-syntax

## Cách nên dùng: export JSONL bằng Python

```bash
pip install -U langsmith
export LANGSMITH_API_KEY="lsv2_xxx"
```

Tạo file `export_langsmith_runs.py`:

```python
import json
from pathlib import Path
from langsmith import Client

PROJECT_ID = "08f3d52e-8f5e-41e0-bd18-1cd9e38e79cd"
OUTPUT_FILE = Path("langsmith_all_runs.jsonl")

# True = chỉ lấy root trace / mỗi execution một record
# False = lấy toàn bộ span: chain, tool, LLM, retriever...
ROOT_ONLY = False

client = Client()
count = 0

with OUTPUT_FILE.open("w", encoding="utf-8") as f:
    for run in client.list_runs(
        project_id=PROJECT_ID,
        is_root=True if ROOT_ONLY else None,
    ):
        # Tương thích nhiều version SDK / Pydantic
        if hasattr(run, "model_dump"):
            record = run.model_dump(mode="json")
        elif hasattr(run, "dict"):
            record = run.dict()
        else:
            record = dict(run)

        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        count += 1

print(f"Exported {count} runs to {OUTPUT_FILE.resolve()}")
```

Chạy:

```bash
python export_langsmith_runs.py
```

Kết quả là `langsmith_all_runs.jsonl`, mỗi dòng là một JSON record, giữ được `inputs`, `outputs`, metadata, timing, error, token/cost nếu trace có ghi các trường đó.

## Chỉ tải trace đang mở trong link

Dùng `trace_id` để lấy toàn bộ run thuộc trace đó:

```python
TRACE_ID = "019f1ce7-e5b4-7d23-8191-b776d5766137"

for run in client.list_runs(trace_id=TRACE_ID):
    ...
```

## Cách nhanh bằng LangSmith CLI

LangSmith CLI có hỗ trợ export traces/runs ra file. CLI dùng **project name** cho `--project`, không phải UUID project.

```bash
curl -fsSL https://cli.langsmith.com/install.sh | sh
langsmith auth login
```

Lấy tên project:

```bash
langsmith project list
```

Export toàn bộ trace theo khoảng thời gian:

```bash
langsmith trace export ./langsmith_export   --project "<PROJECT_NAME>"   --since "2025-01-01T00:00:00Z"   --full
```

Hoặc chỉ export các LLM run:

```bash
langsmith run export llm_runs.jsonl   --project "<PROJECT_NAME>"   --run-type llm   --full
```

Lưu ý: nếu không truyền `--since`, CLI có thể mặc định chỉ query khoảng thời gian gần đây. Nên đặt mốc thời gian đủ cũ để tránh thiếu dữ liệu.

Nguồn tham khảo: https://docs.langchain.com/langsmith/langsmith-cli

## Nếu data rất lớn

LangSmith có Bulk Data Export ra S3/GCS/MinIO ở định dạng Parquet, phù hợp khi export hàng trăm nghìn hoặc hàng triệu spans. Target có thể dùng `session_id` = project UUID và time range.

Ví dụ payload:

```json
{
  "session_id": "08f3d52e-8f5e-41e0-bd18-1cd9e38e79cd"
}
```

Nguồn tham khảo: https://docs.langchain.com/langsmith/data-export

## Khuyến nghị

Dùng script Python trước: dễ chạy, lấy đủ input/output, và dễ nạp lại để phân tích hoặc huấn luyện/evaluate về sau.
