"""Canonical BnK proposal-deck section registry — the backbone for section-by-section generation.

Reverse-engineered from ~10 real BnK proposal decks (``DATA/SLIDE_IMAGES/*/slide_text.json``:
Clinic Management, DAMS Phase 2, Driver Safe, FSD Chat, Maritime ERP, Makalot, Aquila,
Ex Umbra). Every real BnK proposal follows the SAME backbone — 15-25 slides across 4-6
Roman-numeral sections, each opened by a ``Head Page`` divider then ``SECTION | Sub-topic``
``Detail-01`` slides:

    Cover -> [Agenda] -> I. Executive Summary -> II. Success Story -> III. Solution Proposal
    (+ Scope of Work + Project Delivery) -> IV/V. Pricing -> [Reference] -> Thank you / BnK.

This module turns that backbone into a machine-readable list of **content contracts**. Each
:class:`SectionContract` says, for one slide type: the fixed title, the content ``params`` a
generator must fill, the ``required_inputs`` that must resolve (or the slide is *skipped, not
rendered thin*), where the data comes from, and which ``ppt_reporting`` render block/layout it
maps to.

Why it exists — the "no content" bug: today ``deck.build_deck_plan`` and
``ppt_reporting._generate_slide_outline`` draw from architecture-centric JSON
(``diagram_brief`` / ``tech_stack`` / ``wbs``) that has no business-narrative fields, so
whole sections (problem, success story, goals & value, KPIs, client info) are structurally
absent and the deterministic path silently degrades to empty bullets. A generator that
iterates this registry can, per section: (1) know exactly which params to fill, (2) know
whether its inputs are present and **skip + warn** when they are not (rather than emit an
empty-feeling slide), and (3) fail in isolation instead of voiding the whole 20-30 slide
outline.

Wiring (spec — not yet applied):
    * ``deck.build_deck_plan`` iterates ``SECTION_CONTENT_CONTRACTS`` instead of its current
      hand-written linear ``add(...)`` sequence; each contract's data is resolved from the
      CSM + ``business_narrative.json`` (a NEW upstream artifact, see ``required_inputs``).
    * ``ppt_reporting`` gains the ``status != "ready"`` blocks (``goals_value``,
      ``case_study``, ``feature_list``, ``change_request``, ``methodology``, ``post_launch``,
      ``risk_table``, ``opex``) in ``VALID_BLOCKS`` + a renderer each, mirroring the existing
      ``_team_slide`` / ``_pricing_slide`` pattern.

Pure data + stdlib only (no ``csm`` / ``ppt_reporting`` import) so any layer can read it
without an import cycle — same discipline as ``deck.py`` itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# --- vocabularies (MUST stay in sync with ppt_reporting + deck) --------------

# Layout names — MUST match ppt_reporting.VALID_LAYOUTS exactly (note the literal
# spacing in the separator layout name). "" = cover has no titled layout dispatch.
Layout = Literal[
    "Cover-01", "Head Page", "Head-01", "Detail-01", "Overview-01", "Empty",
    "BnK", "C2 -  Separator/ Dark",
]

# Render blocks. The first 8 already exist in ppt_reporting.VALID_BLOCKS; the rest are
# NEW blocks this registry specifies (status="new_block"/"new_block+new_data").
Block = Literal[
    # --- already implemented in ppt_reporting ---
    "bullets", "tech_stack_table", "func_nfr", "sdlc", "delivery_effort",
    "pricing", "milestones", "team",
    # --- specified here, renderer NOT yet built ---
    "agenda", "goals_value", "case_study", "feature_list", "change_request",
    "methodology", "post_launch", "risk_table", "opex", "kpis", "client_info",
    "diagram",  # architecture image slide (Empty layout + asset_ref)
    "cover", "divider", "closing",  # structural — no params to generate
]

# Narrative role — MUST be a superset-compatible value for deck.NarrativeRole. The 5 marked
# NEW must be added to deck.NarrativeRole when this registry is wired in.
Role = Literal[
    "context", "objective", "solution", "architecture", "scope", "effort",
    "timeline", "risk", "pricing",
    "case_study", "kpis", "client_info", "advice",  # NEW roles
]

# Implementation status of the render block backing a contract.
Status = Literal[
    "ready",                 # block + data source both exist today
    "new_block",             # data exists; needs a renderer in ppt_reporting
    "new_block+new_data",    # needs BOTH a renderer AND business_narrative.json data
    "structural",            # cover/divider/closing — no content generation needed
]


@dataclass(frozen=True)
class Param:
    """One content field a generator must fill for a slide.

    ``name`` is the key the render block reads; ``desc`` is the generation instruction
    handed to the LLM (or the deterministic builder's contract); ``required`` slides with a
    missing required param are skipped (see :func:`resolve_missing`).
    """

    name: str
    desc: str
    required: bool = True


@dataclass(frozen=True)
class SectionContract:
    """One slide type in the canonical BnK proposal backbone."""

    key: str                              # stable id, e.g. "exec_summary_overview"
    section: str                          # major section bucket (matches DEFAULT_PPT_SECTIONS)
    kind: Literal["cover", "divider", "content", "closing"]
    title: str                            # fixed title template ("SECTION | Sub-topic"); "" for cover/closing
    role: Role
    layout: Layout
    block: Block
    data_source: str                      # human-readable: where the data comes from
    status: Status
    params: tuple[Param, ...] = ()        # content fields to generate (empty for structural slides)
    required_inputs: tuple[str, ...] = () # upstream artifact.field keys that must resolve, or skip
    slide_count: tuple[int, int] = (1, 1) # (min, max) slides this contract may emit
    optional: bool = False               # whether the whole section may be omitted
    notes: str = ""


def _p(name: str, desc: str, required: bool = True) -> Param:
    return Param(name=name, desc=desc, required=required)


# =============================================================================
# THE REGISTRY — ordered as a deck is built, top to bottom.
# =============================================================================

SECTION_CONTENT_CONTRACTS: tuple[SectionContract, ...] = (

    # ---- 0. Cover ----------------------------------------------------------
    SectionContract(
        key="cover", section="cover", kind="cover",
        title="", role="context", layout="Cover-01", block="cover",
        data_source="blueprint.json (slide_title/brand) + brief.objective",
        status="ready",
        params=(
            _p("project_title", "Deck title, e.g. 'Clinic Management System' / 'DAMS Phase 2'."),
            _p("date", "Proposal month/year, e.g. 'July, 2025'."),
            _p("client_brand", "Client / brand name shown on the cover.", required=False),
        ),
        required_inputs=("blueprint.slide_title|brief.objective",),
        slide_count=(1, 1),
        notes="Slide 1. Renderer already exists (_cover_slide).",
    ),

    # ---- Agenda (optional; present in CMA/TFSVN/Makalot/Aquila) -------------
    SectionContract(
        key="agenda", section="agenda", kind="content",
        title="Agenda", role="context", layout="Detail-01", block="agenda",
        data_source="derived from the section list of THIS deck",
        status="new_block",
        params=(
            _p("section_list", "Ordered list of the Roman-numeral sections in this deck."),
        ),
        slide_count=(0, 1), optional=True,
        notes="Not universal. Cheap: list of divider titles. Skip if deck is short.",
    ),

    # ---- I. Executive Summary ---------------------------------------------
    SectionContract(
        key="exec_summary_divider", section="executive_summary", kind="divider",
        title="{roman}. Executive Summary", role="context", layout="Head Page", block="divider",
        data_source="—", status="structural",
        params=(_p("roman", "Auto-assigned Roman numeral for this section.", required=False),),
        slide_count=(1, 1),
    ),
    SectionContract(
        key="exec_summary_overview", section="executive_summary", kind="content",
        title="EXECUTIVE SUMMARY | Overview", role="objective", layout="Detail-01", block="bullets",
        data_source="brief.objective + top business requirements (CSM req.kind=='business')",
        status="ready",
        params=(
            _p("intro_paragraph", "1-2 sentence description of what the system is/does."),
            _p("key_objectives", "3-5 bullets: the key objectives the system addresses."),
        ),
        required_inputs=("brief.objective",),
        slide_count=(1, 1),
    ),
    SectionContract(
        key="exec_summary_goals_value", section="executive_summary", kind="content",
        title="EXECUTIVE SUMMARY | Goals & Value Proposition", role="objective",
        layout="Detail-01", block="goals_value",
        data_source="business_narrative.json.value_props (NEW) — else derive from business reqs",
        status="new_block+new_data",
        params=(
            _p("value_props", "3-4 numbered value propositions, each: title + 1-2 sub-bullets "
                              "(e.g. 'Improve Road Safety', 'Simplify Fleet Management')."),
        ),
        required_inputs=("business_narrative.value_props",),
        slide_count=(0, 1), optional=True,
        notes="Common in polished decks (Driver Safe, Ex Umbra). Needs business_narrative.json.",
    ),

    # ---- II. Success Story -------------------------------------------------
    SectionContract(
        key="success_story_divider", section="success_story", kind="divider",
        title="{roman}. Success Story", role="case_study", layout="Head Page", block="divider",
        data_source="—", status="structural",
        params=(_p("roman", "Auto-assigned Roman numeral.", required=False),),
        slide_count=(0, 1), optional=True,
    ),
    SectionContract(
        key="success_story", section="success_story", kind="content",
        title="SUCCESS STORY | {case_title}", role="case_study", layout="Detail-01", block="case_study",
        data_source="business_narrative.json.case_study (NEW): title/context/outcome/image",
        status="new_block+new_data",
        params=(
            _p("case_title", "Short name of the reference case, e.g. 'Smart Agriculture'."),
            _p("context_paragraph", "Context: who the client was and what problem they had."),
            _p("outcome", "What BnK delivered and the measurable outcome.", required=False),
            _p("image_ref", "Optional screenshot/photo of the reference solution.", required=False),
        ),
        required_inputs=("business_narrative.case_study",),
        slide_count=(0, 2), optional=True,
        notes="Reuses Detail-01 + _image_fit (case studies are just Detail-01 with pictures — "
              "no dedicated template layout). Skip cleanly if no case study is on file.",
    ),

    # ---- III. Solution Proposal -------------------------------------------
    SectionContract(
        key="solution_divider", section="solution_overview", kind="divider",
        title="{roman}. Solution Proposal", role="solution", layout="Head Page", block="divider",
        data_source="—", status="structural",
        params=(_p("roman", "Auto-assigned Roman numeral.", required=False),),
        slide_count=(1, 1),
    ),
    SectionContract(
        key="solution_name", section="solution_overview", kind="content",
        title="Solution Proposal", role="solution", layout="Overview-01", block="bullets",
        data_source="blueprint.slide_title / brief",
        status="ready",
        params=(
            _p("solution_name", "The named solution, shown large (e.g. 'CLINIC MANAGEMENT')."),
            _p("subtitle", "One-line scope subtitle, e.g. 'Proposed Solution | Scope | Delivery'.",
               required=False),
        ),
        slide_count=(1, 1),
        notes="Overview-01: put subtitle in bullets[0].",
    ),
    SectionContract(
        key="solution_overview", section="solution_overview", kind="content",
        title="PROPOSED SOLUTION | Overview", role="solution", layout="Detail-01", block="func_nfr",
        data_source="brief.functional_requirements + brief.non_functional_requirements (CSM reqs)",
        status="ready",
        params=(
            _p("functionality", "Grouped functional capabilities (feature group -> sub-points)."),
            _p("non_functionality", "Non-functional requirements (performance, security, privacy…)."),
        ),
        required_inputs=("brief.functional_requirements",),
        slide_count=(1, 1),
    ),
    SectionContract(
        key="solution_feature_list", section="solution_overview", kind="content",
        title="PROPOSED SOLUTION | Feature List", role="solution", layout="Detail-01", block="feature_list",
        data_source="brief.functional_requirements / blueprint (condensed to feature + one-liner)",
        status="new_block",
        params=(
            _p("features", "4-6 features, each: name (bold) + one-line description."),
        ),
        required_inputs=("brief.functional_requirements",),
        slide_count=(0, 1), optional=True,
        notes="Condensed sibling of the Overview func/nfr slide; common in feature-heavy decks.",
    ),
    SectionContract(
        key="solution_tech_stack", section="technical_stack", kind="content",
        title="PROPOSED SOLUTION | Technical Stack", role="solution", layout="Detail-01",
        block="tech_stack_table",
        data_source="tech_stack.json.layers (Layer / Technology / Rationale)",
        status="ready",
        params=(
            _p("tech_rows", "Table rows: Layer | Technology | Description, one per stack layer."),
        ),
        required_inputs=("tech_stack.layers",),
        slide_count=(1, 1),
        notes="client_facing=True (cites versions) -> wants an Evidence source_ref.",
    ),
    SectionContract(
        key="solution_architecture", section="architecture_diagram", kind="content",
        title="PROPOSED SOLUTION | Data Flow Architecture", role="architecture", layout="Empty",
        block="diagram",
        data_source="rendered diagram out.png / out.body.png",
        status="ready",
        params=(
            _p("diagram_image", "Full-width architecture / data-flow diagram image (out.png)."),
        ),
        required_inputs=("out.png",),
        slide_count=(0, 2), optional=True,
        notes="Emit ONLY when a rendered diagram exists (has_diagram). Often preceded by a "
              "Head-01 'Architecture Overview' sub-header.",
    ),

    # ---- IV. Scope of Work (rendered under Solution or its own section) ----
    SectionContract(
        key="scope_sdlc", section="scope", kind="content",
        title="SCOPE OF WORK | SDLC Phases", role="scope", layout="Detail-01", block="sdlc",
        data_source="deterministic SDLC template (Analysis→Maintenance) + brief for in/out scope",
        status="ready",
        params=(
            _p("sdlc_phases", "6 phases (Analysis, Design, Development, Testing, Deployment, "
                             "Maintenance), each with in-scope and out-of-scope notes."),
        ),
        slide_count=(1, 3),
        notes="Frequently spans 2-3 physical slides in real decks (SCOPE OF WORK x2-3).",
    ),
    SectionContract(
        key="scope_change_request", section="scope", kind="content",
        title="SCOPE OF WORK | Change Request Definition", role="scope", layout="Detail-01",
        block="change_request",
        data_source="fixed BnK change-request process template",
        status="new_block",
        params=(
            _p("change_request_process", "The standard BnK change-request handling process.",
               required=False),
        ),
        slide_count=(0, 1), optional=True,
        notes="Near-boilerplate; a static default is acceptable when unspecified.",
    ),

    # ---- V. Project Delivery ----------------------------------------------
    SectionContract(
        key="delivery_divider", section="delivery_plan", kind="divider",
        title="{roman}. Project Delivery", role="effort", layout="Head Page", block="divider",
        data_source="—", status="structural",
        params=(_p("roman", "Auto-assigned Roman numeral.", required=False),),
        slide_count=(0, 1), optional=True,
        notes="Some decks fold delivery under Solution Proposal without its own divider.",
    ),
    SectionContract(
        key="delivery_effort", section="delivery_plan", kind="content",
        title="PROJECT DELIVERY | Estimated Effort", role="effort", layout="Detail-01",
        block="delivery_effort",
        data_source="wbs.json.effort_totals + effort_by_module + P50/P80",
        status="ready",
        params=(
            _p("total_md", "Total effort in man-days, e.g. 'Total Effort: 82 MDs'."),
            _p("effort_rows", "Per-module effort table: Module | MD (from WBS roll-up)."),
        ),
        required_inputs=("wbs.effort_totals",),
        slide_count=(1, 1),
        notes="validate_deck enforces the stated total matches the WBS roll-up.",
    ),
    SectionContract(
        key="delivery_master_plan", section="delivery_plan", kind="content",
        title="PROJECT DELIVERY | Master Plan & Milestones", role="timeline", layout="Detail-01",
        block="gantt",
        data_source="wbs.json.phases (module effort) + timeline.weeks, scheduled via the SAME "
                    "waterfall allocator as the '3. Delivery Plan' Excel sheet (wbs_excel._module_schedule)",
        status="new_block",
        params=(
            _p("months", "Number of calendar months in the grid (weeks/4, rounded up)."),
            _p("sprints", "Number of 2-week sprints in the grid."),
            _p("weeks", "Total project duration in weeks."),
            _p("gantt_rows", "One row per module: code, name, start_week, end_week — "
                             "the colored Gantt bar spans [start_week, end_week]."),
        ),
        required_inputs=("wbs.timeline", "wbs.phases|wbs.effort_by_module"),
        slide_count=(1, 1),
        notes="Mirrors the real 'Master Plan' Gantt in the WBS Excel '3. Delivery Plan' sheet "
              "(same screenshot the user showed) — same schedule model, not a re-derivation.",
    ),
    SectionContract(
        key="delivery_risk", section="risks", kind="content",
        title="PROJECT DELIVERY | Risk & Mitigation", role="risk", layout="Detail-01",
        block="risk_table",
        data_source="CSM risks (risk.statement + risk.mitigation)",
        status="new_block",
        params=(
            _p("risks", "Risk | Mitigation table rows. Falls back to a 2-column bullet list."),
        ),
        required_inputs=("csm.risks",),
        slide_count=(0, 1), optional=True,
        notes="Renders as bullets today; a proper 2-col table (risk_table) matches the real decks.",
    ),
    SectionContract(
        key="delivery_methodology", section="delivery_plan", kind="content",
        title="PROJECT DELIVERY | Development Methodology", role="effort", layout="Detail-01",
        block="methodology",
        data_source="fixed template (Agile/Scrum; PM as Scrum Master)",
        status="new_block",
        params=(
            _p("methodology", "Delivery methodology description (Agile/Scrum cadence, roles).",
               required=False),
        ),
        slide_count=(0, 1), optional=True,
        notes="Near-boilerplate; static default acceptable.",
    ),
    SectionContract(
        key="delivery_post_launch", section="delivery_plan", kind="content",
        title="PROJECT DELIVERY | Post-Launch Support", role="effort", layout="Detail-01",
        block="post_launch",
        data_source="fixed SLA template (Ticket -> Analyze -> Propose -> ... -> Close)",
        status="new_block",
        params=(
            _p("sla_process", "Post-launch support SLA steps.", required=False),
        ),
        slide_count=(0, 1), optional=True,
        notes="Near-boilerplate; static default acceptable.",
    ),
    SectionContract(
        key="delivery_team", section="delivery_plan", kind="content",
        title="PROJECT DELIVERY | Team Structure", role="effort", layout="Detail-01", block="team",
        data_source="fixed Client-Team vs BnK-Team template",
        status="ready",
        params=(
            _p("client_team", "Client-side roles (Technical Lead, BA, PM).", required=False),
            _p("bnk_team", "BnK-side roles (Tech Lead, Devs, BA/Tester, PM).", required=False),
        ),
        slide_count=(0, 1), optional=True,
    ),

    # ---- VI. Pricing -------------------------------------------------------
    SectionContract(
        key="pricing_divider", section="pricing", kind="divider",
        title="{roman}. Pricing", role="pricing", layout="Head Page", block="divider",
        data_source="—", status="structural",
        params=(_p("roman", "Auto-assigned Roman numeral.", required=False),),
        slide_count=(1, 1),
    ),
    SectionContract(
        key="pricing_capex", section="pricing", kind="content",
        title="PRICING | CAPEX", role="pricing", layout="Detail-01", block="pricing",
        data_source="wbs.json cost roll-up + tech_stack cost (NET, tax-excluded)",
        status="ready",
        params=(
            _p("total_cost", "Total cost + currency, e.g. 'Total Cost: 17.5MM USD (NET)'."),
            _p("cost_rows", "Cost-structure table derived from the WBS."),
            _p("net_note", "Note that the quotation is NET / tax not included.", required=False),
        ),
        required_inputs=("wbs.effort_totals",),
        slide_count=(1, 1),
        notes="client_facing=True -> wants an Evidence source_ref behind pricing claims.",
    ),
    SectionContract(
        key="pricing_opex", section="pricing", kind="content",
        title="PRICING | OPEX", role="pricing", layout="Detail-01", block="opex",
        data_source="tech_stack.json recurring/operational cost estimates",
        status="new_block",
        params=(
            _p("opex_rows", "Recurring/operational cost table (monthly/annual)."),
        ),
        required_inputs=("tech_stack.opex|tech_stack.cost",),
        slide_count=(0, 1), optional=True,
        notes="Present only when the engagement has recurring costs (Clinic, Maritime).",
    ),
    SectionContract(
        key="pricing_milestones", section="pricing", kind="content",
        title="PRICING | Payment Milestones", role="pricing", layout="Detail-01", block="milestones",
        data_source="fixed milestone schedule template (e.g. 30/30/30/10) + invoice terms",
        status="ready",
        params=(
            _p("milestones", "Payment milestones table (e.g. 30/30/30/10).", required=False),
            _p("invoice_terms", "Invoice/payment terms (net-30 per milestone).", required=False),
        ),
        slide_count=(1, 1),
    ),

    # ---- Reference (optional; feature screenshots/mockups) -----------------
    SectionContract(
        key="reference_divider", section="appendix", kind="divider",
        title="{roman}. Reference", role="context", layout="Head Page", block="divider",
        data_source="—", status="structural",
        params=(_p("roman", "Auto-assigned Roman numeral.", required=False),),
        slide_count=(0, 1), optional=True,
    ),
    SectionContract(
        key="reference_screens", section="appendix", kind="content",
        title="REFERENCE | {screen_title}", role="context", layout="Detail-01", block="bullets",
        data_source="feature mockups / screenshots + record_artifact_inventory",
        status="ready",
        params=(
            _p("screens", "Reference screens, each: title + screenshot image.", required=False),
        ),
        slide_count=(0, 6), optional=True,
        notes="Highly variable count. Pure imagery; safe to omit when no mockups exist.",
    ),

    # ---- Closing (BnK brand slide, appended automatically) -----------------
    SectionContract(
        key="closing", section="closing", kind="closing",
        title="", role="context", layout="BnK", block="closing",
        data_source="template-native BnK closing layout", status="structural",
        params=(),
        slide_count=(1, 1),
        notes="Always appended via ppt_reporting._append_thank_you; never generated.",
    ),

    # =========================================================================
    # OPTIONAL EXTRAS — seen in advisory-heavy decks (Ex Umbra), not the core
    # backbone. Emit only when the corresponding business_narrative field exists.
    # =========================================================================
    SectionContract(
        key="kpis", section="appendix", kind="content",
        title="EXPECTED RESULTS | KPIs", role="kpis", layout="Detail-01", block="kpis",
        data_source="business_narrative.json.kpis + business_goals (NEW)",
        status="new_block+new_data",
        params=(
            _p("kpis", "Metric table: Module | Metric (e.g. 'Soil Moisture | MSE')."),
            _p("business_goals", "Business goals / expected outcomes bullets.", required=False),
        ),
        required_inputs=("business_narrative.kpis",),
        slide_count=(0, 1), optional=True,
    ),
    SectionContract(
        key="client_info", section="appendix", kind="content",
        title="CLIENT | Overview", role="client_info", layout="Detail-01", block="client_info",
        data_source="business_narrative.json.client_info (NEW)",
        status="new_block+new_data",
        params=(
            _p("client_info", "Key-value facts: client, platform, geography, regulatory."),
        ),
        required_inputs=("business_narrative.client_info",),
        slide_count=(0, 1), optional=True,
    ),
    SectionContract(
        key="advice_phase", section="scope", kind="content",
        title="ADVICE PHASE | Overview", role="advice", layout="Detail-01", block="bullets",
        data_source="business_narrative.json.advice_phase (NEW), engagement_mode=='advisory_first'",
        status="new_block+new_data",
        params=(
            _p("advice_scope", "Advisory/feasibility scope (what will be assessed)."),
            _p("advice_deliverable", "The advisory deliverable (e.g. Technical Advisory Report + workshop)."),
        ),
        required_inputs=("business_narrative.advice_phase",),
        slide_count=(0, 2), optional=True,
        notes="Advisory-first engagements only (Ex Umbra). Gate like has_diagram.",
    ),
)


# --- lookups & helpers -------------------------------------------------------

#: Sections whose absence should raise a completeness warning (docx §7.1 deck gate),
#: mirroring deck.REQUIRED_ROLES. A deck with none of these is not a real proposal.
REQUIRED_KEYS: frozenset[str] = frozenset({
    "cover", "exec_summary_overview", "solution_overview",
    "scope_sdlc", "delivery_effort", "delivery_master_plan", "pricing_capex",
})

#: Blocks ppt_reporting already implements (VALID_BLOCKS) + structural pseudo-blocks that
#: need no renderer. Keep in sync with ppt_reporting.VALID_BLOCKS.
IMPLEMENTED_BLOCKS: frozenset[str] = frozenset({
    "bullets", "tech_stack_table", "func_nfr", "sdlc", "delivery_effort",
    "pricing", "milestones", "team",           # ppt_reporting.VALID_BLOCKS
    "diagram", "cover", "divider", "closing",  # structural — handled without a block renderer
})

#: Blocks this registry references that ppt_reporting does NOT yet implement — the concrete
#: renderer TODO list (a contract may still need NEW *data* while reusing an existing block,
#: e.g. advice_phase uses "bullets"; such contracts are NOT counted here).
NEW_BLOCKS: frozenset[str] = frozenset(
    c.block for c in SECTION_CONTENT_CONTRACTS if c.block not in IMPLEMENTED_BLOCKS
)

_BY_KEY: dict[str, SectionContract] = {c.key: c for c in SECTION_CONTENT_CONTRACTS}


def get_contract(key: str) -> SectionContract | None:
    """Return the contract with ``key``, or None."""
    return _BY_KEY.get(key)


def contracts_for_section(section: str) -> list[SectionContract]:
    """All contracts belonging to a major ``section`` bucket, in deck order."""
    return [c for c in SECTION_CONTENT_CONTRACTS if c.section == section]


def content_contracts() -> list[SectionContract]:
    """Only the slides that carry generatable content (skip cover/divider/closing)."""
    return [c for c in SECTION_CONTENT_CONTRACTS if c.kind == "content"]


def resolve_missing(contract: SectionContract, available: set[str]) -> list[str]:
    """Required inputs of ``contract`` not satisfied by ``available``.

    ``available`` is the set of resolvable input keys for the current workspace (e.g.
    ``{"brief.objective", "wbs.effort_totals", "out.png"}``). A ``required_inputs`` entry may
    be an OR-group written ``"a|b"`` — satisfied when ANY alternative is available.

    Non-empty return => the section should be **skipped with a warning**, never rendered
    with empty params (this is the fix for the "no content" bug).
    """
    missing: list[str] = []
    for req in contract.required_inputs:
        alternatives = req.split("|")
        if not any(alt in available for alt in alternatives):
            missing.append(req)
    return missing


def plannable_contracts(
    available: set[str], *, include_optional: bool = True
) -> list[tuple[SectionContract, list[str]]]:
    """Walk the backbone and pair each contract with its unmet required inputs.

    Structural slides (cover/divider/closing) always pass. A content contract with unmet
    required inputs is returned with a non-empty ``missing`` list so the caller can skip it
    and surface a ``narrative_gap`` finding at the propose_deck_plan HITL gate.
    """
    out: list[tuple[SectionContract, list[str]]] = []
    for c in SECTION_CONTENT_CONTRACTS:
        if c.optional and not include_optional:
            continue
        missing = [] if c.kind != "content" else resolve_missing(c, available)
        out.append((c, missing))
    return out
