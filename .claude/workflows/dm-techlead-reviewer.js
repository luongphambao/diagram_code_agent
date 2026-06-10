export const meta = {
  name: 'dm-techlead-reviewer',
  description: 'DM phân tích yêu cầu → TechLead review impl & issues → Reviewer tạo benchmark chất lượng diagram',
  phases: [
    { title: 'DM: Phân tích yêu cầu', detail: 'Đọc Project Brief, phân tích luồng agent, tạo task list' },
    { title: 'TechLead: Review impl', detail: 'Review code hiện tại, identify issues, đề xuất fix' },
    { title: 'Reviewer: Quality Benchmark', detail: 'Tạo tiêu chuẩn benchmark về thẩm mỹ, nội dung, bố cục, logo' },
    { title: 'Synthesis', detail: 'Tổng hợp tất cả findings thành báo cáo hành động' },
  ],
}

// ─── Schemas ───────────────────────────────────────────────────────────────

const DM_SCHEMA = {
  type: 'object',
  properties: {
    project_summary: { type: 'string' },
    core_requirements: {
      type: 'array',
      items: { type: 'string' },
    },
    agent_flow_analysis: {
      type: 'object',
      properties: {
        current_flow: { type: 'string' },
        proposed_improvements: { type: 'array', items: { type: 'string' } },
      },
      required: ['current_flow', 'proposed_improvements'],
    },
    diagram_requirements: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          title: { type: 'string' },
          description: { type: 'string' },
          priority: { type: 'string', enum: ['P0', 'P1', 'P2'] },
          acceptance_criteria: { type: 'array', items: { type: 'string' } },
        },
        required: ['id', 'title', 'description', 'priority', 'acceptance_criteria'],
      },
    },
    task_list: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          task_id: { type: 'string' },
          title: { type: 'string' },
          type: { type: 'string', enum: ['feature', 'improvement', 'fix', 'quality'] },
          description: { type: 'string' },
          files_affected: { type: 'array', items: { type: 'string' } },
          priority: { type: 'string', enum: ['P0', 'P1', 'P2'] },
        },
        required: ['task_id', 'title', 'type', 'description', 'files_affected', 'priority'],
      },
    },
  },
  required: ['project_summary', 'core_requirements', 'agent_flow_analysis', 'diagram_requirements', 'task_list'],
}

const TECHLEAD_SCHEMA = {
  type: 'object',
  properties: {
    implementation_health: {
      type: 'object',
      properties: {
        score: { type: 'number' },
        summary: { type: 'string' },
      },
      required: ['score', 'summary'],
    },
    issues: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          category: { type: 'string', enum: ['architecture', 'quality', 'performance', 'prompt', 'tool', 'ux'] },
          file: { type: 'string' },
          line_hint: { type: 'string' },
          description: { type: 'string' },
          proposed_fix: { type: 'string' },
        },
        required: ['id', 'severity', 'category', 'file', 'description', 'proposed_fix'],
      },
    },
    diagram_quality_gaps: {
      type: 'array',
      items: { type: 'string' },
    },
    quick_wins: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          effort: { type: 'string', enum: ['1h', '2h', '4h', '1d'] },
          impact: { type: 'string' },
        },
        required: ['title', 'effort', 'impact'],
      },
    },
  },
  required: ['implementation_health', 'issues', 'diagram_quality_gaps', 'quick_wins'],
}

const BENCHMARK_SCHEMA = {
  type: 'object',
  properties: {
    benchmark_version: { type: 'string' },
    description: { type: 'string' },
    dimensions: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          name: { type: 'string' },
          weight: { type: 'number' },
          description: { type: 'string' },
          rubric: {
            type: 'object',
            properties: {
              score_5: { type: 'string' },
              score_4: { type: 'string' },
              score_3: { type: 'string' },
              score_2: { type: 'string' },
              score_1: { type: 'string' },
            },
            required: ['score_5', 'score_4', 'score_3', 'score_2', 'score_1'],
          },
          checklist: { type: 'array', items: { type: 'string' } },
          common_defects: { type: 'array', items: { type: 'string' } },
        },
        required: ['name', 'weight', 'description', 'rubric', 'checklist', 'common_defects'],
      },
    },
    scoring_formula: { type: 'string' },
    pass_threshold: { type: 'number' },
    red_flags: { type: 'array', items: { type: 'string' } },
    reference_examples: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          tier: { type: 'string', enum: ['gold', 'silver', 'needs_work'] },
          description: { type: 'string' },
          score_range: { type: 'string' },
          characteristics: { type: 'array', items: { type: 'string' } },
        },
        required: ['tier', 'description', 'score_range', 'characteristics'],
      },
    },
  },
  required: ['benchmark_version', 'description', 'dimensions', 'scoring_formula', 'pass_threshold', 'red_flags', 'reference_examples'],
}

// ─── Phase 1: DM ────────────────────────────────────────────────────────────

phase('DM: Phân tích yêu cầu')

const dmAnalysis = await agent(
  `Bạn là DM (Delivery Manager) cho dự án Diagram Code Agent.

NHIỆM VỤ: Đọc Project Brief và phân tích toàn bộ codebase để tạo task list có cấu trúc.

BƯỚC 1 - Đọc Project Brief:
Chạy lệnh Bash: pandoc "/home/baoluong/projects/diagram_code_agent/requirement/Project Brief.docx" -t plain

BƯỚC 2 - Đọc Software Spec (nếu cần thêm context):
Chạy lệnh Bash: pandoc "/home/baoluong/projects/diagram_code_agent/requirement/Project Aila Software Specification v1.0_EN.docx" -t plain 2>/dev/null | head -200

BƯỚC 3 - Đọc các file core:
- /home/baoluong/projects/diagram_code_agent/backend/src/diagram_mcp/agent.py
- /home/baoluong/projects/diagram_code_agent/backend/src/diagram_mcp/prompts.py
- /home/baoluong/projects/diagram_code_agent/backend/src/diagram_mcp/tools.py

BƯỚC 4 - Đọc eval và quality files:
- /home/baoluong/projects/diagram_code_agent/backend/src/diagram_mcp/quality_logger.py
- Chạy: find /home/baoluong/projects/diagram_code_agent/backend/evals -name "*.py" | head -5

PHÂN TÍCH & OUTPUT:
Dựa trên tất cả thông tin trên, tạo ra:
1. project_summary: Tóm tắt dự án và mục tiêu POC
2. core_requirements: Các yêu cầu cốt lõi từ Project Brief
3. agent_flow_analysis: Phân tích luồng agent hiện tại và đề xuất cải tiến
4. diagram_requirements: Các yêu cầu cụ thể về diagram (từ Project Brief + Software Spec)
   - Mỗi requirement cần có: id, title, description, priority (P0/P1/P2), acceptance_criteria
5. task_list: Danh sách tasks cụ thể, actionable để implement/improve
   - Mỗi task: task_id, title, type (feature/improvement/fix/quality), description, files_affected, priority

Tập trung vào: chất lượng diagram output, độ chính xác architecture diagram, trải nghiệm người dùng.`,
  { label: 'DM: phân tích requirements', schema: DM_SCHEMA }
)

log(`DM tạo được ${dmAnalysis.task_list.length} tasks và ${dmAnalysis.diagram_requirements.length} diagram requirements`)

// ─── Phase 2: TechLead ──────────────────────────────────────────────────────

phase('TechLead: Review impl')

// TechLead chạy parallel review trên các khía cạnh khác nhau
const techLeadResults = await parallel([
  () => agent(
    `Bạn là TechLead senior cho dự án Diagram Code Agent.

CONTEXT từ DM:
- Project summary: ${dmAnalysis.project_summary}
- Core requirements: ${dmAnalysis.core_requirements.join('; ')}
- Tasks từ DM: ${dmAnalysis.task_list.map(t => t.title).join(', ')}

NHIỆM VỤ: Review agent architecture và prompt quality.

Đọc các file sau:
- /home/baoluong/projects/diagram_code_agent/backend/src/diagram_mcp/agent.py
- /home/baoluong/projects/diagram_code_agent/backend/src/diagram_mcp/prompts.py

Tìm issues trong:
1. Agent flow logic (staged pipeline, subagent calls, HITL)
2. Prompt engineering (clarity, specificity, hallucination risks)
3. Error handling và fallback logic
4. Memory/state management

Output issues theo format schema. Category = 'architecture' hoặc 'prompt'.`,
    { label: 'TechLead: agent+prompt review', schema: TECHLEAD_SCHEMA }
  ),
  () => agent(
    `Bạn là TechLead senior cho dự án Diagram Code Agent.

CONTEXT từ DM:
- Diagram requirements: ${JSON.stringify(dmAnalysis.diagram_requirements.slice(0, 3))}
- Quality tasks: ${dmAnalysis.task_list.filter(t => t.type === 'quality').map(t => t.title).join(', ')}

NHIỆM VỤ: Review tools, rendering và diagram quality pipeline.

Đọc các file sau:
- /home/baoluong/projects/diagram_code_agent/backend/src/diagram_mcp/tools.py
- /home/baoluong/projects/diagram_code_agent/backend/src/diagram_mcp/quality_logger.py
- /home/baoluong/projects/diagram_code_agent/backend/src/diagram_mcp/prettygraph.py (nếu tồn tại)

Chạy: find /home/baoluong/projects/diagram_code_agent/backend/evals -name "*.py" | xargs head -30 2>/dev/null

Tìm issues trong:
1. Rendering pipeline (graphviz → drawio conversion accuracy)
2. Quality metrics (eval completeness, blind spots)
3. Logo/icon fetching reliability
4. Tool API design (naming, parameters, error codes)

Output issues. Category = 'tool', 'quality', hoặc 'performance'.`,
    { label: 'TechLead: tools+rendering review', schema: TECHLEAD_SCHEMA }
  ),
])

// Merge TechLead results
const mergedIssues = techLeadResults
  .filter(Boolean)
  .flatMap(r => r.issues)
  .map((issue, i) => ({ ...issue, id: `ISSUE-${String(i + 1).padStart(3, '0')}` }))

const mergedQuickWins = techLeadResults
  .filter(Boolean)
  .flatMap(r => r.quick_wins)

const mergedDiagramGaps = [...new Set(
  techLeadResults.filter(Boolean).flatMap(r => r.diagram_quality_gaps)
)]

const avgHealth = techLeadResults.filter(Boolean)
  .reduce((sum, r) => sum + r.implementation_health.score, 0) / techLeadResults.filter(Boolean).length

log(`TechLead tìm được ${mergedIssues.length} issues (${mergedIssues.filter(i => i.severity === 'critical').length} critical), ${mergedQuickWins.length} quick wins`)

// ─── Phase 3: Reviewer ──────────────────────────────────────────────────────

phase('Reviewer: Quality Benchmark')

const qualityBenchmark = await agent(
  `Bạn là Reviewer chuyên về chất lượng diagram kỹ thuật (architecture diagrams, flow diagrams, system diagrams).

CONTEXT:
- Dự án: ${dmAnalysis.project_summary}
- Các diagram requirements từ DM: ${dmAnalysis.diagram_requirements.map(r => r.title).join(', ')}
- Diagram quality gaps từ TechLead: ${mergedDiagramGaps.join('; ')}

ĐỌC THÊM CONTEXT:
1. Đọc /home/baoluong/projects/diagram_code_agent/backend/src/diagram_mcp/prompts.py để hiểu tiêu chuẩn hiện tại
2. Chạy: find /home/baoluong/projects/diagram_code_agent/backend/evals -name "*.json" | head -3 | xargs head -50 2>/dev/null

NHIỆM VỤ: Tạo BENCHMARK CHUẨN để đánh giá chất lượng diagram output.

Benchmark phải cover 5 dimensions sau (total weight = 1.0):

1. **Thẩm mỹ / Visual Aesthetics** (weight ~0.20)
   - Color harmony (consistent palette, không chói, professional)
   - Spacing & padding đồng đều
   - Font size hierarchy (title > label > description)
   - Visual noise (không cluttered)

2. **Nội dung / Content Accuracy** (weight ~0.30)
   - Nodes đúng với yêu cầu (không thiếu, không thừa)
   - Labels chính xác, không viết tắt khó hiểu
   - Edge labels mô tả đúng relationship
   - Tech stack accuracy (đúng công nghệ với use case)

3. **Bố cục / Layout & Composition** (weight ~0.25)
   - Hierarchy rõ ràng (L→R hoặc T→B nhất quán)
   - Grouping hợp lý (clusters phản ánh đúng domain boundaries)
   - Cross-edge tối thiểu (không spider web)
   - Cân đối trái/phải và trên/dưới

4. **Logo & Icon Quality** (weight ~0.15)
   - Logo đúng brand (AWS, GCP, Azure, không nhầm)
   - Resolution đủ rõ (không pixelated, không blurry)
   - Icon size nhất quán trong cùng cluster
   - Không dùng generic shape khi có branded icon

5. **Readability & Clarity** (weight ~0.10)
   - Diagram đọc được ở 100% zoom không cần scroll
   - Legend hoặc title rõ ràng nếu cần
   - Màu sắc accessible (không dùng red/green làm phân biệt duy nhất)
   - Không overlap text với shape

Với mỗi dimension, viết rubric 5 mức (1=rất tệ, 5=xuất sắc) và checklist cụ thể.

Cũng đưa ra:
- scoring_formula: cách tính overall score từ 5 dimensions
- pass_threshold: điểm tối thiểu để PASS (e.g., 3.5/5.0)
- red_flags: các lỗi nghiêm trọng tự động FAIL dù tổng điểm cao
- reference_examples: mô tả các tier (gold/silver/needs_work)`,
  { label: 'Reviewer: quality benchmark', schema: BENCHMARK_SCHEMA }
)

log(`Reviewer tạo benchmark với ${qualityBenchmark.dimensions.length} dimensions, pass threshold = ${qualityBenchmark.pass_threshold}/5.0`)

// ─── Phase 4: Synthesis ─────────────────────────────────────────────────────

phase('Synthesis')

const report = await agent(
  `Bạn là technical writer. Tổng hợp tất cả findings từ DM, TechLead, và Reviewer thành một báo cáo hành động rõ ràng.

=== DM FINDINGS ===
Project: ${dmAnalysis.project_summary}

Core Requirements:
${dmAnalysis.core_requirements.map((r, i) => `${i + 1}. ${r}`).join('\n')}

Task List (${dmAnalysis.task_list.length} tasks):
${dmAnalysis.task_list.map(t => `[${t.priority}] ${t.task_id}: ${t.title} (${t.type})`).join('\n')}

Diagram Requirements:
${dmAnalysis.diagram_requirements.map(r => `[${r.priority}] ${r.id}: ${r.title}`).join('\n')}

=== TECHLEAD FINDINGS ===
Implementation Health Score: ${avgHealth.toFixed(1)}/10

Critical Issues:
${mergedIssues.filter(i => i.severity === 'critical').map(i => `- [${i.id}] ${i.file}: ${i.description}`).join('\n') || 'None'}

High Severity Issues:
${mergedIssues.filter(i => i.severity === 'high').map(i => `- [${i.id}] ${i.category}: ${i.description}`).join('\n')}

Quick Wins (top 5):
${mergedQuickWins.slice(0, 5).map(w => `- ${w.title} (${w.effort}, impact: ${w.impact})`).join('\n')}

Diagram Quality Gaps:
${mergedDiagramGaps.map(g => `- ${g}`).join('\n')}

=== REVIEWER BENCHMARK ===
Version: ${qualityBenchmark.benchmark_version}
Pass Threshold: ${qualityBenchmark.pass_threshold}/5.0

Dimensions:
${qualityBenchmark.dimensions.map(d => `- ${d.name} (weight=${d.weight}): ${d.description}`).join('\n')}

Red Flags (auto-fail):
${qualityBenchmark.red_flags.map(f => `- ${f}`).join('\n')}

=== OUTPUT YÊU CẦU ===
Tạo báo cáo markdown với cấu trúc:
1. Executive Summary (3-4 câu)
2. Priority Action Items (top 5, ưu tiên P0 critical trước)
3. Sprint Planning Suggestion (chia 3 sprint: S1=critical fixes, S2=quality, S3=polish)
4. Quality Gate Checklist (dựa trên Reviewer benchmark, dạng checkbox)
5. Open Questions cần DM/stakeholder trả lời

Viết bằng tiếng Việt, ngắn gọn, actionable.`,
  { label: 'Synthesis: tổng hợp báo cáo' }
)

// ─── Return full structured output ──────────────────────────────────────────

return {
  dm: dmAnalysis,
  techlead: {
    health_score: avgHealth,
    issues: mergedIssues,
    diagram_quality_gaps: mergedDiagramGaps,
    quick_wins: mergedQuickWins,
  },
  reviewer: qualityBenchmark,
  synthesis_report: report,
}
