"""Test script: compress PDF rồi gửi qua Composio Gmail (auto file handling).

Chạy từ thư mục backend:
    uv run python scripts/test_send_email_pdf.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

# Load .env từ thư mục backend
BACKEND_DIR = Path(__file__).parent.parent
ENV_FILE = BACKEND_DIR / ".env"

if ENV_FILE.exists():
    from dotenv import load_dotenv
    load_dotenv(ENV_FILE)
    print(f"[INFO] Loaded env from {ENV_FILE}")
else:
    print(f"[WARN] .env not found at {ENV_FILE}")

RECIPIENT       = "minh.doan@bnksolution.com"
SUBJECT         = "Architecture Report — BNK Solution"
SOURCE_PDF      = Path("/home/baoluong/projects/diagram_code_agent/architecture_report.pdf")
COMPRESSED_PDF  = Path("/tmp/architecture_report_compressed.pdf")

HTML_BODY = """\
<!DOCTYPE html>
<html lang="vi">
<body style="font-family:Arial,sans-serif;color:#1e293b;padding:32px;">
  <h2 style="color:#2563eb;">BNK Solution — Architecture Report</h2>
  <p>Xin chào <strong>Anh Minh</strong>,</p>
  <p>
    Vui lòng xem file <strong>Architecture Report</strong> đính kèm từ hệ thống
    <strong>diagram-code-agent</strong>.
  </p>
  <p style="background:#eff6ff;border-left:4px solid #2563eb;padding:12px;border-radius:4px;">
    &#128206; <strong>architecture_report.pdf</strong> — đính kèm bên dưới
  </p>
  <p>Trân trọng,<br><strong>BNK Solution Architecture Team</strong></p>
</body>
</html>"""


def compress_pdf(src: Path, dst: Path) -> None:
    """Compress PDF bằng Ghostscript."""
    result = subprocess.run(
        [
            "gs",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            "-dPDFSETTINGS=/ebook",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-sOutputFile={dst}",
            str(src),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Ghostscript thất bại: {result.stderr}")
    orig = src.stat().st_size
    comp = dst.stat().st_size
    pct  = (1 - comp / orig) * 100
    print(f"[INFO] Compress OK: {orig:,} → {comp:,} bytes (giảm {pct:.0f}%)")


def main():
    api_key    = os.environ.get("COMPOSIO_API_KEY", "")
    account_id = os.environ.get("GMAIL_CONNECTED_ACCOUNT_ID", "")

    if not api_key:
        print("[ERROR] COMPOSIO_API_KEY chưa được set.")
        sys.exit(1)
    if not account_id:
        print("[ERROR] GMAIL_CONNECTED_ACCOUNT_ID chưa được set.")
        sys.exit(1)

    if not SOURCE_PDF.exists():
        print(f"[ERROR] Không tìm thấy file: {SOURCE_PDF}")
        sys.exit(1)

    try:
        import composio  # type: ignore[import]
    except ImportError:
        print("[ERROR] composio chưa được cài. Chạy: pip install composio-langchain")
        sys.exit(1)

    # Compress
    print(f"[INFO] Compressing {SOURCE_PDF.name}...")
    compress_pdf(SOURCE_PDF, COMPRESSED_PDF)

    print(f"[INFO] COMPOSIO_API_KEY  = {api_key[:12]}...")
    print(f"[INFO] GMAIL_ACCOUNT_ID  = {account_id}")
    print(f"[INFO] Recipient         = {RECIPIENT}")
    print(f"[INFO] Attachment        = {COMPRESSED_PDF} ({COMPRESSED_PDF.stat().st_size:,} bytes)")

    client = composio.Composio(
        api_key=api_key,
        dangerously_allow_auto_upload_download_files=True,
        file_upload_dirs=["/tmp", "~/.composio/temp"],
    )

    # Gửi mail với retry
    MAX_RETRIES = 5
    RETRY_DELAY = 65

    result = None
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"[INFO] Đang gửi email... (lần {attempt}/{MAX_RETRIES})")
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
                    "attachment": str(COMPRESSED_PDF),
                },
            )
            break
        except Exception as exc:
            err_str = str(exc)
            if any(code in err_str for code in ("520", "521", "522", "502", "503", "504", "500")):
                if attempt < MAX_RETRIES:
                    print(f"[WARN] Lỗi tạm thời: {exc}")
                    print(f"[INFO] Chờ {RETRY_DELAY}s rồi thử lại...")
                    time.sleep(RETRY_DELAY)
                    continue
            print(f"[ERROR] Lỗi khi gửi email: {exc}")
            sys.exit(1)

    if result is None:
        print("[ERROR] Không thể gửi email sau tất cả các lần thử.")
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
    print(f"     Subject : {SUBJECT}")
    print(f"     PDF size: {COMPRESSED_PDF.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
