"""Overlay filled values onto the Terapias Ambulatorias blank PDF template."""

from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path

from django.conf import settings
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import black, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

APP_DIR = Path(__file__).resolve().parent
DEFAULT_PDF_TEMPLATE = APP_DIR / "assets" / "terapias_ambulatorias.pdf"

PAGE_WIDTH = 595.30396
PAGE_HEIGHT = 841.88977
LEFT = 85.15
FONT_SIZE = 11
VALUE_COLOR = black

_CARLITO = APP_DIR / "assets" / "fonts" / "Carlito-Regular.ttf"
if _CARLITO.is_file():
    pdfmetrics.registerFont(TTFont("FormFont", str(_CARLITO)))
    FONT_NAME = "FormFont"
else:
    FONT_NAME = "Helvetica"

# Sit above the underscore so the blue line stays fully visible under the text
Y_LIFT = 3.5
Y_FECHA = 715.3 + Y_LIFT
Y_NOMBRE = 641.3 + Y_LIFT
Y_DNI = 626.8 + Y_LIFT
Y_DIAG = [612.3 + Y_LIFT, 597.8 + Y_LIFT, 583.3 + Y_LIFT]
Y_PREST = [568.8 + Y_LIFT, 554.3 + Y_LIFT]
Y_FREQ = 539.8 + Y_LIFT
Y_PERIODO = 525.3 + Y_LIFT

X_FECHA = 439.0
X_NOMBRE = 182.0
X_DNI = 108.0
X_EDAD = 276.0
X_DIAG = 148.0
X_PREST = 143.0
X_FREQ = 190.0
X_PERIODO = 126.0
RIGHT = 508.0

_MONTH_ABBR = (
    "Ene",
    "Feb",
    "Mar",
    "Abr",
    "May",
    "Jun",
    "Jul",
    "Ago",
    "Sep",
    "Oct",
    "Nov",
    "Dic",
)


def get_pdf_template_path() -> Path:
    override = getattr(settings, "TERAPIAS_AMBULATORIAS_PDF", None)
    return Path(override) if override else DEFAULT_PDF_TEMPLATE


def _fmt_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _fmt_month_year(value: date) -> str:
    return f"{_MONTH_ABBR[value.month - 1]} - {value.year}"


def _fmt_timeframe(desde: date, hasta: date) -> str:
    return f"{_fmt_month_year(desde)} / {_fmt_month_year(hasta)}"


def _wrap_text(text: str, max_width: float, font_name: str = FONT_NAME, font_size: float = FONT_SIZE) -> list[str]:
    text = " ".join(text.split())
    if not text:
        return []
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            while stringWidth(word, font_name, font_size) > max_width:
                cut = len(word)
                while cut > 1 and stringWidth(word[:cut], font_name, font_size) > max_width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_on_line(c: canvas.Canvas, text: str, x: float, y: float) -> None:
    """Black text above the blue line — transparent, does not erase the underline."""
    if not text:
        return
    c.setFillColor(VALUE_COLOR)
    c.setFont(FONT_NAME, FONT_SIZE)
    c.drawString(x, y, text)


def build_overlay(data: dict) -> BytesIO:
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))

    _draw_on_line(c, _fmt_date(data["fecha"]), X_FECHA, Y_FECHA)
    _draw_on_line(c, data["nombre_apellido"][:90], X_NOMBRE, Y_NOMBRE)
    _draw_on_line(c, str(data["dni"]), X_DNI, Y_DNI)
    _draw_on_line(c, str(data["edad"]), X_EDAD, Y_DNI)

    diag = _wrap_text(data["diagnostico"], RIGHT - X_DIAG)
    if len(diag) > 1:
        diag = [diag[0], *_wrap_text(" ".join(diag[1:]), RIGHT - LEFT)]
    for i, line in enumerate(diag[:3]):
        x = X_DIAG if i == 0 else LEFT
        _draw_on_line(c, line, x, Y_DIAG[i])

    prest = _wrap_text(data["prestacion"], RIGHT - X_PREST)
    if len(prest) > 1:
        prest = [prest[0], *_wrap_text(" ".join(prest[1:]), RIGHT - LEFT)]
    for i, line in enumerate(prest[:2]):
        x = X_PREST if i == 0 else LEFT
        _draw_on_line(c, line, x, Y_PREST[i])

    _draw_on_line(c, data["frecuencia_semanal"][:80], X_FREQ, Y_FREQ)

    # Periodo still has dense date blanks (__/__/____); clear only that crowded stretch
    timeframe = _fmt_timeframe(data["periodo_desde"], data["periodo_hasta"])
    c.setFillColor(white)
    c.rect(X_PERIODO - 1, Y_PERIODO - Y_LIFT - 3.0, RIGHT - X_PERIODO + 2, 12, stroke=0, fill=1)
    _draw_on_line(c, timeframe, X_PERIODO, Y_PERIODO)

    c.save()
    buffer.seek(0)
    return buffer


def fill_prescription_pdf(data: dict, template_path: Path | None = None) -> bytes:
    template = Path(template_path) if template_path else get_pdf_template_path()
    if not template.is_file():
        raise FileNotFoundError(f"PDF template not found: {template}")

    overlay_buf = build_overlay(data)
    writer = PdfWriter(clone_from=str(template))
    overlay_reader = PdfReader(overlay_buf)
    writer.pages[0].merge_page(overlay_reader.pages[0])

    out = BytesIO()
    writer.write(out)
    return out.getvalue()
