"""Guards for the knowledge-graph canonical vocabularies.

Two layers. The unit tests pin the behaviour that downstream loaders rely on and
run everywhere. The corpus-coverage tests re-derive the raw strings from
``DATA/`` and fail if the alias tables have drifted behind the data — they skip
when ``DATA/`` is absent, which is the normal case in CI (it is gitignored).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

import kg_vocab as kv

DATA = Path(__file__).resolve().parents[2] / "DATA"
WBS_DIR = DATA / "SOLUTION_WBS"

requires_corpus = pytest.mark.skipif(
    not WBS_DIR.is_dir(), reason="DATA/SOLUTION_WBS is gitignored; corpus not present"
)


# ---------------------------------------------------------------- role resolution


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Testing (QA)", ("QC",)),
        ("Testing_QA", ("QC",)),
        ("QC", ("QC",)),
        ("Quality Controller (QC/Tester)", ("QC",)),
        ("Requirement Analysis (BA)", ("BA",)),
        ("Business Analyst", ("BA",)),
        ("BE Coding", ("BE",)),
        ("Back-end Developer", ("BE",)),
        ("Project Management (PM)", ("PM",)),
        ("Solution Architect", ("TL",)),
        ("Designer (UI/UX)", ("UX",)),
    ],
)
def test_role_spelling_variants_collapse(raw: str, expected: tuple[str, ...]) -> None:
    assert kv.resolve_role(raw).roles == expected


def test_composite_role_keeps_every_member() -> None:
    """A shared Excel column must not silently collapse onto one role."""
    assert kv.resolve_role("BA_Tester").roles == ("BA", "QC")
    assert kv.resolve_role("FE/Mobile").roles == ("FE", "MOBILE")
    assert kv.resolve_role("Developer (BE + AI)").roles == ("BE", "AI")


@pytest.mark.parametrize("name", ["Bao", "Tien", "Dat Nguyen", "Thu Tran", "Bao & Tien"])
def test_personal_names_are_not_roles(name: str) -> None:
    """People in role columns are PII and must never become graph nodes."""
    res = kv.resolve_role(name)
    assert res.roles == ()
    assert res.reason == "person"


def test_structural_json_keys_are_flagged_not_guessed() -> None:
    assert kv.resolve_role("master_data_rates").reason == "structural"
    assert kv.resolve_role("rate_card").reason == "structural"


def test_unknown_role_reports_unknown_rather_than_guessing() -> None:
    res = kv.resolve_role("Chief Vibes Officer")
    assert res.roles == ()
    assert res.reason == "unknown"
    assert res.source == "Chief Vibes Officer"


def test_accent_folding_makes_stripped_and_accented_spellings_match() -> None:
    assert kv.resolve_role("Kỹ thuật viên").reason == kv.resolve_role("Ky thuat vien").reason


# ------------------------------------------------------------------- md fields


def test_partner_estimate_is_not_a_bnk_role() -> None:
    """oi_md is Oi's parallel estimate; folding it into role effort inflates
    every benchmark it touches by ~1046 MD across the corpus."""
    field = kv.classify_md_field("oi_md")
    assert field is not None
    assert field.estimator == "partner"
    assert field.roles == ()


def test_rollup_fields_are_separated_from_role_columns() -> None:
    """total_md sits on parents and leaves alike — summing it with the per-role
    columns double counts."""
    assert "total_md" in kv.ROLLUP_FIELDS
    for name in kv.ROLLUP_FIELDS:
        assert kv.MD_FIELDS[name].roles == ()


def test_casing_variants_collapse() -> None:
    for a, b in [("BA_md", "ba_md"), ("Testing_MD", "testing_md"), ("BE_Coding_MD", "be_coding_md")]:
        assert kv.classify_md_field(a) == kv.classify_md_field(b)


def test_rate_column_is_not_effort() -> None:
    field = kv.classify_md_field("rate_per_md")
    assert field is not None and field.kind == "not_effort"


def test_unallocated_effort_is_kept_not_dropped() -> None:
    """coding_md carries 3514 MD with no role in its name. It is still effort."""
    field = kv.classify_md_field("coding_md")
    assert field is not None
    assert field.kind == "unallocated"
    assert field.roles == ()


def test_every_md_field_role_is_in_the_canonical_set() -> None:
    for name, field in kv.MD_FIELDS.items():
        for role in field.roles:
            assert role in kv.ROLES, f"{name} maps to unknown role {role}"


# ----------------------------------------------------------- phases vs modules


def test_delivery_phases_resolve_and_feature_modules_do_not() -> None:
    assert kv.resolve_phase("TESTING & DEPLOYMENT SUPPORT") == ("TESTING", "DEPLOYMENT")
    assert kv.resolve_phase("SET UP & INSTALLATION") == ("SETUP",)
    # project-local feature groups are a different node type, so: no match
    assert kv.resolve_phase("MODULE B - BOOKING ENGINE") == ()
    assert kv.resolve_phase("Camera Registration") == ()


def test_roman_module_codes_are_recognised_as_structural() -> None:
    for code in ("I", "II.A", "II.A.3", "III.B"):
        assert kv.is_structural_module_code(code)
    assert not kv.is_structural_module_code("QHSE-1")
    assert not kv.is_structural_module_code("DASH-01")


# ------------------------------------------------------------------ text hygiene


def test_mojibake_endash_is_repaired() -> None:
    assert kv.clean_text("MODULE A � FRONTEND") == "MODULE A - FRONTEND"
    assert kv.clean_text("II � SYSTEM DEVELOPMENT") == "II - SYSTEM DEVELOPMENT"


def test_powerpoint_vertical_tab_becomes_space() -> None:
    assert kv.clean_text("Giai phapThang 5") == "Giai phap Thang 5"


def test_methodologies_are_not_technologies() -> None:
    for word in ("Agile", "Scrum", "CI/CD Pipeline", "UAT environment", "Cong nghe"):
        assert not kv.is_technology(word), word
    for word in ("PostgreSQL", "UiPath", "Flutter", "Odoo"):
        assert kv.is_technology(word), word


# -------------------------------------------------------------- corpus coverage


def _iter_wbs_payloads():
    for path in sorted(WBS_DIR.glob("*.json")):
        if path.name == "_tmp_data.json":  # a pre-aggregated dashboard feed
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            yield path.name, payload


def _walk(node, hits: list) -> None:
    if isinstance(node, dict):
        hits.append(node)
        for value in node.values():
            _walk(value, hits)
    elif isinstance(node, list):
        for value in node:
            _walk(value, hits)


#: Columns whose role genuinely cannot be recovered from the name. Effort under
#: these is real and must still be loaded, but it cannot be attributed — so the
#: set is pinned. A new entry appearing here is a prompt to look at the source
#: sheet, not something to wave through.
KNOWN_UNALLOCATED = {"coding_md", "dev_md", "effort_md"}


def _corpus_md_columns() -> Counter[str]:
    counts: Counter[str] = Counter()
    for _name, payload in _iter_wbs_payloads():
        nodes: list = []
        _walk(payload, nodes)
        for node in nodes:
            for key in node:
                low = key.lower()
                if low.endswith("_md") or low == "md":
                    counts[key] += 1
    return counts


@requires_corpus
def test_every_md_field_in_the_corpus_is_classified() -> None:
    """An unclassified column is effort that vanishes from the graph."""
    counts = _corpus_md_columns()
    assert counts, "corpus present but no man-day columns found — walker is broken"
    unclassified = sorted({k for k in counts if kv.classify_md_field(k) is None})
    assert not unclassified, f"unclassified man-day columns: {unclassified}"


@requires_corpus
def test_unattributable_columns_stay_within_the_known_set() -> None:
    """Catches a new source spelling that the token rules cannot read a role from
    — the case where effort silently loses its owner."""
    counts = _corpus_md_columns()
    unallocated = {
        k.lower() for k in counts if (f := kv.classify_md_field(k)) is not None and f.kind == "unallocated"
    }
    assert unallocated <= KNOWN_UNALLOCATED, (
        f"new unattributable man-day columns: {sorted(unallocated - KNOWN_UNALLOCATED)}"
    )


@requires_corpus
def test_most_corpus_effort_resolves_to_a_role() -> None:
    """A blunt regression bar on the whole pipeline: if a refactor breaks role
    attribution, the ratio drops here before anything reaches the graph."""
    counts = _corpus_md_columns()
    classified = [(k, c, kv.classify_md_field(k)) for k, c in counts.items()]
    with_role = sum(c for _k, c, f in classified if f is not None and f.roles)
    total = sum(counts.values())
    assert with_role / total >= 0.60, f"role-attributed columns {with_role}/{total}"


@requires_corpus
def test_role_alias_coverage_stays_high() -> None:
    """Guards against the alias table rotting as new WBS files land. The tail is
    dominated by one-off free-text notes, so the bar is coverage-weighted rather
    than exhaustive."""
    counts: Counter[str] = Counter()
    for _name, payload in _iter_wbs_payloads():
        nodes: list = []
        _walk(payload, nodes)
        for node in nodes:
            breakdown = node.get("role_breakdown") or node.get("effort_by_role")
            if isinstance(breakdown, dict):
                counts.update(k for k in breakdown if isinstance(k, str))

    assert counts, "corpus present but no role strings found — walker is broken"
    resolved = sum(c for label, c in counts.items() if kv.resolve_role(label).reason != "unknown")
    coverage = resolved / sum(counts.values())
    unknown = sorted({label for label in counts if kv.resolve_role(label).reason == "unknown"})
    assert coverage >= 0.95, f"role coverage {coverage:.1%} < 95%; unmapped: {unknown}"
