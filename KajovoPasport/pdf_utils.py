from __future__ import annotations

import io
import os
import tempfile
import webbrowser
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


def _ensure_pdf_font() -> str:
    """Register a TrueType font that covers Czech glyphs; fallback to Helvetica."""
    font_name = "KajovoSans"
    candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/arialuni.ttf"),
        Path("C:/Windows/Fonts/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                pdfmetrics.registerFont(TTFont(font_name, str(candidate)))
                return font_name
            except Exception:
                break
    return "Helvetica"


def generate_card_pdf(
    out_path: str,
    card_name: str,
    fields: List[Tuple[str, str]],  # (field_key, label)
    images_png: Dict[str, bytes],
    margin_mm: float = 5.0,
) -> str:
    """Generate an A4 portrait PDF for one card."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    page_w, page_h = A4
    c = canvas.Canvas(str(out), pagesize=A4)

    margin = margin_mm * mm
    content_w = page_w - 2 * margin
    content_h = page_h - 2 * margin

    # Title area
    title_font = 16
    title_h = 18 * mm
    font_name = _ensure_pdf_font()
    c.setFont(font_name, title_font)
    c.drawString(margin, page_h - margin - title_font * 1.2, card_name)

    # Grid below title
    grid_top = page_h - margin - title_h
    grid_bottom = margin
    grid_h = grid_top - grid_bottom
    grid_w = content_w

    cols = 4
    rows = 4
    gap = 2.0 * mm

    cell_w = (grid_w - gap * (cols - 1)) / cols
    cell_h = (grid_h - gap * (rows - 1)) / rows

    label_font = 8
    label_h = 9 * mm  # room for multiword labels
    img_pad = 1.5 * mm

    c.setLineWidth(0.8)

    for idx, (field_key, label) in enumerate(fields):
        r = idx // cols
        col = idx % cols

        x = margin + col * (cell_w + gap)
        y = grid_top - (r + 1) * cell_h - r * gap

        # Cell border
        c.rect(x, y, cell_w, cell_h, stroke=1, fill=0)

        # Label
        c.setFont(font_name, label_font)
        c.drawString(x + img_pad, y + img_pad, label)

        # Image area (above label)
        img_x = x + img_pad
        img_y = y + label_h
        img_w = cell_w - 2 * img_pad
        img_h = cell_h - label_h - img_pad

        # White background for image area
        c.setFillGray(1.0)
        c.rect(img_x, img_y, img_w, img_h, stroke=0, fill=1)
        c.setFillGray(0.0)

        png = images_png.get(field_key)
        if png:
            try:
                ir = ImageReader(io.BytesIO(png))
                iw, ih = ir.getSize()
                # Fit image into img_w/img_h, preserve aspect
                scale = min(img_w / iw, img_h / ih)
                dw, dh = iw * scale, ih * scale
                dx = img_x + (img_w - dw) / 2
                dy = img_y + (img_h - dh) / 2
                c.drawImage(ir, dx, dy, dw, dh, preserveAspectRatio=True, mask="auto")
            except Exception:
                # If image fails, keep blank.
                pass

    c.showPage()
    c.save()
    return str(out)


def open_pdf(path: str) -> None:
    p = Path(path)
    if not p.exists():
        return
    try:
        os.startfile(str(p))  # type: ignore[attr-defined]
    except Exception:
        webbrowser.open(p.as_uri())


def print_pdf_windows(path: str) -> bool:
    """Try to invoke Windows shell print action. Returns True if invoked."""
    p = Path(path)
    if not p.exists():
        return False
    try:
        os.startfile(str(p), "print")  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


def make_temp_pdf_path(card_name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in (" ", "_", "-") else "_" for ch in card_name).strip() or "karta"
    safe = safe.replace(" ", "_")
    tmp = Path(tempfile.gettempdir()) / f"KajovoPasport_{safe}.pdf"
    return str(tmp)
