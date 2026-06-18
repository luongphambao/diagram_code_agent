"""Test script: gửi email với file đính kèm dùng Composio auto file handling.

Docs: https://docs.composio.dev/docs/tools-direct/executing-tools#automatic-file-handling

Chạy từ thư mục backend:
    uv run python scripts/test_send_email_auto_file.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Load .env
BACKEND_DIR = Path(__file__).parent.parent
ENV_FILE = BACKEND_DIR / ".env"
if ENV_FILE.exists():
    from dotenv import load_dotenv
    load_dotenv(ENV_FILE)
    print(f"[INFO] Loaded env from {ENV_FILE}")

RECIPIENT      = "minh.doan@bnksolution.com"
SUBJECT        = "Architecture Report — BNK Solution"
ATTACHMENT_PATH = "/tmp/architecture_report_compressed.pdf"

HTML_BODY = f"""\
<!DOCTYPE html>
<html lang="vi">
<body style="font-family:Arial,sans-serif;color:#1e293b;padding:32px;">
  <h2 style="color:#2563eb;">BNK Solution — Test Auto File Handling</h2>
  <p>Xin chào <strong>Anh Minh</strong>,</p>
  <p>
    Đây là email test gửi từ hệ thống <strong>diagram-code-agent</strong>
    sử dụng Composio <em>automatic file handling</em>.<br>
    File đính kèm được pass trực tiếp bằng local path — không cần presigned URL thủ công.
  </p>
  <p style="background:#eff6ff;border-left:4px solid #2563eb;padding:12px;border-radius:4px;">
    &#128206; <strong>diagram(24).png</strong> — đính kèm bên dưới
  </p>
  <p>Trân trọng,<br><strong>BNK Solution Architecture Team</strong></p>
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

    print(f"[INFO] COMPOSIO_API_KEY  = {api_key[:12]}...")
    print(f"[INFO] GMAIL_ACCOUNT_ID  = {account_id}")
    print(f"[INFO] Recipient         = {RECIPIENT}")
    print(f"[INFO] Attachment        = {attachment} ({attachment.stat().st_size:,} bytes)")

    try:
        import composio  # type: ignore[import]
    except ImportError:
        print("[ERROR] composio chưa được cài. Chạy: pip install composio-langchain")
        sys.exit(1)

    # Bật auto file handling, whitelist thư mục chứa file
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
                "attachment": str(attachment),   # local path — SDK tự xử lý upload
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
