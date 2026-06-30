"""Deck eval judge (docx §4.8, §4.5 "deck" suite).

Deterministic L1/L2 scorer built directly on `deck.validate_deck`. A golden case
seeds a storyboard defect (a slide claiming a non-existent entity, a missing
narrative role, an effort number that disagrees with the WBS, or a client-facing
claim with no evidence) and asserts the matching finding dimension fires; the clean
case asserts none does. This makes the deck validator self-testing on realistic
inputs, mirroring the architecture suite.

The VLM coherence/visual judge (`render_deck_to_png` + `deck_vision_judge`) is
OPT-IN — it needs a pptx->png renderer (aspose.slides) and an API key, so it is NOT
part of `METRIC_KEYS` / the regression gate, exactly like the diagram vision judge.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def score_deck(findings: list[dict[str, Any]], golden: dict) -> dict:
    """`findings` is the list[dict] returned by deck.validate_deck."""
    dims_present = {f.get("dimension") for f in findings}
    expected = golden.get("expected_dimensions", [])

    # Recall over the dimensions the seeded case should surface.
    if expected:
        hit = sum(1 for d in expected if d in dims_present)
        finding_recall = round(hit / len(expected), 4)
    else:
        finding_recall = 1.0

    # Exact match: the validator fires exactly the expected dimensions (no more, no less).
    match = 1.0 if dims_present == set(expected) else 0.0

    return {
        "finding_recall": finding_recall,
        "match": match,
        "n_findings": len(findings),
        "dimensions": sorted(d for d in dims_present if d),
    }


def score_structure(struct_result: dict, golden: dict) -> dict:
    """Score the structural scorer output against golden expectations.

    `struct_result` is the dict from `deck.score_deck_structure`.
    Golden fields (all optional):
      * ``expected_max_score``  — structure score must be at or below this (defect cases)
      * ``expected_min_score``  — structure score must be at or above this (clean cases)
      * ``expected_issue_keywords`` — list of substrings that must appear in some issue
    """
    score = struct_result.get("score", 100.0)
    issues = struct_result.get("issues", [])
    issue_text = " | ".join(issues).lower()

    # score_ok: 1.0 when the score is within the golden bounds.
    max_s = golden.get("expected_max_score")
    min_s = golden.get("expected_min_score")
    score_ok = 1.0
    if max_s is not None and score > max_s:
        score_ok = 0.0
    if min_s is not None and score < min_s:
        score_ok = 0.0

    # keyword_recall: fraction of expected keywords found in the combined issues text.
    keywords = golden.get("expected_issue_keywords", [])
    if keywords:
        hits = sum(1 for kw in keywords if kw.lower() in issue_text)
        kw_recall = round(hits / len(keywords), 4)
    else:
        kw_recall = 1.0

    return {
        "score_ok": score_ok,
        "kw_recall": kw_recall,
        "structural_score": score,
        "structural_grade": struct_result.get("grade", "?"),
        "n_issues": len(issues),
    }


METRIC_KEYS = ["scores.finding_recall", "scores.match"]
STRUCTURE_METRIC_KEYS = ["scores.score_ok", "scores.kw_recall"]
VISUAL_AUDIT_METRIC_KEYS = ["scores.issue_recall", "scores.passed_ok"]


def score_visual_audit(audit_result: dict, golden: dict) -> dict:
    """Score a DeckVisualAuditResult dict against golden expectations.

    Golden fields (all optional):
      * ``expected_issue_types`` — list of issue_type strings that must appear
      * ``expected_passed``      — expected value of audit_result["passed"]
    """
    found_types = {i.get("issue_type") for i in audit_result.get("issues", [])}
    expected = golden.get("expected_issue_types", [])
    if expected:
        hit = sum(1 for t in expected if t in found_types)
        issue_recall = round(hit / len(expected), 4)
    else:
        issue_recall = 1.0

    expected_passed = golden.get("expected_passed", True)
    passed_ok = 1.0 if audit_result.get("passed") == expected_passed else 0.0

    return {
        "issue_recall": issue_recall,
        "passed_ok": passed_ok,
        "high_count": audit_result.get("high_count", 0),
        "medium_count": audit_result.get("medium_count", 0),
        "threshold_score": audit_result.get("threshold_score", 100),
    }


# --- opt-in vision/coherence judge (NOT in the gate) -------------------------

def render_deck_to_png(pptx_path: str | Path, out_dir: str | Path) -> list[str]:
    """Render every slide of `pptx_path` to PNG via aspose.slides (opt-in dependency).

    Mirrors DATA/analyze_slide.convert_pptx_to_images. aspose.slides is not in the
    backend venv, so this raises ImportError unless the caller's interpreter has it
    (e.g. anaconda). Used only by the opt-in vision judge, never by the CI gate.
    """
    import os

    import aspose.slides as slides  # type: ignore
    import aspose.pydrawing as drawing  # type: ignore

    out_dir = str(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    paths: list[str] = []
    with slides.Presentation(str(pptx_path)) as prs:
        for i, slide in enumerate(prs.slides):
            p = os.path.join(out_dir, f"slide_{i + 1:03d}.png")
            slide.get_image(drawing.Size(1280, 720)).save(p)
            paths.append(p)
    return paths


_VISION_RUBRIC = """\
Score each dimension 0.0-1.0 for this proposal slide deck:
1. readability            — legible text, no overflow/truncation, sane font sizes.
2. visual_hierarchy       — clear title/section structure, scannable bullets.
3. brand_consistency      — consistent BnK palette, fonts, layout across slides.
4. text_density           — slides are not walls of text; one idea per slide.
5. coherence_across_slides— the narrative flows Exec Summary -> Solution -> Scope ->
                            Delivery -> Pricing without gaps or repeats.
6. factual_alignment      — claims match the provided source context (no invented
                            components, numbers or guarantees).
7. overall                — holistic proposal quality.
Return ONLY a JSON object with those keys (floats) plus "reasoning" (string).
"""


def deck_vision_judge(png_paths: list[str], context: str, model: str) -> dict:
    """Opt-in VLM judge over the rendered slides. Returns the rubric scores as a dict.

    Kept thin and tolerant: any failure (no key, no aspose, parse error) returns an
    empty dict so a caller can treat the vision layer as best-effort. NOT gated.
    """
    import base64
    import json

    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        return {}
    try:
        client = OpenAI()
        blocks: list[dict] = [{"type": "text", "text": _VISION_RUBRIC + "\n\nCONTEXT:\n" + context}]
        for p in png_paths[:12]:
            b64 = base64.b64encode(Path(p).read_bytes()).decode("ascii")
            blocks.append({"type": "image_url",
                           "image_url": {"url": f"data:image/png;base64,{b64}"}})
        resp = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": blocks}],
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content or "{}")
    except Exception:  # noqa: BLE001 — opt-in layer, never fatal
        return {}
