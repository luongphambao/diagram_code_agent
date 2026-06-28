"""Upload endpoint — extract requirement documents to text."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, File, UploadFile

from backends import AGENT_SPACE
from document_parsers import parse_file

router = APIRouter(tags=["upload"])

UPLOADS_DIR = AGENT_SPACE / "uploads"


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex[:12]
    raw_path = UPLOADS_DIR / f"{file_id}_{file.filename}"
    raw_path.write_bytes(await file.read())

    doc = parse_file(raw_path)
    if doc.kind == "image" and doc.ok:
        (UPLOADS_DIR / f"{file_id}.img.json").write_text(
            json.dumps({"b64": doc.image_b64, "mime": doc.image_mime, "filename": file.filename}),
            encoding="utf-8",
        )
        return {
            "file_id": file_id,
            "filename": file.filename,
            "kind": "image",
            "char_count": 0,
            "preview": f"[reference image: {file.filename}]",
            "error": doc.error,
        }
    text = doc.text if doc.ok else ""
    (UPLOADS_DIR / f"{file_id}.md").write_text(text, encoding="utf-8")
    return {
        "file_id": file_id,
        "filename": file.filename,
        "kind": doc.kind,
        "char_count": len(text),
        "preview": text[:300],
        "error": doc.error,
    }


def _attached_text(file_ids: list[str]) -> str:
    parts = []
    for fid in file_ids or []:
        p = UPLOADS_DIR / f"{fid}.md"
        if p.exists():
            t = p.read_text(encoding="utf-8", errors="replace").strip()
            if t:
                parts.append(t)
    return "\n\n---\n\n".join(parts)


def _attached_images(file_ids: list[str]) -> list[dict]:
    """Return image content blocks for any uploaded reference images."""
    blocks = []
    for fid in file_ids or []:
        p = UPLOADS_DIR / f"{fid}.img.json"
        if p.exists():
            try:
                meta = json.loads(p.read_text(encoding="utf-8"))
                b64 = meta.get("b64", "")
                mime = meta.get("mime", "image/png")
                fname = meta.get("filename", "reference")
                if b64:
                    blocks.append({
                        "type": "image_url",
                        "text": "",  # mimo requires text on every content block
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                        "filename": fname,
                    })
            except Exception:  # noqa: BLE001
                pass
    return blocks
