"""Per-kind structural-lint framework for typed diagrams (improvement plan:
typed-diagram foundation, §4/§5's Error/Warning/Info taxonomy).

This is deliberately separate from `validate_drawio.py`'s XML-level audits
(`audit_bpmn`, `audit_architecture`, ...): those inspect the RENDERED mxCell
XML for visual/layout defects. Linters registered here inspect the SOURCE
SPEC (before rendering) for domain-semantic defects a renderer can't see —
a sequence message pointing at a participant that doesn't exist, an ERD
foreign key referencing a missing table, a state no transition ever reaches.
0 LLM tokens, deterministic, same tier-1 slot the BPMN semantic-preservation
check already occupies in `_render_typed_native`/`_render_native_from_spec`.

Each new diagram kind's own module (`tools/analysis/<kind>_tools.py`, in the
kind's own phase) implements `lint_<kind>(spec) -> LintReport` and calls
`register_linter("<kind>", lint_<kind>)` at import time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

Severity = Literal["error", "warning", "info"]


@dataclass
class LintFinding:
    severity: Severity
    code: str
    message: str
    ref: str = ""  # id of the offending node/edge/message/state, if applicable


@dataclass
class LintReport:
    findings: list[LintFinding] = field(default_factory=list)

    def add(self, severity: Severity, code: str, message: str, ref: str = "") -> None:
        self.findings.append(LintFinding(severity, code, message, ref))

    def error(self, code: str, message: str, ref: str = "") -> None:
        self.add("error", code, message, ref)

    def warning(self, code: str, message: str, ref: str = "") -> None:
        self.add("warning", code, message, ref)

    def info(self, code: str, message: str, ref: str = "") -> None:
        self.add("info", code, message, ref)

    @property
    def errors(self) -> list[LintFinding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    def to_dict(self) -> dict:
        return {
            "errors": [f.__dict__ for f in self.findings if f.severity == "error"],
            "warnings": [f.__dict__ for f in self.findings if f.severity == "warning"],
            "info": [f.__dict__ for f in self.findings if f.severity == "info"],
        }


LINTERS: dict[str, Callable[[dict], LintReport]] = {}


def register_linter(kind: str, fn: Callable[[dict], LintReport]) -> None:
    """Register (or replace) the structural linter for `kind`."""
    LINTERS[kind] = fn


def lint(kind: str, spec: dict) -> LintReport:
    """Run `kind`'s registered linter over `spec`; an empty report if unregistered."""
    fn = LINTERS.get(kind)
    if fn is None:
        return LintReport()
    return fn(spec)


__all__ = ["Severity", "LintFinding", "LintReport", "LINTERS", "register_linter", "lint"]
