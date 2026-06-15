# Nâng cấp bước "Propose Tech Stack" lên chuẩn Solution Architect 10 năm kinh nghiệm

## Context

Bước "Proposing the technology stack" hiện tại chưa đủ production-grade: chỉ có choice/rationale/alternatives + cost tier tương đối ($/$$/$$$). Một SA senior luôn trình bày **cơ sở định cỡ (sizing basis) trước, lựa chọn sau**: giả định về budget khách hàng, quy mô user (MAU/DAU), concurrent users, RPS đỉnh, tăng trưởng dữ liệu, team size — rồi từ đó suy ra cost ước tính (USD/tháng), capacity sizing có kèm phép tính, performance target gắn với NFR, rủi ro + mitigation, và lộ trình scaling theo phase.

Phát hiện thêm khi khảo sát:
- `_normalize_tech_stack` (server.py:443-469) hiện **làm rơi `cost_tier` và `decision_criteria`** — LLM có sinh ra nhưng card approval không bao giờ thấy. Sẽ fix luôn.
- **Số lượng layer chưa đầy đủ** (câu hỏi của user): danh sách gợi ý hiện tại `frontend|backend|database|cache|queue|auth|infra|monitoring|cdn|search` thiếu các layer mà chính diagram output đang dùng (ví dụ diagram CCS có KMS/Secrets, DMS, Qlik BI, Step Functions, VPN/ALB, external integrations). Lưu ý: `layer` là `str` tự do, không phải enum — nên đây là vấn đề **hướng dẫn trong prompt/skill**, không phải schema.

Quyết định scope: **bỏ qua weighted criteria matrix** (điểm 1-5 + why_rejected đã đủ kể câu chuyện trade-off; thêm trọng số chỉ tăng noise JSON). Chất SA senior đến từ con số tường minh + danh sách "cần khách hàng xác nhận", không phải thêm máy móc chấm điểm.

## Taxonomy layer mới (trả lời "đã đầy đủ chưa?")

Mở rộng từ 10 → 16 layer, chia 2 nhóm trong skill/prompt:

**Core (luôn cân nhắc, bỏ qua phải có lý do):**
`frontend, backend, database, auth, infra, monitoring, networking` *(mới — LB/API Gateway/VPN/VPC topology, trước đây lẫn vào infra)*, `security` *(mới — KMS, secrets, WAF; tách khỏi auth vì auth = identity, security = encryption/perimeter)*

**Conditional (thêm khi requirement chạm tới):**
`cache, queue, cdn, search, storage` *(mới — object storage S3/Blob, khác database)*, `ci_cd` *(mới — pipeline deploy)*, `analytics` *(mới — ETL/warehouse/BI như Qlik)*, `ai_ml` *(mới)*, `integration` *(mới — kết nối hệ thống ngoài: DMS, ESB, iPaaS)*

Quy tắc trong skill: "Một stack production tối thiểu có 7-9 layer (core). Thiếu `security` hoặc `networking` ở security_level high/critical là lỗi. Không bịa layer khi requirement không cần — conditional layer phải trace về một FR/NFR cụ thể."

## Changes

### 1. `backend/src/diagram_mcp/tools.py` — Pydantic models mới (sau TechCriteria ~dòng 1060)

```python
class CostRange(BaseModel):
    """Assumption-based monthly cost estimate in USD (always a range)."""
    min_usd: int  # ge=0
    max_usd: int  # ge=0

class UserScaleAssumptions(BaseModel):
    mau: Optional[int]                 # monthly active users
    dau: Optional[int]                 # B2C ≈ 20-30% MAU, B2B ≈ 60-80%
    peak_concurrent: Optional[int]     # ≈ 5-10% DAU
    peak_rps: Optional[int]            # ≈ concurrent × actions/min ÷ 60
    growth_rate_yoy_pct: Optional[int]

class DataAssumptions(BaseModel):
    initial_gb: Optional[int]
    growth_gb_per_month: Optional[int]
    read_write_ratio: str = ""         # "90:10 read-heavy"

class TeamAssumptions(BaseModel):
    size: Optional[int]
    skill_level: str = ""              # junior-mid | mixed | senior
    devops_maturity: str = ""          # none | basic CI/CD | mature platform team

class SolutionAssumptions(BaseModel):
    budget_tier: str = ""              # startup | smb | mid-market | enterprise
    monthly_budget_range_usd: Optional[CostRange]
    users: Optional[UserScaleAssumptions]
    data: Optional[DataAssumptions]
    team: Optional[TeamAssumptions]
    project_phase: str = ""            # mvp | growth | scale-up | enterprise
    availability_target: str = ""      # "99.9% (≤8.8h downtime/yr)" — measurable
    latency_target_p99_ms: Optional[int]
    compliance: list[str] = []
    primary_region: str = ""
    confirm_with_customer: list[str] = []   # giả định CHƯA được khách xác nhận — "senior-SA hedge list"

class TechRisk(BaseModel):
    risk: str
    mitigation: str = ""

class ScalingPhase(BaseModel):
    phase: str                          # "Phase 1 — MVP (0–10k MAU)"
    trigger: str = ""                   # "DAU > 5k or p99 > 300 ms" — measurable
    changes: list[str] = []
    est_monthly_cost_usd: Optional[CostRange]
```

Mở rộng `TechChoice` (dòng 1069) — 4 field optional mới (payload cũ vẫn validate):
- `estimated_monthly_cost_usd: Optional[CostRange]`
- `capacity_sizing: str = ""` — instance type/count KÈM phép tính ("2× Fargate 0.5vCPU, autoscale 2–6 — sized for ~150 RPS peak × 2 headroom")
- `performance_target: str = ""` — gắn với NFR trong brief ("p99 ≤ 120 ms at 150 RPS")
- `risks: list[TechRisk] = []` — 1-2 risk/layer

Cập nhật docstring `layer` trong TechChoice: liệt kê 16 layer mới.

### 2. `propose_tech_stack` tool (tools.py:1234-1270)

Signature mới (kwargs optional → call cũ vẫn chạy):
```python
def propose_tech_stack(
    tech_stack: list[TechChoice],
    assumptions: Optional[SolutionAssumptions] = None,
    scaling_roadmap: Optional[list[ScalingPhase]] = None,
    estimated_total_monthly_cost_usd: Optional[CostRange] = None,
) -> str:
```

`tech_stack.json` shape mới (wrapped):
```json
{ "assumptions": {...}|null, "layers": {"<layer>": {...đầy đủ field mới}},
  "scaling_roadmap": [...], "estimated_total_monthly_cost_usd": {...}|null }
```

Soft warnings trong return string (theo pattern propose_blueprint tools.py:1397-1408 — cảnh báo, không block):
- Thiếu `assumptions` → "No sizing assumptions recorded — a senior proposal states budget, user scale, concurrency explicitly."
- Layer thiếu cost estimate → liệt kê tên.
- Tổng min các layer > total.max, hoặc total.max > budget.max → cảnh báo nhất quán.
- Có assumptions nhưng `confirm_with_customer` rỗng → nhắc liệt kê.
- **Layer completeness**: thiếu layer core (đặc biệt `security`/`networking` khi security_level từ architecture_analysis.json là high/critical) → cảnh báo.

### 3. `backend/src/diagram_mcp/server.py`

- `_normalize_tech_stack` (443-469): pass-through các field mới + fix 2 field đang bị rơi (`cost_tier`, `decision_criteria`). Nhánh dict: nếu có key `"layers"` (shape mới replay từ DB) thì unwrap trước.
- `_card_for` (472-483): nhánh techstack thêm `assumptions`, `scaling_roadmap`, `estimated_total_monthly_cost_usd` từ args vào card payload; đổi question thành "Review the recommended tech stack and its sizing assumptions...".

### 4. Skills

**`backend/skills/requirement-analysis/SKILL.md`** — thêm section "2e. Sizing assumptions — numbers, not adjectives" (sau 2d, ~dòng 82):
- Bảng heuristic: signal trong request → MAU / peak concurrent / peak RPS / budget tier (MVP: 1-5k MAU, $200-1k/mo … enterprise: 1M+ MAU, $25k+/mo).
- Chuỗi suy diễn PHẢI show phép tính: DAU ≈ 20-30% MAU (B2C) / 60-80% (B2B); concurrent ≈ 5-10% DAU; RPS ≈ concurrent × actions/min ÷ 60; team không nói gì → giả định 3-6 engineer, mixed, basic CI/CD → thiên về managed services.
- Mở rộng mental-brief template (dòng 105-114): thêm Budget, Peak load (kèm derivation), Data volume, Team, Phase.
- Anti-pattern mới: "'medium traffic' thay vì '~150 RPS peak (assumed: 50k MAU → 12k DAU → 1.2k concurrent × 2 actions/min)' là junior work."

**`backend/skills/solution-design/SKILL.md`** — thay section "Cost tier" mỏng (dòng 90-97) bằng 4 section:
1. **Cost estimation (required)**: giữ `cost_tier` làm nhãn nhanh + bảng giá tham chiếu AWS theo 3 mức tải (MVP ~25 RPS / Growth ~250 RPS / Scale ~2.5k RPS) cho containers, serverless, Postgres, Redis, queue, CDN, LB+NAT+egress, monitoring. Mọi con số frame là "assumption-based ±40%, infra only". Tổng phải fit budget — "không fit thì đổi design, đừng đổi số".
2. **Capacity sizing (required per layer)**: heuristic — 2vCPU/4GB ≈ 100-300 RPS CRUD; size cho peak × 1.5-2 headroom, show số instance; db.t3.medium ~200 connections, cần PgBouncer/RDS Proxy khi >100; storage = initial + 12×growth×1.5; cache ≈ 10-20% DB size cho read-heavy.
3. **Scaling roadmap (required, 2-3 phase)**: "start with X, move to Y when Z" với trigger đo được (DAU > N, p95 > target, DB CPU > 70%).
4. **Risk identification (1-2/layer)**: checklist — vendor lock-in exit cost, cold start, connection exhaustion, cost runaway (egress/per-request), single-AZ blast radius, learning curve, quota ceilings.

Cộng thêm: **section "Layer coverage"** với taxonomy 16 layer (core vs conditional) + quy tắc tối thiểu 7-9 layer như mô tả ở trên.

### 5. `backend/src/diagram_mcp/prompts.py`

- `_MAIN_TOOLS_BLOCK` (~dòng 36-40): cập nhật mô tả propose_tech_stack với danh sách layer mới + tham số mới.
- `_STAGED_FLOW` step 4 (dòng 205-213): viết lại — "Work like a 10-year solution architect: state the sizing basis FIRST, then choices." Yêu cầu: `assumptions` LUÔN có (derive theo heuristic, mọi giả định chưa xác nhận vào `confirm_with_customer`); per-layer đủ cost range/capacity (kèm math)/performance target/risks/alternatives; tổng cost fit budget; roadmap 2-3 phase với trigger đo được; cover đủ core layers.

### 6. Frontend

**`frontend/src/hooks/useDiagramAgent.ts`**:
- Interface mới: `CostRange`, `SolutionAssumptions` (tất cả optional, có nested users/data/team + `confirm_with_customer?`), `TechRisk`, `ScalingPhase`.
- `TechStackLayer` thêm optional: `cost_tier?`, `decision_criteria?: Record<string, number>`, `estimated_monthly_cost_usd?`, `capacity_sizing?`, `performance_target?`, `risks?`.
- `PendingInterrupt.data` thêm: `assumptions?`, `scaling_roadmap?`, `estimated_total_monthly_cost_usd?`.
- `AgentState.tech_stack` → union chấp nhận cả shape cũ (flat) lẫn mới (wrapped).

**`frontend/src/components/TechStackApproval.tsx`** (mọi section conditional → conversation cũ render y nguyên):
- Helper `fmtUsd(r?: CostRange)` → "$800–2.4k/mo".
- **Assumptions header** (giữa question và layer cards): block "Design assumptions" dạng chip row — `MVP · $1–3k/mo budget · 50k MAU · ~2.5k concurrent · ~150 RPS · 99.9% · p99 ≤200ms · Team 4 (mixed) · ap-southeast-1` (chỉ render giá trị có). Dưới đó: list "Confirm with customer" tint amber khi non-empty — **luôn hiển thị, không collapse** (đây là chữ ký của SA senior).
- **Per-layer meta line** dưới rationale: muted `~$150–400/mo · 2× Fargate autoscale 2–6 · p99 ≤120ms` (join segment có mặt); `cost_tier` chip nhỏ cạnh tên choice; risks = badge ⚠ với tooltip `title={risk — mitigation}` (cùng pattern tooltip alternatives hiện tại).
- **Footer** trên hàng nút: `Estimated total: $X–Y/mo (assumption-based, infra only)` + `<details>` collapse "Scaling roadmap" (mỗi phase 1 dòng: phase đậm, trigger muted, changes join ", ").
- `LAYER_ORDER` (dòng 10): mở rộng theo taxonomy 16 layer (layer lạ vẫn render — logic hiện tại đã append cuối).

### 7. `backend/src/diagram_mcp/reporting.py` (PDF report)

- `_tech_items` (141-163): unwrap shape mới trước (`tech_stack.get("layers")` nếu là dict) — giữ tương thích shape cũ.
- `assemble_report_data` (354+): thêm `tech_assumptions`, `scaling_roadmap`, `tech_total_cost`; template techstack section (594-624): thêm cột "Est. cost/mo", đoạn assumptions + confirm-with-customer phía trên bảng, scaling roadmap rút gọn phía dưới.

## Verification

1. Backend import + tests: `cd backend && python -c "from diagram_mcp.tools import propose_tech_stack"` rồi `python -m pytest tests/ -x`.
2. Backward-compat: feed `_normalize_tech_stack` list/dict shape cũ → vẫn render; `_tech_items` với tech_stack.json flat cũ → output không đổi.
3. Frontend: `cd frontend && npm run build` (tsc phải pass).
4. `docker compose up --build`, chạy flow thật với prompt thưa thông tin ("Design an e-commerce platform for a startup on AWS"): card phải hiện assumptions chips (MAU/RPS/budget derive được) + confirm-with-customer list + cost/capacity per layer + total footer + roadmap; reject với "budget is only $500/month" → revision phải điều chỉnh assumptions + cost nhất quán; approve → check `workspace/tech_stack.json` shape wrapped; chạy hết flow → PDF có cột cost mới.
5. Replay 1 conversation cũ từ DB → card + stage artifacts render không lỗi.
