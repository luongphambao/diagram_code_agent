"""brd_toc — refresh the cached TOC field text (docs/plans/2026-07-29-brd-agent.md §E1).

Word's TOC field is only recalculated when a human opens the file in Word, so a
document built or patched by this agent shows STALE page numbers in every other
viewer (browser PDF preview, an emailed attachment opened in Preview/Acrobat).
We refresh the cached text by round-tripping through a LibreOffice-rendered
PDF's real bookmark page numbers, mirroring the soffice_available()/best-effort
pattern already used for the WBS sheet screenshots
(domain/wbs/wbs_excel_render.py), including the per-call UserInstallation
profile — a shared LibreOffice profile would otherwise serialize (or fail)
concurrent conversions from different per-thread workspaces.

Best-effort, NEVER blocking: if `soffice` isn't on PATH or the conversion fails,
every TOC field is still marked `w:dirty="true"` so Word recomputes it on next
open — the document is never worse off, just not pre-refreshed for non-Word
viewers.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path
from typing import Optional

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from domain.brd.brd_docx import blocks

logger = logging.getLogger(__name__)

_CONVERT_TIMEOUT_S = 60


def soffice_available() -> bool:
    return shutil.which("soffice") is not None


def _element(block):
    return block._p if isinstance(block, Paragraph) else block._tbl


def _mark_toc_dirty(doc) -> int:
    n = 0
    for fld in doc.element.body.iter(qn("w:fldChar")):
        if fld.get(qn("w:fldCharType")) == "begin":
            fld.set(qn("w:dirty"), "true")
            n += 1
    return n


def _to_pdf(docx_path: Path, out_dir: Path, *, timeout: int = _CONVERT_TIMEOUT_S) -> Optional[Path]:
    if not soffice_available():
        return None
    profile_dir = out_dir / "lo_profile"
    try:
        subprocess.run(
            [
                "soffice",
                "--headless",
                "--norestore",
                f"-env:UserInstallation=file://{profile_dir}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(out_dir),
                str(docx_path),
            ],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
    except Exception:
        logger.warning("soffice convert-to-pdf failed for %s", docx_path, exc_info=True)
        return None
    pdf_path = out_dir / (docx_path.stem + ".pdf")
    return pdf_path if pdf_path.exists() else None


def _pdf_outline(pdf_path: Path) -> list[tuple[int, str, int]]:
    warnings.filterwarnings("ignore")
    import pypdf

    r = pypdf.PdfReader(str(pdf_path))
    out: list[tuple[int, str, int]] = []

    def walk(items, depth=0):
        for it in items:
            if isinstance(it, list):
                walk(it, depth + 1)
            else:
                try:
                    pg = r.get_destination_page_number(it) + 1
                except Exception:
                    pg = 1
                out.append((depth, it.title.strip(), pg))

    walk(r.outline)
    return out


def _run(p, text: Optional[str] = None, tab: bool = False, style: Optional[str] = None):
    r = p.add_run(text or "")
    if style:
        try:
            r.style = style
        except KeyError:
            pass
    if tab:
        r._r.append(OxmlElement("w:tab"))
    return r


_NUMBERED_TITLE_RE = re.compile(r"^((?:\d+(?:\.\d+)*)|(?:Appendix\s+[A-Z]\.))\s+(.+)$")


def rebuild_toc(docx_path: Path, entries: list[tuple[int, str, int]]) -> int:
    """entries: list[(level0, title, page)] — level0 = 0/1/2 for toc 1/2/3.
    Rewrites only the TOC paragraphs, borrowing each level's own tab-stop/dot-
    leader pPr from the existing template TOC so the visual contract never
    changes — same "borrow, don't invent" rule as heading numbering."""
    import copy as _copy

    doc = Document(docx_path)
    bs = blocks(doc)
    toc_idx = [i for i, b in enumerate(bs) if hasattr(b, "style") and (b.style.name or "").startswith("toc ")]
    if not toc_idx:
        return 0

    first, last = bs[toc_idx[0]], bs[toc_idx[-1]]

    open_runs, close_run = [], None
    for r in first._p.findall(qn("w:r")):
        fc = r.find(qn("w:fldChar"))
        if (fc is not None and fc.get(qn("w:fldCharType")) in ("begin", "separate")) or r.find(
            qn("w:instrText")
        ) is not None:
            open_runs.append(r)
    for r in last._p.iter(qn("w:r")):
        fc = r.find(qn("w:fldChar"))
        if fc is not None and fc.get(qn("w:fldCharType")) == "end":
            close_run = r
    for r in open_runs:
        r.getparent().remove(r)
    if close_run is not None:
        close_run.getparent().remove(close_run)

    exemplar = {}
    for i in toc_idx:
        b = bs[i]
        name = b.style.name
        if name not in exemplar:
            pPr = b._p.find(qn("w:pPr"))
            if pPr is not None:
                exemplar[name] = _copy.deepcopy(pPr)

    anchor = first._p.getprevious()
    parent = first._p.getparent()
    for i in toc_idx:
        el = _element(bs[i])
        el.getparent().remove(el)

    new_ps = []
    for lvl, title, page in entries:
        style = f"toc {min(lvl, 8) + 1}"
        p = doc.add_paragraph()
        try:
            p.style = doc.styles[style]
        except KeyError:
            style = "toc 1"
            p.style = doc.styles[style]
        if style in exemplar:
            old = p._p.find(qn("w:pPr"))
            if old is not None:
                p._p.remove(old)
            p._p.insert(0, _copy.deepcopy(exemplar[style]))
        m = _NUMBERED_TITLE_RE.match(title)
        if m:
            _run(p, m.group(1))
            _run(p, tab=True)
            _run(p, m.group(2))
        else:
            _run(p, title)
        _run(p, tab=True)
        _run(p, str(page))
        new_ps.append(p)

    if new_ps:
        for r in reversed(open_runs):
            new_ps[0]._p.insert(1, r)
        if close_run is not None:
            new_ps[-1]._p.append(close_run)

    cursor = anchor
    for p in new_ps:
        p._p.getparent().remove(p._p)
        if cursor is None:
            parent.insert(0, p._p)
        else:
            cursor.addnext(p._p)
        cursor = p._p

    doc.save(docx_path)
    return len(new_ps)


def refresh_toc(docx_path: Path, *, passes: int = 2) -> bool:
    """Best-effort TOC refresh. Returns True if the PDF round-trip wrote real
    page numbers, False if it fell back to marking fields dirty only (soffice
    missing, conversion failed, or the document has no TOC) — never raises."""
    if not soffice_available():
        doc = Document(docx_path)
        n = _mark_toc_dirty(doc)
        if n:
            doc.save(docx_path)
        logger.info("soffice not on PATH — marked %d TOC field(s) dirty only, no page-number refresh", n)
        return False

    ok = False
    with tempfile.TemporaryDirectory(prefix="brd_toc_") as tmp:
        tmp_dir = Path(tmp)
        for _ in range(passes):
            pdf_path = _to_pdf(docx_path, tmp_dir)
            if pdf_path is None:
                break
            entries = _pdf_outline(pdf_path)
            if not entries:
                break
            n = rebuild_toc(docx_path, entries)
            if not n:
                break
            ok = True

    doc = Document(docx_path)
    _mark_toc_dirty(doc)
    doc.save(docx_path)
    return ok
