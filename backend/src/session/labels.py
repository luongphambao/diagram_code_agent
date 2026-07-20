"""Tool label + subagent-attribution maps for chat-facing activity logs."""

from __future__ import annotations

_TOOL_LABELS = {
    "analyze_architecture_requirements": "Analyzing architecture requirements",
    "propose_diagram_brief": "Preparing the diagram brief",
    "propose_tech_stack": "Proposing the technology stack",
    "propose_blueprint": "Designing the architecture blueprint",
    "render_diagram": "Rendering the diagram",
    "export_drawio": "Exporting the editable .drawio",
    "list_saved_diagrams": "Listing saved diagram sessions",
    "resolve_icons": "Resolving icon plan",
    "search_diagrams_nodes": "Searching built-in diagram nodes",
    "search_icons": "Searching the icon library",
    "fetch_logo": "Fetching a logo",
    "audit_diagram_code": "Auditing diagram code",
    "inspect_diagram": "Reviewing the rendered diagram",
    "submit_critique": "Recording the diagram review",
    "finalize_diagram": "Finalizing the diagram",
    "generate_pdf_report": "Generating the PDF report",
    "generate_ppt_proposal": "Presenting the PPT proposal for approval",
    "create_pptx": "Generating the PowerPoint deck",
    "send_email": "Sending the deliverables email",
    "write_todos": "Planning the steps",
    "task": "Delegating to subagent",
    "ls": "Listing files",
    "read_file": "Reading a file",
    "write_file": "Writing a file",
    "edit_file": "Editing a file",
    "glob": "Searching for files",
    "grep": "Searching file contents",
}

# Maps tool name → which subagent owns it (for activity attribution).
_TOOL_TO_SUBAGENT: dict[str, str] = {
    "search_diagrams_nodes": "icon_resolver",
    "search_icons": "icon_resolver",
    "resolve_icons": "icon_resolver",
    "fetch_logo": "icon_resolver",
    "audit_diagram_code": "drawer",
    "render_diagram": "drawer",
    "export_drawio": "drawer",
    "inspect_diagram": "critic",
    "submit_critique": "critic",
    "create_pptx": "ppt_generator",
}


def _label(tool: str) -> str:
    return _TOOL_LABELS.get(tool, f"Running {tool}")


# Human-readable names for subagent identifiers, used only in chat-facing labels/
# detail text. Internal identifiers (used for event matching/routing/tests) are
# untouched — see _tool_detail's "task" branch and chat.py's delegate label.
_SUBAGENT_DISPLAY_NAMES = {"wbs_planner": "WBS Agent"}


def _display_subagent(name: str) -> str:
    return _SUBAGENT_DISPLAY_NAMES.get(name, name)
