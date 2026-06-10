export const meta = {
  name: 'diagram-quality-check',
  description: 'Sau mỗi implementation: kiểm tra diagram output so với Project Brief và quality benchmark',
  phases: [
    { title: 'Load Context', detail: 'Đọc Project Brief và benchmark hiện tại' },
    { title: 'Multi-lens Review', detail: 'Đánh giá diagram theo 5 dimensions song song' },
    { title: 'Verdict', detail: 'Tổng hợp điểm, đưa ra PASS/REVISE/FAIL và action items' },
  ],
}

// args có thể là:
// - { diagram_path: "/path/to/diagram.png" }  — đánh giá file diagram cụ thể
// - { run_id: "xxx" }  — đánh giá run quality log
// - null  — đánh giá latest output trong workspace

const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    dimension: { type: 'string' },
    score: { type: 'number' },
    weight: { type: 'number' },
    observations: { type: 'array', items: { type: 'string' } },
    defects: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', enum: ['blocker', 'major', 'minor'] },
          description: { type: 'string' },
          fix: { type: 'string' },
        },
        required: ['severity', 'description', 'fix'],
      },
    },
    red_flags_triggered: { type: 'array', items: { type: 'string' } },
  },
  required: ['dimension', 'score', 'weight', 'observations', 'defects', 'red_flags_triggered'],
}

// ─── Phase 1: Load Context ───────────────────────────────────────────────────

phase('Load Context')

const context = await agent(
  `Đọc và tổng hợp context cần thiết để review diagram quality.

1. Đọc Project Brief:
   Chạy: pandoc "/home/baoluong/projects/diagram_code_agent/requirement/Project Brief.docx" -t plain

2. Tìm diagram output gần nhất:
   Chạy: find /home/baoluong/projects/diagram_code_agent -name "*.png" -newer /home/baoluong/projects/diagram_code_agent/backend/pyproject.toml 2>/dev/null | head -5
   Chạy: find /home/baoluong/projects/diagram_code_agent -name "*.drawio" -newer /home/baoluong/projects/diagram_code_agent/backend/pyproject.toml 2>/dev/null | head -5
   Chạy: ls -lt /home/baoluong/projects/diagram_code_agent/backend/workspace/ 2>/dev/null | head -20

3. Đọc quality log gần nhất nếu có:
   Chạy: find /home/baoluong/projects/diagram_code_agent -name "quality*.jsonl" -o -name "quality*.json" 2>/dev/null | head -3 | xargs tail -50 2>/dev/null

4. Đọc benchmark (nếu đã được tạo bởi dm-techlead-reviewer workflow):
   Chạy: cat /home/baoluong/projects/diagram_code_agent/.claude/benchmark.json 2>/dev/null || echo "No benchmark file yet"

Target: ${args && args.diagram_path ? args.diagram_path : 'latest output'}

Trả về JSON với:
{
  "project_brief_summary": "tóm tắt yêu cầu key",
  "diagram_path": "path đến diagram cần review",
  "has_benchmark": true/false,
  "benchmark_summary": "tóm tắt benchmark nếu có",
  "quality_log_summary": "tóm tắt quality log nếu có"
}`,
  {
    label: 'Load: context + diagram',
    schema: {
      type: 'object',
      properties: {
        project_brief_summary: { type: 'string' },
        diagram_path: { type: 'string' },
        has_benchmark: { type: 'boolean' },
        benchmark_summary: { type: 'string' },
        quality_log_summary: { type: 'string' },
      },
      required: ['project_brief_summary', 'diagram_path', 'has_benchmark', 'benchmark_summary', 'quality_log_summary'],
    },
  }
)

log(`Reviewing: ${context.diagram_path}`)

// ─── Phase 2: Multi-lens Review ──────────────────────────────────────────────

phase('Multi-lens Review')

const DIMENSIONS = [
  {
    name: 'Thẩm mỹ / Visual Aesthetics',
    weight: 0.20,
    focus: `
    - Color harmony: palette nhất quán, professional, không chói
    - Spacing & padding đồng đều giữa các nodes
    - Font size hierarchy (title > label > description)
    - Visual noise: không cluttered, whitespace hợp lý
    - Không dùng màu mặc định xấu (đỏ/vàng chói mắt)`,
  },
  {
    name: 'Nội dung / Content Accuracy',
    weight: 0.30,
    focus: `
    - Nodes đầy đủ so với yêu cầu (không thiếu component nào)
    - Labels chính xác, không ambiguous, không viết tắt khó hiểu
    - Edge labels mô tả đúng relationship (REST, gRPC, Kafka, etc.)
    - Tech stack phù hợp với use case trong Project Brief
    - Không có node placeholder hoặc "TBD"`,
  },
  {
    name: 'Bố cục / Layout & Composition',
    weight: 0.25,
    focus: `
    - Flow direction nhất quán (LR hoặc TB, không mixed)
    - Grouping phản ánh đúng domain boundaries (clusters rõ ràng)
    - Cross-edge tối thiểu, không spider web
    - Cân đối không gian (không dồn hết về một phía)
    - Hierarchy rõ ràng (ingestion → processing → storage → serving)`,
  },
  {
    name: 'Logo & Icon Quality',
    weight: 0.15,
    focus: `
    - Logo đúng brand (AWS Lambda ≠ GCP Functions icon)
    - Không dùng generic box khi có branded icon
    - Icon size nhất quán trong cùng tier/cluster
    - Không pixelated, không blurry
    - Logo có nền transparent hoặc white, không có nền màu lạ`,
  },
  {
    name: 'Readability & Clarity',
    weight: 0.10,
    focus: `
    - Readable ở 100% zoom không cần scroll horizontal
    - Title/legend rõ ràng
    - Màu accessible (không chỉ dùng red/green để phân biệt)
    - Không overlap text với shape/edge
    - Diagram tự giải thích được (không cần verbal explanation dài)`,
  },
]

const reviews = await pipeline(
  DIMENSIONS,
  async (dim) => {
    return agent(
      `Bạn là Diagram Quality Reviewer chuyên về "${dim.name}".

PROJECT BRIEF CONTEXT:
${context.project_brief_summary}

DIAGRAM CẦN REVIEW: ${context.diagram_path}

Nếu là file ảnh (.png/.jpg/.svg), hãy dùng Read tool để xem nội dung ảnh.
Nếu là file .drawio, chạy: cat "${context.diagram_path}" | head -200

BENCHMARK CONTEXT: ${context.benchmark_summary}

TIÊU CHÍ ĐÁNH GIÁ CHO "${dim.name}" (weight=${dim.weight}):
${dim.focus}

THANG ĐIỂM (1-5):
5 = Xuất sắc, vượt tiêu chuẩn
4 = Tốt, đáp ứng đầy đủ
3 = Chấp nhận được, có một vài vấn đề nhỏ
2 = Cần cải thiện, có vấn đề rõ ràng
1 = Không đạt, có lỗi nghiêm trọng

RED FLAGS (tự động giảm điểm về 1-2 nếu vi phạm):
- Sai brand logo (e.g., AWS icon cho GCP service)
- Missing component quan trọng từ Project Brief
- Unreadable text (font < 8pt effective)
- Complete layout chaos (không có hierarchy)

Chấm điểm nghiêm túc và khách quan.`,
      {
        label: `Review: ${dim.name}`,
        schema: REVIEW_SCHEMA,
        phase: 'Multi-lens Review',
      }
    )
  }
)

// ─── Phase 3: Verdict ────────────────────────────────────────────────────────

phase('Verdict')

const validReviews = reviews.filter(Boolean)
const weightedScore = validReviews.reduce((sum, r) => sum + r.score * r.weight, 0)
const allRedFlags = validReviews.flatMap(r => r.red_flags_triggered)
const allBlockers = validReviews.flatMap(r => r.defects.filter(d => d.severity === 'blocker'))

const hasAutoFail = allRedFlags.length > 0 || allBlockers.length > 0
const PASS_THRESHOLD = 3.5
const verdict = hasAutoFail ? 'FAIL' : weightedScore >= PASS_THRESHOLD ? 'PASS' : 'REVISE'

log(`Score: ${weightedScore.toFixed(2)}/5.0 → ${verdict} (${allRedFlags.length} red flags, ${allBlockers.length} blockers)`)

const finalReport = await agent(
  `Tạo báo cáo quality review cuối cùng.

DIAGRAM: ${context.diagram_path}
OVERALL SCORE: ${weightedScore.toFixed(2)}/5.0
VERDICT: ${verdict}

SCORES BY DIMENSION:
${validReviews.map(r => `- ${r.dimension}: ${r.score}/5 (weight=${r.weight})`).join('\n')}

RED FLAGS TRIGGERED:
${allRedFlags.length > 0 ? allRedFlags.map(f => `- ⛔ ${f}`).join('\n') : '✅ None'}

BLOCKERS:
${allBlockers.length > 0 ? allBlockers.map(b => `- 🚫 ${b.description} → Fix: ${b.fix}`).join('\n') : '✅ None'}

ALL DEFECTS:
${validReviews.flatMap(r => r.defects).map(d => `[${d.severity.toUpperCase()}] ${d.description} → ${d.fix}`).join('\n')}

KEY OBSERVATIONS:
${validReviews.flatMap(r => r.observations.slice(0, 2)).join('\n')}

TẠO BÁO CÁO MARKDOWN với:
1. Verdict badge (🟢 PASS / 🟡 REVISE / 🔴 FAIL)
2. Score card (table 5 dimensions)
3. Critical actions (nếu REVISE/FAIL)
4. What's working well (luôn có, dù FAIL)
5. Next steps cụ thể

Ngắn gọn, actionable, tiếng Việt.`,
  { label: 'Verdict: final report' }
)

return {
  diagram_path: context.diagram_path,
  score: weightedScore,
  verdict,
  dimension_scores: validReviews.map(r => ({ name: r.dimension, score: r.score, weight: r.weight })),
  red_flags: allRedFlags,
  blockers: allBlockers,
  report: finalReport,
}
