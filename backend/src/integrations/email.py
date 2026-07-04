"""Composio-based Gmail tool for emailing workspace deliverables (PDF/PPTX/XLSX/...)."""

from __future__ import annotations

import hashlib
import mimetypes
import os
from datetime import datetime
from pathlib import Path

import httpx
from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from backends import WorkspaceFile
from context import SessionContext

# Known deliverables auto-attached when the caller doesn't specify `attachments`.
# Any other workspace file can still be attached by naming it in `attachments`
# (mimetype is guessed).
_KNOWN_DELIVERABLES: dict[str, str] = {
    "out.pdf": "PDF Report",
    "out.pptx": "Slide Deck (PPTX)",
    "wbs_filled.xlsx": "WBS (Excel)",
    "out.drawio": "Editable Diagram (draw.io)",
    "out.png": "Architecture Diagram (PNG)",
}

# Branding is configurable — the template is generic, not hardcoded to one team.
_EMAIL_BRAND = os.environ.get("EMAIL_BRAND_NAME", "BNK Solution")
_EMAIL_SENDER_LINE = os.environ.get("EMAIL_SENDER_LINE", "luongphambao1901@gmail.com")


_EMAIL_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>{project_name} — Deliverables</title>
</head>
<body style="margin:0;padding:0;background:#f0f4f8;font-family:'Segoe UI',Arial,sans-serif;">

  <!-- Header bar -->
  <table width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);">
    <tr>
      <td style="padding:20px 40px;">
        <span style="color:#ffffff;font-size:20px;font-weight:700;letter-spacing:1px;">
          BNK Solution
        </span>
      </td>
      <td align="right" style="padding:20px 40px;">
        <span style="color:#93c5fd;font-size:13px;text-transform:uppercase;letter-spacing:2px;">
          Project Deliverables
        </span>
      </td>
    </tr>
  </table>

  <!-- Hero band -->
  <table width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background:#1e3a5f;">
    <tr>
      <td align="center" style="padding:36px 40px 28px;">
        <h1 style="color:#ffffff;margin:0;font-size:28px;font-weight:700;line-height:1.3;">
          {project_name}
        </h1>
        <p style="color:#93c5fd;margin:10px 0 0;font-size:15px;">{subtitle}</p>
      </td>
    </tr>
  </table>

  <!-- Body card -->
  <table width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background:#f0f4f8;">
    <tr>
      <td align="center" style="padding:32px 16px;">
        <table width="600" cellpadding="0" cellspacing="0" border="0"
               style="background:#ffffff;border-radius:8px;
                      box-shadow:0 2px 12px rgba(0,0,0,.08);max-width:600px;">
          <tr>
            <td style="padding:36px 40px;">

              <p style="color:#1e293b;font-size:16px;line-height:1.6;margin:0 0 16px;">
                Dear {recipient_name},
              </p>

              <p style="color:#334155;font-size:15px;line-height:1.7;margin:0 0 24px;">
                Please find attached the requested deliverable(s) for
                <strong>{project_name}</strong>.
              </p>

              <!-- Attachment callout(s) -->
              {attachment_callouts_html}

              <p style="color:#64748b;font-size:14px;line-height:1.6;margin:24px 0 28px;">
                If you have any questions, please reply to this email.
              </p>

              <p style="color:#334155;font-size:15px;margin:0;">
                Best regards,<br>
                <strong>BNK Solution Team</strong><br>
                <span style="color:#64748b;font-size:13px;">
                  luongphambao1901@gmail.com
                </span>
              </p>

            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>

  <!-- Footer -->
  <table width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background:#1e293b;">
    <tr>
      <td align="center" style="padding:20px;color:#94a3b8;font-size:12px;
                                 line-height:1.6;">
        &copy; {year} BNK Solution. All rights reserved.<br>
        This email and its attachments are confidential and intended solely for
        the named recipient(s).
      </td>
    </tr>
  </table>

</body>
</html>"""


def _upload_file_to_composio(client, file_bytes: bytes, filename: str, mimetype: str) -> str:
    """Upload file bytes to Composio file storage; return the S3 key."""
    md5 = hashlib.md5(file_bytes).hexdigest()
    resp = client.client.files.create_presigned_url(
        filename=filename,
        md5=md5,
        mimetype=mimetype,
        tool_slug="GMAIL_SEND_EMAIL",
        toolkit_slug="GMAIL",
    )
    upload_resp = httpx.put(
        resp.new_presigned_url,
        content=file_bytes,
        headers={"Content-Type": mimetype},
        timeout=60,
    )
    upload_resp.raise_for_status()
    return resp.key


_ATTACHMENT_CALLOUT_TEMPLATE = """\
              <table cellpadding="0" cellspacing="0" border="0"
                     style="background:#eff6ff;border-left:4px solid #2563eb;
                            border-radius:4px;margin:0 0 12px;width:100%;">
                <tr>
                  <td style="padding:14px 18px;">
                    <span style="color:#1d4ed8;font-size:14px;font-weight:600;">
                      &#128206; {filename}
                    </span>
                    <span style="color:#64748b;font-size:13px;">
                      — {label}
                    </span>
                  </td>
                </tr>
              </table>"""


class SendEmailConfig(BaseModel):
    recipient_email: str
    subject: str
    project_name: str
    subtitle: str = ""
    recipient_name: str = "Team"
    attachments: list[str] = Field(
        default_factory=list,
        description=(
            "Workspace filenames to attach, e.g. [\"out.pptx\"] to send only the "
            "slide deck, or [\"out.pdf\", \"wbs_filled.xlsx\"] for a specific "
            "combination. Leave empty to auto-attach whatever known deliverables "
            f"exist in the workspace ({', '.join(_KNOWN_DELIVERABLES)})."
        ),
    )


@tool(args_schema=SendEmailConfig)
def send_email(
    recipient_email: str,
    subject: str,
    project_name: str,
    runtime: ToolRuntime[SessionContext] = None,
    subtitle: str = "",
    recipient_name: str = "Team",
    attachments: list[str] | None = None,
) -> str:
    """Email workspace deliverables (PDF report, PPTX slide deck, WBS Excel, ...) via Gmail.

    With no `attachments` given, auto-attaches whichever known deliverables
    exist in the workspace (out.pdf, out.pptx, wbs_filled.xlsx) — send just
    the PDF, just the slide deck, just the WBS, or any combination, whatever
    was actually generated. Pass `attachments` (workspace filenames) to send
    a specific file or set of files instead, e.g. attachments=["out.pptx"].

    Uploads each file to Composio file storage, then delivers them as email
    attachments with a professional HTML template branded for BNK Solution.

    Requires a Composio API key and a connected Gmail account (run
    `composio add gmail` once to authorise the sending account).
    Call this only after the relevant generator tool(s) completed
    (generate_pdf_report / generate_ppt_proposal / export_wbs_excel).
    This tool PAUSES for user approval before sending.
    """
    ctx = runtime.context if runtime is not None else SessionContext()
    recipient_email = recipient_email or ctx.user_email
    if not recipient_email:
        return "ERROR: no recipient_email provided and no session user_email available."

    requested = [name.strip() for name in (attachments or []) if name.strip()]
    candidate_names = requested or list(_KNOWN_DELIVERABLES)

    files_to_attach: list[tuple[str, str, bytes]] = []
    missing: list[str] = []
    for name in candidate_names:
        fpath = Path(WorkspaceFile(name))
        if not fpath.exists():
            missing.append(name)
            continue
        mimetype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        files_to_attach.append((name, mimetype, fpath.read_bytes()))

    if requested and missing:
        return f"ERROR: requested attachment(s) not found in workspace: {', '.join(missing)}."
    if not files_to_attach:
        return (
            "ERROR: no deliverables found in workspace to attach. Generate a PDF "
            "report (generate_pdf_report), slide deck (generate_ppt_proposal), or "
            "WBS Excel (export_wbs_excel) first."
        )

    try:
        import composio  # type: ignore[import]
    except ImportError:
        return (
            "ERROR: composio package is not installed. "
            "Run: pip install composio-langchain"
        )

    api_key = ctx.composio_api_key or os.environ.get("COMPOSIO_API_KEY", "")
    if not api_key:
        return "ERROR: no Composio API key in session context or COMPOSIO_API_KEY env."
    gmail_account_id = ctx.gmail_account_id or os.environ.get("GMAIL_CONNECTED_ACCOUNT_ID", "")
    if not gmail_account_id:
        return "ERROR: no Gmail connected account id in session context or GMAIL_CONNECTED_ACCOUNT_ID env."

    html_body = _EMAIL_HTML_TEMPLATE.format(
        project_name=project_name,
        subtitle=subtitle or "",
        recipient_name=recipient_name or "Team",
        year=datetime.now().year,
        attachment_callouts_html="\n".join(
            _ATTACHMENT_CALLOUT_TEMPLATE.format(
                filename=name, label=_KNOWN_DELIVERABLES.get(name, "Attachment")
            )
            for name, _, _ in files_to_attach
        ),
    )

    final_subject = subject or f"Deliverables — {project_name}"

    try:
        client = composio.Composio(api_key=api_key)
    except Exception as exc:
        return (
            f"ERROR: Composio client initialisation failed: {exc}. "
            "Check that COMPOSIO_API_KEY is valid."
        )

    attachments_payload = []
    for filename, mimetype, file_bytes in files_to_attach:
        try:
            s3_key = _upload_file_to_composio(client, file_bytes, filename, mimetype)
        except Exception as exc:
            return (
                f"ERROR: Failed to upload {filename} to Composio storage: {exc}. "
                "Check your network connection and COMPOSIO_API_KEY."
            )
        attachments_payload.append({
            "name": filename,
            "mimetype": mimetype,
            "s3key": s3_key,
        })

    try:
        result = client.tools.execute(
            "GMAIL_SEND_EMAIL",
            arguments={
                "recipient_email": recipient_email,
                "subject": final_subject,
                "body": html_body,
                "is_html": True,
                "attachment": attachments_payload,
            },
            connected_account_id=gmail_account_id,
            version="20260612_00",
        )
    except Exception as exc:
        return (
            f"ERROR: Failed to send email via Composio: {exc}. "
            "Check that Gmail is connected: run `composio add gmail`"
        )

    if hasattr(result, "error") and result.error:
        return f"ERROR: Composio returned an error: {result.error}"

    attached_names = ", ".join(f"{name} ({len(data):,} bytes)" for name, _, data in files_to_attach)
    return (
        f"Email sent successfully to {recipient_email}. "
        f"Subject: \"{final_subject}\". "
        f"Attached: {attached_names}."
    )
