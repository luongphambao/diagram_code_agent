"""Gửi file wbs_filled.xlsx qua email dùng Composio auto file handling.

Chạy từ thư mục backend:
    uv run python scripts/send_wbs_email.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent
ENV_FILE = BACKEND_DIR / ".env"
if ENV_FILE.exists():
    from dotenv import load_dotenv
    load_dotenv(ENV_FILE)
    print(f"[INFO] Loaded env from {ENV_FILE}")

RECIPIENT       = "bao.luong@bnksolution.com"
SUBJECT         = "WBS — diagram_code_agent"
ATTACHMENT_PATH = "/home/baoluong/projects/diagram_code_agent/wbs_filled.xlsx"

HTML_BODY = f"""\
<!DOCTYPE html>
<html lang="vi">
<body style="font-family:Arial,sans-serif;color:#1e293b;padding:32px;">
  <h2 style="color:#2563eb;">WBS File</h2>
  <p>Xin chào,</p>
  <p>
    Đính kèm file <strong>wbs_filled.xlsx</strong> được gửi từ hệ thống
    <strong>diagram-code-agent</strong> qua Composio.
  </p>
  <p>Trân trọng.</p>
</body>
</html>"""


def main():
    api_key    = os.environ.get("COMPOSIO_API_KEY", "")
    account_id = os.environ.get("GMAIL_CONNECTED_ACCOUNT_ID", "")

    if not api_key:
        print("[ERROR] COMPOSIO_API_KEY chưa được set.")
        sys.exit(1)
    if not account_id:
        print("[ERROR] GMAIL_CONNECTED_ACCOUNT_ID chưa được set.")
        sys.exit(1)

    attachment = Path(ATTACHMENT_PATH)
    if not attachment.exists():
        print(f"[ERROR] Không tìm thấy file: {attachment}")
        sys.exit(1)

    print(f"[INFO] Recipient  = {RECIPIENT}")
    print(f"[INFO] Attachment = {attachment} ({attachment.stat().st_size:,} bytes)")

    try:
        import composio  # type: ignore[import]
    except ImportError:
        print("[ERROR] composio chưa được cài. Chạy: pip install composio-langchain")
        sys.exit(1)

    client = composio.Composio(
        api_key=api_key,
        dangerously_allow_auto_upload_download_files=True,
        file_upload_dirs=[str(attachment.parent), "~/.composio/temp", "/tmp"],
    )

    print("[INFO] Đang gửi email (auto file handling)...")
    try:
        result = client.tools.execute(
            slug="GMAIL_SEND_EMAIL",
            connected_account_id=account_id,
            version="20260615_00",
            arguments={
                "recipient_email": RECIPIENT,
                "subject": SUBJECT,
                "body": HTML_BODY,
                "is_html": True,
                "attachment": str(attachment),
            },
        )
    except Exception as exc:
        print(f"[ERROR] Lỗi khi gửi: {exc}")
        sys.exit(1)

    print(f"[INFO] Kết quả: {result}")

    err = result.get("error") if isinstance(result, dict) else getattr(result, "error", None)
    if err:
        print(f"[ERROR] Composio trả về lỗi: {err}")
        sys.exit(1)

    successful = result.get("successful") if isinstance(result, dict) else getattr(result, "successful", True)
    if not successful:
        data = result.get("data") if isinstance(result, dict) else getattr(result, "data", result)
        print(f"[ERROR] Composio báo thất bại: {data}")
        sys.exit(1)

    print(f"\n[OK] Email gửi thành công tới {RECIPIENT}!")
    print(f"     Subject: {SUBJECT}")
    print(f"     Attachment: {attachment.name}")


if __name__ == "__main__":
    main()
