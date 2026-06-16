"""Composio-based Gmail tool for sending architecture report PDFs."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path

import httpx
from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from pydantic import BaseModel

from .backends import WORKSPACE
from .context import SessionContext


_EMAIL_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Architecture Report — {project_name}</title>
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
          Architecture Report
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
                Please find attached the <strong>Architecture Report</strong> for
                <strong>{project_name}</strong>. This document captures the proposed
                solution architecture, technology stack, Well-Architected review, and
                the final system diagram approved during our design session.
              </p>

              <!-- Attachment callout -->
              <table cellpadding="0" cellspacing="0" border="0"
                     style="background:#eff6ff;border-left:4px solid #2563eb;
                            border-radius:4px;margin:0 0 24px;width:100%;">
                <tr>
                  <td style="padding:14px 18px;">
                    <span style="color:#1d4ed8;font-size:14px;font-weight:600;">
                      &#128206; architecture_report.pdf
                    </span><br>
                    <span style="color:#64748b;font-size:13px;">
                      Attached to this email
                    </span>
                  </td>
                </tr>
              </table>

              <!-- Deliverables list -->
              <p style="color:#1e293b;font-size:15px;font-weight:600;margin:0 0 10px;">
                This report includes:
              </p>
              <ul style="color:#334155;font-size:14px;line-height:1.9;
                         padding-left:20px;margin:0 0 28px;">
                <li>Executive Summary &amp; Requirements Analysis</li>
                <li>Technology Stack with cost estimates</li>
                <li>Architecture Blueprint &amp; Design Decisions</li>
                <li>Well-Architected Framework review</li>
                <li>Risk assessment &amp; recommendations</li>
                <li>Production-quality architecture diagram</li>
              </ul>

              <p style="color:#64748b;font-size:14px;line-height:1.6;margin:0 0 28px;">
                If you have any questions or would like to discuss the architecture
                in detail, please reply to this email.
              </p>

              <p style="color:#334155;font-size:15px;margin:0;">
                Best regards,<br>
                <strong>BNK Solution Architecture Team</strong><br>
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


def _upload_pdf_to_composio(client, pdf_bytes: bytes) -> str:
    """Upload PDF bytes to Composio file storage; return the S3 key."""
    md5 = hashlib.md5(pdf_bytes).hexdigest()
    resp = client.client.files.create_presigned_url(
        filename="architecture_report.pdf",
        md5=md5,
        mimetype="application/pdf",
        tool_slug="GMAIL_SEND_EMAIL",
        toolkit_slug="GMAIL",
    )
    # PUT the file bytes to the presigned S3 URL
    upload_resp = httpx.put(
        resp.new_presigned_url,
        content=pdf_bytes,
        headers={"Content-Type": "application/pdf"},
        timeout=60,
    )
    upload_resp.raise_for_status()
    return resp.key


class SendEmailConfig(BaseModel):
    recipient_email: str
    subject: str
    project_name: str
    subtitle: str = ""
    recipient_name: str = "Team"


@tool(args_schema=SendEmailConfig)
def send_architecture_report_email(
    recipient_email: str,
    subject: str,
    project_name: str,
    runtime: ToolRuntime[SessionContext],
    subtitle: str = "",
    recipient_name: str = "Team",
) -> str:
    """Send the generated architecture report PDF to a recipient via Gmail.

    Reads out.pdf from the workspace, uploads it to Composio file storage,
    then delivers it as an email attachment with a professional HTML template
    branded for BNK Solution.

    Requires a Composio API key and a connected Gmail account (run
    `composio add gmail` once to authorise the sending account).
    Call this ONLY after generate_pdf_report() has completed successfully.
    This tool PAUSES for user approval before sending.
    """
    ctx = runtime.context
    # Default the recipient to the session user when the model leaves it blank.
    recipient_email = recipient_email or ctx.user_email
    if not recipient_email:
        return "ERROR: no recipient_email provided and no session user_email available."
    pdf_path: Path = WORKSPACE / "out.pdf"
    if not pdf_path.exists():
        return (
            "ERROR: out.pdf not found in workspace. "
            "Call generate_pdf_report() first, then retry."
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
    gmail_account_id = ctx.gmail_account_id or "ca_LVbY16_Vo874"

    html_body = _EMAIL_HTML_TEMPLATE.format(
        project_name=project_name,
        subtitle=subtitle or "",
        recipient_name=recipient_name or "Team",
        year=datetime.now().year,
    )

    pdf_bytes = pdf_path.read_bytes()
    final_subject = subject or f"Architecture Report — {project_name}"

    try:
        client = composio.Composio(api_key=api_key)
    except Exception as exc:
        return (
            f"ERROR: Composio client initialisation failed: {exc}. "
            "Check that COMPOSIO_API_KEY is valid."
        )

    try:
        s3_key = _upload_pdf_to_composio(client, pdf_bytes)
    except Exception as exc:
        return (
            f"ERROR: Failed to upload PDF to Composio storage: {exc}. "
            "Check your network connection and COMPOSIO_API_KEY."
        )

    try:
        result = client.tools.execute(
            "GMAIL_SEND_EMAIL",
            arguments={
                "recipient_email": recipient_email,
                "subject": final_subject,
                "body": html_body,
                "is_html": True,
                "attachment": {
                    "name": "architecture_report.pdf",
                    "mimetype": "application/pdf",
                    "s3key": s3_key,
                },
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

    return (
        f"Email sent successfully to {recipient_email}. "
        f"Subject: \"{final_subject}\". "
        f"PDF attached ({len(pdf_bytes):,} bytes)."
    )
