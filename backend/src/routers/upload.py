"""Upload endpoint — extract requirement documents to text."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from backends import AGENT_SPACE
from document_parsers import parse_file
from document_parsers.content_sniff import sniff_mismatch
from document_parsers.parsers import SUPPORTED_EXT
from safe_path import safe_filename
from security.auth import Identity, require_identity

router = APIRouter(tags=["upload"])

UPLOADS_DIR = AGENT_SPACE / "uploads"

# Improvement plan §0.4: an unauthenticated /upload that reads a whole file
# into memory with no cap is a denial-of-service vector. Stream to disk in
# chunks instead, aborting (and deleting the partial file) the moment the cap
# is crossed — the client's declared Content-Length is not trusted either,
# since it can be omitted or forged.
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))  # 25 MB
_CHUNK_SIZE = 1024 * 1024  # 1 MB
_SNIFF_HEAD_BYTES = 64


async def _stream_to_disk(file: UploadFile, dest: Path) -> None:
    """Write *file* to *dest* in bounded chunks, raising 413 (and deleting
    the partial file) if it exceeds MAX_UPLOAD_BYTES before EOF."""
    total = 0
    with dest.open("wb") as out:
        while True:
            chunk = await file.read(_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds the {MAX_UPLOAD_BYTES} byte upload limit",
                )
            out.write(chunk)


@router.post("/upload")
async def upload(
    file: UploadFile = File(...), identity: Identity = Depends(require_identity)
):
    # §0.6: require *some* server-resolved identity so /upload isn't a fully
    # anonymous write surface — no per-upload ownership is enforced here (a
    # file_id is only useful to the caller that receives it back in this same
    # response and later attaches it via file_ids on /agui, which is where
    # thread-ownership is actually enforced).
    del identity
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or '(none)'}")

    file_id = uuid.uuid4().hex[:12]
    raw_path = UPLOADS_DIR / f"{file_id}_{safe_filename(file.filename)}"
    await _stream_to_disk(file, raw_path)

    # Content-based check: the extension must match what the bytes actually
    # are, not just what the client claims (filename/Content-Type are both
    # client-controlled and untrusted).
    with raw_path.open("rb") as f:
        head = f.read(_SNIFF_HEAD_BYTES)
    mismatch = sniff_mismatch(ext, head)
    if mismatch:
        raw_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Rejected upload: {mismatch}")

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
                        "text": "[image]",  # mimo requires a non-empty text on every content block
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                        "filename": fname,
                    })
            except Exception:  # noqa: BLE001
                pass
    return blocks
