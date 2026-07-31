"""Budget tracking, stage marker management, and helper I/O functions."""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path

from backends import OUTPUTS_DIR, current_workspace
from domain.reporting.reporting import REPORT_EVIDENCE_NAME
from .constants import (
    _ARCH_ANALYSIS_FILE,
    _BRIEF_FILE,
    _BLUEPRINT_FILE,
    _CRITIQUE_FILE,
    _ICON_PLAN_FILE,
    _ICON_SEARCH_BUDGET_FILE,
    _NODE_SEARCH_BUDGET_FILE,
    _OUT_NAMES,
    _PRETTYGRAPH_PKG_DIR,
    _QUALITY_HISTORY_FILE,
    _RENDER_COUNT_FILE,
    _RENDER_SPEC_FILE,
    _REVISION_COUNT_FILE,
    _SESSION_ARTIFACTS,
    _TECHSTACK_FILE,
    _TOOL_SUMMARY_FILE,
    _WEB_SEARCH_BUDGET_FILE,
    RENDER_HARD_CAP,
    RENDER_SOFT_CAP,
)


def _read_json_file(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _write_json_file(path: Path, value) -> None:
    current_workspace().mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _bump_tool_summary(tool_name: str, **extra) -> None:
    summary = _read_json_file(_TOOL_SUMMARY_FILE, {"tool_counts": {}})
    counts = summary.setdefault("tool_counts", {})
    counts[tool_name] = int(counts.get(tool_name, 0)) + 1
    for key, value in extra.items():
        if key.endswith("_hits"):
            summary[key] = int(summary.get(key, 0)) + int(value)
        else:
            summary[key] = value
    _write_json_file(_TOOL_SUMMARY_FILE, summary)


def _render_count() -> int:
    try:
        return int(json.loads(_RENDER_COUNT_FILE.read_text(encoding="utf-8"))["count"])
    except Exception:  # noqa: BLE001
        return 0


def _bump_render_count() -> int:
    n = _render_count() + 1
    _RENDER_COUNT_FILE.write_text(json.dumps({"count": n}), encoding="utf-8")
    _bump_tool_summary("render_diagram", render_attempts=n)
    return n


def _reset_round_budgets() -> None:
    for f in (_RENDER_COUNT_FILE, _ICON_SEARCH_BUDGET_FILE, _NODE_SEARCH_BUDGET_FILE):
        if f.exists():
            f.unlink()


def reset_render_count() -> None:
    """New design / new revision round -> fresh render budget."""
    _reset_round_budgets()


def _reset_revision_count() -> None:
    if _REVISION_COUNT_FILE.exists():
        _REVISION_COUNT_FILE.unlink()


# --------------------------------------------------------------------------- #
# Native-drawio engineer-loop counters (edit_drawio / inspect_render_quality /
# export_drawio_native / upgrade_drawio). Moved here from rendering_tools.py so
# every file-backed budget counter lives in one place (see AGENTS.md: "Bộ đếm
# nằm ở file JSON trong workspace ... qua tools/stage_markers.py"), and so
# DrawerReviseGateMiddleware (agent/middleware/drawer_gate.py) can reset them
# without importing the (heavy) rendering_tools module.
#
# Reset points, by design:
#   - a fresh export (_render_native_from_spec) resets ONLY the edit/inspect
#     counters (see _reset_drawio_edit_rounds) -- geometry changed, so old edit
#     history no longer applies.
#   - the export-count itself (.native_export_rounds) is reset ONLY when
#     DrawerReviseGateMiddleware lets a genuine post-finalize_diagram revision
#     dispatch through, and by clear_stage_markers() on a brand-new run. This
#     is what makes "never re-export hoping for a different geometry"
#     (prompts/drawer_agent.py) a code-enforced budget instead of prose: a
#     drawer that hits EDIT/ENGINEER BUDGET EXHAUSTED cannot just call
#     export_drawio_native() again to get a fresh one within the same round.
# --------------------------------------------------------------------------- #

_EDIT_ROUNDS_FILE = ".drawio_edit_rounds"
_ENGINEER_ROUNDS_FILE = ".engineer_rounds"
_NATIVE_EXPORT_ROUNDS_FILE = ".native_export_rounds"


def _reset_drawio_edit_rounds() -> None:
    """Called after a fresh export — old edit/inspect history no longer applies
    to the new geometry. Does NOT touch .native_export_rounds (see module note)."""
    for name in (_EDIT_ROUNDS_FILE, _ENGINEER_ROUNDS_FILE):
        p = current_workspace() / name
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass


def _reset_native_export_rounds() -> None:
    """Called only when a genuine post-rejection revision round is granted
    (DrawerReviseGateMiddleware) or on a brand-new run (clear_stage_markers)."""
    p = current_workspace() / _NATIVE_EXPORT_ROUNDS_FILE
    if p.exists():
        try:
            p.unlink()
        except OSError:
            pass


def _bump_counter_file(name: str) -> int:
    p = current_workspace() / name
    n = 0
    if p.exists():
        try:
            n = int(p.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            n = 0
    n += 1
    p.write_text(str(n), encoding="utf-8")
    return n


def _read_counter_file(name: str) -> int:
    p = current_workspace() / name
    try:
        return int(p.read_text(encoding="utf-8").strip() or 0) if p.exists() else 0
    except (OSError, ValueError):
        return 0


def _bump_drawio_edit_rounds() -> int:
    return _bump_counter_file(_EDIT_ROUNDS_FILE)


def _drawio_edit_rounds() -> int:
    return _read_counter_file(_EDIT_ROUNDS_FILE)


def _bump_engineer_rounds() -> int:
    return _bump_counter_file(_ENGINEER_ROUNDS_FILE)


def _bump_native_export_rounds() -> int:
    return _bump_counter_file(_NATIVE_EXPORT_ROUNDS_FILE)


def _native_export_rounds() -> int:
    return _read_counter_file(_NATIVE_EXPORT_ROUNDS_FILE)


def append_quality_history(step: str, scorecard: dict, *, reverted: bool = False) -> list[dict]:
    """Append one {step_no, step, total, pass, breakdown, reverted} entry and
    return the full history so far. `scorecard` is whatever production_scorecard()
    returned. Pass reverted=True for a batch edit_drawio rejected (see
    tools/rendering_tools.py::edit_drawio) — it still lands in the trail so the
    next inspect_render_quality call can say "that direction already failed"
    instead of the drawer silently retrying the same fix.

    This is the only thing that lets the drawer/critic see "did the last edit
    help or hurt" — KeepLatestImagesEdit (agent/middleware/context_edits.py)
    strips every rendered image except the most recent, so a visual before/after
    comparison is structurally impossible; a numeric delta is the substitute.
    Does not use datetime.now() (would break Workflow-style resume determinism
    elsewhere in this codebase) — a monotonic step_no is enough to order entries.
    """
    history = _read_json_file(_QUALITY_HISTORY_FILE, [])
    if not isinstance(history, list):
        history = []
    entry = {
        "step_no": len(history) + 1,
        "step": step,
        "total": scorecard.get("total"),
        "pass": scorecard.get("pass"),
        "breakdown": scorecard.get("breakdown"),
        "reverted": reverted,
    }
    history.append(entry)
    _write_json_file(_QUALITY_HISTORY_FILE, history)
    return history


def quality_history() -> list[dict]:
    history = _read_json_file(_QUALITY_HISTORY_FILE, [])
    return history if isinstance(history, list) else []


def clear_stage_markers(*, preserve_wbs: bool = False, preserve_brd: bool = False) -> None:
    """Reset the staged-flow markers at the start of a fresh run.

    These are the per-thread JSON markers and stores (resolved against the current
    workspace); the shared binary render artifacts (out.png/out.drawio/…) are cleaned
    separately by the render pipeline.
    """
    ws = current_workspace()
    files = [
        _ARCH_ANALYSIS_FILE,
        _BRIEF_FILE,
        _TECHSTACK_FILE,
        _BLUEPRINT_FILE,
        _CRITIQUE_FILE,
        _REVISION_COUNT_FILE,
        _TOOL_SUMMARY_FILE,
        _ICON_SEARCH_BUDGET_FILE,
        _NODE_SEARCH_BUDGET_FILE,
        _RENDER_SPEC_FILE,
        _ICON_PLAN_FILE,
        _WEB_SEARCH_BUDGET_FILE,
        ws / REPORT_EVIDENCE_NAME,
        ws / "solution_model.json",
        ws / "trace_links.json",
        ws / "evidence_log.json",
        ws / "pending_gate.json",
        ws / "tech_stack_draft.json",
        ws / "blueprint_draft.json",
        ws / "deck_plan.json",
        ws / "deck_qa_result.json",
        ws / "quality_snapshot.json",
        ws / "compliance_pack.json",
        ws / "delivery_export_preview.json",
        ws / "current_state_model.json",
        ws / "drift_report.json",
        ws / "quality_history.json",
        ws / "artifact_manifest.json",
    ]
    if not preserve_wbs:
        files.extend(
            [
                ws / "wbs_skeleton.json",
                ws / "wbs.json",
                ws / "wbs_filled.xlsx",
            ]
        )
    if not preserve_brd:
        files.extend(
            [
                ws / "template_map.json",
                ws / "brd_outline_draft.json",
                ws / "brd_outline.json",
                ws / "brd_validation.json",
                ws / "out.brd.docx",
            ]
        )
        for stale_dir in (ws / "brd_sections", ws / "brd_revisions"):
            if stale_dir.exists():
                shutil.rmtree(stale_dir, ignore_errors=True)
    for f in files:
        if f.exists():
            f.unlink()
    _reset_round_budgets()
    _reset_drawio_edit_rounds()
    _reset_native_export_rounds()


def _stage_helpers() -> None:
    current_workspace().mkdir(parents=True, exist_ok=True)
    pg_dst = current_workspace() / "prettygraph"
    pg_dst.mkdir(exist_ok=True)
    for src_file in _PRETTYGRAPH_PKG_DIR.glob("*.py"):
        dst_file = pg_dst / src_file.name
        content = src_file.read_text(encoding="utf-8")
        if not dst_file.exists() or dst_file.read_text(encoding="utf-8") != content:
            dst_file.write_text(content, encoding="utf-8")


def _layout_audit() -> str:
    """Best-effort layout audit for the last render (advisory; "" if unavailable)."""
    drawio = current_workspace() / "out.drawio"
    if drawio.exists():
        try:
            from domain.validation.validate_drawio import validate_file, production_scorecard

            stats = _read_json_file(current_workspace() / "out.native_stats.json", {})
            report = validate_file(str(drawio), stats=stats)
            scorecard = production_scorecard(report, stats)
            metrics = report.get("layout_metrics") or {}
            arrow = metrics.get("arrow_clarity") or {}
            bd = scorecard.get("breakdown") or {}
            lines = [
                f"Production scorecard: {scorecard.get('total')}/100 "
                f"({'PASS' if scorecard.get('pass') else 'below gate'})",
                f"Connector readability: {bd.get('connector_readability')}/15",
                "Arrow clarity: "
                f"{arrow.get('arrow_clarity_score')}/100, "
                f"visible_edges={arrow.get('visible_edge_count')}, "
                f"bundled_edges={arrow.get('bundled_edge_count')}, "
                f"crossings={arrow.get('edge_crossings')}, "
                f"crossings_per_edge={arrow.get('crossings_per_edge')}, "
                f"long_edges={arrow.get('long_edges')}, "
                f"long_edge_ratio={arrow.get('long_edge_ratio')}, "
                f"label_overlaps={arrow.get('edge_label_overlaps')}",
            ]
            if report.get("advice"):
                lines.append("Top layout advice: " + "; ".join(report["advice"][:3]))
            if report.get("polish"):
                lines.append("Polish findings: " + "; ".join(report["polish"][:3]))
            return "\n  ".join(lines)
        except Exception:  # noqa: BLE001 — audit is advisory, never fail over it
            pass
    dot = current_workspace() / "out.dot"
    png = current_workspace() / "out.png"
    if not dot.exists() or not png.exists():
        return ""
    try:
        from prettygraph import audit_layout

        verdict = audit_layout(str(dot), str(png))
    except Exception:  # noqa: BLE001 — audit is advisory, never fail over it
        return ""

    # Append panel-fill check from the last slide render metadata.
    slide_json = current_workspace() / "out.slide.json"
    if slide_json.exists():
        try:
            slide_data = json.loads(slide_json.read_text(encoding="utf-8"))
            fill_pct = slide_data.get("layout", {}).get("panel_fill_pct")
            if fill_pct is not None and fill_pct < 0.55:
                verdict += (
                    f"\n  PANEL FILL: {fill_pct:.0%} — body leaves large white margins "
                    "inside the slide panel. For flow-mode (LR landscape) this is normal "
                    "when node count is low; options: add more nodes/edges to the flow, "
                    "consolidate sparse zones, raise grid cols for large clusters "
                    "(g.grid_cluster(region, cols=3)), or for poster mode use direction='TB' "
                    "so planes sit side by side. Target ≥55% for flow diagrams, ≥65% for "
                    "poster/wall-grid mode."
                )
        except Exception:  # noqa: BLE001
            pass

    return verdict


def _archive_session(*, extra_meta: dict | None = None) -> Path | None:
    """Copy final diagram artifacts into a timestamped session folder under OUTPUTS_DIR.

    Called from finalize_diagram() on every user-approved diagram (§4.3 — the
    ONLY diagrams worth learning from) and, for the deprecated Graphviz path,
    from export_drawio() on success — so every completed diagram is preserved
    for reuse without overwriting the active workspace.

    extra_meta is merged into meta.json (e.g. scorecard/provider/style_preset
    from finalize_diagram, so the archive is self-describing without having
    to re-open out.native_stats.json).

    Returns the archive folder path, or None if nothing was saved.
    """
    png = current_workspace() / "out.png"
    drawio = current_workspace() / "out.drawio"
    if not png.exists() and not drawio.exists():
        return None

    # Derive a human-readable title from the blueprint or brief.
    title = ""
    for meta_file in (_BLUEPRINT_FILE, _BRIEF_FILE):
        if meta_file.exists():
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                title = data.get("diagram_title") or data.get("title") or data.get("topic") or ""
                if title:
                    break
            except Exception:  # noqa: BLE001
                pass

    # Sanitize title for use in a folder name (max 60 chars).
    safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:60]
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"{timestamp}_{safe_title}" if safe_title else timestamp

    dest = OUTPUTS_DIR / folder_name
    dest.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for name in _SESSION_ARTIFACTS:
        src = current_workspace() / name
        if src.exists():
            shutil.copy2(str(src), str(dest / name))
            copied.append(name)

    # Write a lightweight index so the folder is self-describing.
    meta = {
        "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
        "title": title or folder_name,
        "files": copied,
        **(extra_meta or {}),
    }
    (dest / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return dest


def _web_search_state() -> dict:
    return _read_json_file(_WEB_SEARCH_BUDGET_FILE, {"calls": 0, "queries": []})


def _save_web_search_state(state: dict) -> None:
    _write_json_file(_WEB_SEARCH_BUDGET_FILE, state)


def _icon_search_state() -> dict:
    from .constants import ICON_SEARCH_DEFAULT_TOTAL_CAP

    return _read_json_file(
        _ICON_SEARCH_BUDGET_FILE,
        {"counts": {}, "cache": {}, "total_calls": 0, "planned_icons": 0},
    )


def _save_icon_search_state(state: dict) -> None:
    _write_json_file(_ICON_SEARCH_BUDGET_FILE, state)


def _node_search_state() -> dict:
    return _read_json_file(_NODE_SEARCH_BUDGET_FILE, {"single_calls": 0, "batch_calls": 0})


def _save_node_search_state(state: dict) -> None:
    _write_json_file(_NODE_SEARCH_BUDGET_FILE, state)


def _inspection_image_b64(png_path: Path) -> tuple[str, str]:
    """Return (base64, mime) of a context-friendly copy of the rendered PNG.

    Downscale to <= INSPECT_MAX_WIDTH and JPEG-compress so the image that lands in
    the conversation is small. Falls back to the raw PNG if Pillow is unavailable.
    """
    import base64
    import io

    from .constants import INSPECT_MAX_WIDTH

    try:
        from PIL import Image

        im = Image.open(png_path).convert("RGB")
        if im.width > INSPECT_MAX_WIDTH:
            h = round(im.height * INSPECT_MAX_WIDTH / im.width)
            im = im.resize((INSPECT_MAX_WIDTH, h), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=65, optimize=True)
        return base64.standard_b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"
    except Exception:  # noqa: BLE001 — never fail a render over the preview copy
        import logging

        logging.getLogger(__name__).warning(
            "_inspection_image_b64: Pillow downscale failed — sending FULL-SIZE "
            "raw PNG (%s bytes); large payloads can trigger provider vision 400s",
            png_path.stat().st_size if png_path.exists() else "?",
            exc_info=True,
        )
        return base64.standard_b64encode(png_path.read_bytes()).decode("ascii"), "image/png"
