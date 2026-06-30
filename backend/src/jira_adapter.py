"""Real Jira Cloud adapter for the delivery export (docx §8.6, §10.3).

`delivery_export.sync_work_items(..., dry_run=False)` calls into here when the target is
Jira AND credentials are configured. With no credentials the caller falls back to the
offline deterministic simulation, so CI / local runs never touch the network.

Auth follows the Jira Cloud REST v3 convention: HTTP Basic with (email, API token).
Configuration is read from the environment (mirrors how `web_research` reads
``TAVILY_API_KEY``):

    JIRA_BASE_URL     e.g. https://acme.atlassian.net   (no trailing /rest/...)
    JIRA_EMAIL        the Atlassian account email
    JIRA_API_TOKEN    an API token (id.atlassian.com/manage-profile/security/api-tokens)
    JIRA_PROJECT_KEY  the project to create issues in, e.g. PROJ
    JIRA_EFFORT_FIELD optional — the custom field id for effort (e.g. customfield_10016);
                      when unset the synthetic effort field is dropped and the estimate is
                      folded into the description so the POST never 400s on an unknown field.

Imports only httpx + stdlib (no project modules) so it stays cycle-free and trivially
mockable in tests.
"""

from __future__ import annotations

import copy
import os
from typing import Optional

import httpx

JIRA_TIMEOUT_S = 30


def jira_credentials() -> Optional[dict]:
    """Return Jira credentials from the environment, or ``None`` if not fully configured.

    All four of base url / email / token / project key must be present; a partial config
    is treated as "no credentials" so the caller simulates instead of failing mid-push.
    """
    base = (os.getenv("JIRA_BASE_URL") or "").rstrip("/")
    email = os.getenv("JIRA_EMAIL") or ""
    token = os.getenv("JIRA_API_TOKEN") or ""
    project = os.getenv("JIRA_PROJECT_KEY") or ""
    if not (base and email and token and project):
        return None
    return {
        "base_url": base,
        "email": email,
        "token": token,
        "project_key": project,
        "effort_field": os.getenv("JIRA_EFFORT_FIELD") or "",
    }


def _prepare_fields(creds: dict, payload: dict, *, is_create: bool) -> dict:
    """Sanitise the build_payload() jira shape into fields a real instance will accept.

    - inject the project key on create,
    - rename the synthetic ``customfield_effort_days`` to the configured custom field id,
      or, if none is configured, drop it and fold the estimate into the description so an
      arbitrary Jira instance does not 400 on an unknown field.
    """
    body = copy.deepcopy(payload)
    fields = body.setdefault("fields", {})
    if is_create:
        fields["project"] = {"key": creds["project_key"]}

    effort = fields.pop("customfield_effort_days", None)
    if effort is not None:
        if creds.get("effort_field"):
            fields[creds["effort_field"]] = effort
        else:
            desc = fields.get("description") or ""
            fields["description"] = (desc + f"\n\nEstimated effort: {effort} man-days").strip()
    return body


def push_issue(creds: dict, payload: dict, *, action: str, external_id: str = "") -> str:
    """Create or update a Jira issue and return its external id (issue key).

    action="create" → POST /rest/api/3/issue, returns the new issue key (e.g. PROJ-12).
    action="update" → PUT  /rest/api/3/issue/{external_id}, returns ``external_id`` (Jira
    answers 204 No Content on a successful edit).
    Raises ``httpx.HTTPStatusError`` on a non-2xx response so the caller can surface it.
    """
    auth = (creds["email"], creds["token"])
    if action == "update" and external_id:
        body = _prepare_fields(creds, payload, is_create=False)
        resp = httpx.put(
            f"{creds['base_url']}/rest/api/3/issue/{external_id}",
            json=body, auth=auth, timeout=JIRA_TIMEOUT_S,
        )
        resp.raise_for_status()
        return external_id

    body = _prepare_fields(creds, payload, is_create=True)
    resp = httpx.post(
        f"{creds['base_url']}/rest/api/3/issue",
        json=body, auth=auth, timeout=JIRA_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()["key"]
