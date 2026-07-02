"""Tải LLM runs từ LangSmith project, lưu JSONL + in token summary."""
import json, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from langsmith import Client

PROJECT_ID = "08f3d52e-8f5e-41e0-bd18-1cd9e38e79cd"
DAYS_BACK  = int(os.getenv("DAYS_BACK", "1"))    # default: 1 ngày
RUN_TYPES  = os.getenv("RUN_TYPES", "llm").split(",")   # llm | chain | tool | all
ROOT_ONLY  = os.getenv("ROOT_ONLY", "0") == "1"

since = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
out_path = Path(f"langsmith_runs_{DAYS_BACK}d.jsonl")

client = Client()

filters = dict(
    project_id  = PROJECT_ID,
    start_time  = since,
    is_root     = True if ROOT_ONLY else None,
)
if "all" not in RUN_TYPES:
    filters["run_type"] = RUN_TYPES[0]   # SDK v0.x: один тип за раз

print(f"Fetching run_type={RUN_TYPES} from last {DAYS_BACK}d (since {since.strftime('%Y-%m-%d %H:%M UTC')})…")

records = []; total_in = 0; total_out = 0; total_tok = 0
with out_path.open("w", encoding="utf-8") as f:
    for run in client.list_runs(**filters):
        rec = run.model_dump(mode="json") if hasattr(run, "model_dump") else dict(run)
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        records.append(rec)

        # token fields vary by SDK version / provider
        pt = (rec.get("prompt_tokens") or
              (rec.get("token_usage") or {}).get("prompt_tokens") or
              (rec.get("usage_metadata") or {}).get("input_tokens") or 0)
        ct = (rec.get("completion_tokens") or
              (rec.get("token_usage") or {}).get("completion_tokens") or
              (rec.get("usage_metadata") or {}).get("output_tokens") or 0)
        tt = pt + ct
        total_in += pt; total_out += ct; total_tok += tt

n = len(records)
print(f"\nSaved {n} runs → {out_path.resolve()}")
print(f"\n{'Token summary':=<44}")
print(f"  input  tokens : {total_in:>10,}")
print(f"  output tokens : {total_out:>10,}")
print(f"  TOTAL         : {total_tok:>10,}")
if n:
    print(f"  avg per run   : {total_tok//n:>10,}")

# top-10 by total tokens
if records:
    print(f"\n{'Top 10 runs by total tokens':=<44}")
    def rtok(r):
        pt = (r.get("prompt_tokens") or (r.get("token_usage") or {}).get("prompt_tokens") or 0)
        ct = (r.get("completion_tokens") or (r.get("token_usage") or {}).get("completion_tokens") or 0)
        return pt+ct
    for r in sorted(records, key=rtok, reverse=True)[:10]:
        ts  = str(r.get("start_time","?"))[:16]
        nm  = r.get("name") or r.get("run_type","?")
        tok = rtok(r)
        err = " ERR" if r.get("error") else ""
        print(f"  {ts}  {nm:<35}  {tok:>8,} tok{err}")
