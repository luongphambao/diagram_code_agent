"""Reality Sync / Reverse Architecture (docx §5.2, Phase 4 flagship).

Ingests a real codebase/infra source — a repo tree, Terraform, k8s/compose YAML, an
OpenAPI spec — into a *current-state* `SolutionModel`, then diffs it against the
*desired* CSM to produce a drift report: what is designed but not built, built but not
designed, and what matches. This turns the agent from a greenfield proposal tool into a
recurring operating workflow ("does the doc match production?").

Deterministic and dependency-light: OpenAPI/JSON is parsed directly, YAML via PyYAML,
Terraform via a small regex, and Python repos via the existing `codevis.discover` file
walk (no Graphviz needed). The current-state model is written to its own
`current_state_model.json` and never mixed into the desired `solution_model.json`.

Imports only `csm` (+ optional `codevis`), so it is cycle-free.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from csm import Component, SolutionModel, SourceRef, mint_id, slug

CURRENT_STATE_MODEL_NAME = "current_state_model.json"
DRIFT_REPORT_NAME = "drift_report.json"

# Files we know how to read.
_COMPOSE_NAMES = {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
_OPENAPI_NAMES = {"openapi.json", "openapi.yaml", "openapi.yml", "swagger.json"}
_K8S_KINDS = {"Deployment", "StatefulSet", "Service", "DaemonSet", "CronJob"}
_TF_RESOURCE = re.compile(r'resource\s+"([^"]+)"\s+"([^"]+)"')


def _load_yaml(text: str):
    try:
        import yaml  # PyYAML
        return yaml.safe_load(text)
    except Exception:  # noqa: BLE001 — degrade gracefully if YAML is malformed/absent
        return None


# --- per-source ingest -------------------------------------------------------

def ingest_compose(text: str, ref: str) -> list[tuple[str, str, str]]:
    """docker-compose services → (name, kind, source_ref)."""
    data = _load_yaml(text)
    out: list[tuple[str, str, str]] = []
    if isinstance(data, dict):
        for svc in (data.get("services") or {}):
            out.append((str(svc), "component", ref))
    return out


def ingest_k8s(text: str, ref: str) -> list[tuple[str, str, str]]:
    """k8s manifests (possibly multi-doc) → workloads/services."""
    out: list[tuple[str, str, str]] = []
    try:
        import yaml
        docs = list(yaml.safe_load_all(text))
    except Exception:  # noqa: BLE001
        docs = [_load_yaml(text)]
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        kind = doc.get("kind")
        if kind in _K8S_KINDS:
            name = (doc.get("metadata") or {}).get("name") or kind.lower()
            k = "integration" if kind == "Service" else "component"
            out.append((str(name), k, ref))
    return out


def ingest_terraform(text: str, ref: str) -> list[tuple[str, str, str]]:
    """Terraform `resource "type" "name"` blocks → components."""
    out: list[tuple[str, str, str]] = []
    for rtype, rname in _TF_RESOURCE.findall(text):
        out.append((f"{rtype}.{rname}", "component", ref))
    return out


def ingest_openapi(text: str, ref: str) -> list[tuple[str, str, str]]:
    """OpenAPI/Swagger → one integration per tag (or per top-level path)."""
    data = None
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
    if data is None:
        data = _load_yaml(text)
    if not isinstance(data, dict):
        return []
    out: list[tuple[str, str, str]] = []
    tags = {t.get("name") for t in (data.get("tags") or []) if isinstance(t, dict)}
    if tags:
        for t in sorted(filter(None, tags)):
            out.append((f"api:{t}", "integration", ref))
    else:
        for path in (data.get("paths") or {}):
            top = "/" + str(path).strip("/").split("/")[0]
            out.append((f"api:{top}", "integration", ref))
    # de-dup while preserving determinism
    seen = set()
    deduped = []
    for item in out:
        if item[0] in seen:
            continue
        seen.add(item[0])
        deduped.append(item)
    return deduped


def ingest_repo(source_dir: Path) -> list[tuple[str, str, str]]:
    """Python repo → top-level packages as components (reuses codevis.discover)."""
    try:
        from codevis.pyimports import discover
        modules, _root = discover(str(source_dir))
    except Exception:  # noqa: BLE001 — codevis optional / non-python repo
        return []
    tops: dict[str, str] = {}
    for name, path in modules.items():
        top = str(name).split(".")[0]
        tops.setdefault(top, path)
    return [(top, "component", "repo") for top in sorted(tops)]


# --- assemble current-state model -------------------------------------------

def build_current_state_model(source_dir: Path) -> SolutionModel:
    """Scan ``source_dir`` for known infra/spec files + a python repo and assemble a
    deterministic current-state SolutionModel (components/integrations only)."""
    source_dir = Path(source_dir)
    found: list[tuple[str, str, str]] = []

    if source_dir.is_dir():
        for p in sorted(source_dir.rglob("*")):
            if not p.is_file():
                continue
            name = p.name.lower()
            try:
                if name in _COMPOSE_NAMES:
                    found += ingest_compose(p.read_text(encoding="utf-8", errors="ignore"), p.name)
                elif name in _OPENAPI_NAMES:
                    found += ingest_openapi(p.read_text(encoding="utf-8", errors="ignore"), p.name)
                elif p.suffix == ".tf":
                    found += ingest_terraform(p.read_text(encoding="utf-8", errors="ignore"), p.name)
                elif p.suffix in (".yaml", ".yml") and name not in _COMPOSE_NAMES:
                    found += ingest_k8s(p.read_text(encoding="utf-8", errors="ignore"), p.name)
            except OSError:
                continue
        found += ingest_repo(source_dir)

    # Mint components with stable ids; de-dup by normalized name.
    model = SolutionModel()
    seen: set[str] = set()
    for raw_name, kind, ref in found:
        key = slug(raw_name)
        if key in seen:
            continue
        seen.add(key)
        model.components.append(Component(
            id=mint_id("component", raw_name),
            provenance="deterministic",
            name=raw_name,
            kind=kind,  # type: ignore[arg-type]
            purpose="observed in current state",
            source_refs=[SourceRef(kind="document", ref=ref)],
        ))
    return model


# --- drift -------------------------------------------------------------------

def _comp_index(model: SolutionModel) -> dict[str, Component]:
    """Normalized-name → component (last wins; current/desired keyed independently)."""
    return {slug(c.name): c for c in model.components}


def drift(desired: SolutionModel, current: SolutionModel) -> dict:
    """Compare desired vs current architecture by normalized component name.

    Returns three buckets plus remediation hints:
      * in_design_not_in_reality — designed but not found in the source (build it / it is missing)
      * in_reality_not_in_design — found in the source but not designed (undocumented drift)
      * matched                  — present in both
    """
    d_idx = _comp_index(desired)
    c_idx = _comp_index(current)
    d_keys, c_keys = set(d_idx), set(c_idx)

    only_design = sorted(d_keys - c_keys)
    only_reality = sorted(c_keys - d_keys)
    matched = sorted(d_keys & c_keys)

    def _entry(comp: Component) -> dict:
        return {"id": comp.id, "name": comp.name, "kind": comp.kind}

    remediation: list[str] = []
    for k in only_design:
        remediation.append(f"DESIGN-ONLY: '{d_idx[k].name}' is in the proposal but not in the "
                           f"current state — implement it or mark it as future scope.")
    for k in only_reality:
        remediation.append(f"DRIFT: '{c_idx[k].name}' exists in the source but is not in the "
                           f"design — document it or remove it.")

    return {
        "summary": {
            "designed": len(d_keys),
            "observed": len(c_keys),
            "matched": len(matched),
            "in_design_not_in_reality": len(only_design),
            "in_reality_not_in_design": len(only_reality),
        },
        "in_design_not_in_reality": [_entry(d_idx[k]) for k in only_design],
        "in_reality_not_in_design": [_entry(c_idx[k]) for k in only_reality],
        "matched": [_entry(d_idx[k]) for k in matched],
        "remediation": remediation,
    }


def format_drift(report: dict) -> str:
    s = report["summary"]
    lines = [
        f"DRIFT REPORT — designed {s['designed']}, observed {s['observed']}, "
        f"matched {s['matched']} | design-only {s['in_design_not_in_reality']}, "
        f"reality-only {s['in_reality_not_in_design']}",
    ]
    if report["in_design_not_in_reality"]:
        names = ", ".join(e["name"] for e in report["in_design_not_in_reality"])
        lines.append(f"  Designed but NOT built: {names}")
    if report["in_reality_not_in_design"]:
        names = ", ".join(e["name"] for e in report["in_reality_not_in_design"])
        lines.append(f"  Built but NOT designed (drift): {names}")
    if not (report["in_design_not_in_reality"] or report["in_reality_not_in_design"]):
        lines.append("  No drift — design and current state agree.")
    return "\n".join(lines)


# --- orchestration -----------------------------------------------------------

def run_reality_sync(source_dir: Path, workspace: Optional[Path] = None) -> dict:
    """Build the current-state model + drift report and write both into the workspace."""
    if workspace is None:
        from backends import current_workspace
        workspace = current_workspace()
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    current = build_current_state_model(source_dir)
    (workspace / CURRENT_STATE_MODEL_NAME).write_text(current.to_json(), encoding="utf-8")

    desired_path = workspace / "solution_model.json"
    desired = SolutionModel()
    if desired_path.exists():
        try:
            desired = SolutionModel.model_validate(
                json.loads(desired_path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            desired = SolutionModel()

    report = drift(desired, current)
    (workspace / DRIFT_REPORT_NAME).write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report
