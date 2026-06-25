# Superseded by integrations/email.py — this shim preserves backward compatibility.
from integrations.email import (  # noqa: F401
    SendEmailConfig,
    _EMAIL_HTML_TEMPLATE,
    _upload_pdf_to_composio,
    send_architecture_report_email,
)
