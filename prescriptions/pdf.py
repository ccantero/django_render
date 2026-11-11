"""Overlay filled values onto the Terapias Ambulatorias blank PDF template.

Field geometry was measured from the bundled Galeno blank PDF (A4, Carlito 11pt
label text). Values are fitted with ReportLab ``stringWidth`` measurements.

Period handling: the Django form collects month/year only (``<input type="month">``).
The template has day/month/year blanks for ``desde`` and ``hasta``. This module
writes day 01 for ``periodo_desde``, the calendar last day of the month for
``periodo_hasta`` (via ``calendar.monthrange``), the Spanish month name, and
the year — each centered in its measured blank.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path

from django.conf import settings
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import black
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

APP_DIR = Path(__file__).resolve().parent
DEFAULT_PDF_TEMPLATE = APP_DIR / "assets" / "terapias_ambulatorias.pdf"

PAGE_WIDTH = 595.30396
PAGE_HEIGHT = 841.88977
LEFT = 85.15
# Right edge of full underscore rows measured from the template label lines.
RIGHT = 507.0

FONT_SIZE = 11.0
MIN_FONT_SIZE = 8.0
VALUE_COLOR = black

# Sit slightly above the printed underscore so text stays legible without
# floating into the previous field or colliding with date separators.
Y_LIFT = 2.0
# Small gap after labels so values do not crowd printed glyphs.
X_PAD = 4.0
# Keep period month/year clear of the printed '/' separators.
PERIOD_INSET = 2.0

_CARLITO = APP_DIR / "assets" / "fonts" / "Carlito-Regular.ttf"
if _CARLITO.is_file():
    pdfmetrics.registerFont(TTFont("FormFont", str(_CARLITO)))
    FONT_NAME = "FormFont"
else:
    FONT_NAME = "Helvetica"

# Template baselines (y) from pypdf text positions + Y_LIFT.
Y_FECHA = 715.34 + Y_LIFT
Y_NOMBRE = 641.34 + Y_LIFT
Y_DNI = 626.84 + Y_LIFT
Y_DIAG = (612.34 + Y_LIFT, 597.84 + Y_LIFT, 583.34 + Y_LIFT)
Y_PREST = (568.84 + Y_LIFT, 554.34 + Y_LIFT)
Y_FREQ = 539.84 + Y_LIFT
Y_PERIODO = 525.34 + Y_LIFT
LINE_GAP = 14.5

# FECHA blanks use the full measured slots so "2026" stays at 11pt.
X_FECHA_DAY = 430.69
W_FECHA_DAY = 21.91
X_FECHA_MONTH = 456.85
W_FECHA_MONTH = 27.39
X_FECHA_YEAR = 488.49
# Measured underscore run is ~21.91pt; allow a hair past it so "2026" stays 11pt.
W_FECHA_YEAR = 22.5

X_NOMBRE = 170.5 + X_PAD
W_NOMBRE = RIGHT - X_NOMBRE

X_DNI = 107.22 + X_PAD
W_DNI = 249.66 - X_DNI
X_EDAD = 274.8 + X_PAD
W_EDAD = 302.2 - X_EDAD

X_DIAG = 140.38 + X_PAD
W_DIAG_FIRST = RIGHT - X_DIAG
W_DIAG_CONT = RIGHT - LEFT

X_PREST = 135.1 + X_PAD
W_PREST_FIRST = RIGHT - X_PREST
W_PREST_CONT = RIGHT - LEFT

X_FREQ = 188.74 + X_PAD
W_FREQ = RIGHT - X_FREQ

# Periodo: desde:______/_____________/________hasta:____/______________/_________.
# Day and year use the full measured blanks so centering matches the underline.
# Month names keep a small inset so long names stay clear of the printed '/'.
X_DESDE_DAY = 155.23
W_DESDE_DAY = 32.87
X_DESDE_MONTH = 192.35 + PERIOD_INSET
W_DESDE_MONTH = 71.22 - (2 * PERIOD_INSET)
X_DESDE_YEAR = 267.82
W_DESDE_YEAR = 43.83
X_HASTA_DAY = 338.89
W_HASTA_DAY = 21.91
X_HASTA_MONTH = 365.05 + PERIOD_INSET
W_HASTA_MONTH = 76.7 - (2 * PERIOD_INSET)
X_HASTA_YEAR = 446.0
W_HASTA_YEAR = 49.31

_MONTH_NAMES = (
    "Enero",
    "Febrero",
    "Marzo",
    "Abril",
    "Mayo",
    "Junio",
    "Julio",
    "Agosto",
    "Septiembre",
    "Octubre",
    "Noviembre",
    "Diciembre",
)


@dataclass(frozen=True)
class FieldBox:
    """Printable area for one logical overlay field."""

    name: str
    x: float
    y: float
    width: float
    max_lines: int = 1
    line_gap: float = LINE_GAP
    continuation_x: float | None = None
    continuation_width: float | None = None

    def x_for_line(self, line_index: int) -> float:
        if line_index == 0:
            return self.x
        return self.continuation_x if self.continuation_x is not None else self.x

    def width_for_line(self, line_index: int) -> float:
        if line_index == 0:
            return self.width
        return (
            self.continuation_width
            if self.continuation_width is not None
            else self.width
        )

    def y_for_line(self, line_index: int) -> float:
        return self.y - (line_index * self.line_gap)


FIELD_BOXES: dict[str, FieldBox] = {
    "fecha_day": FieldBox("fecha_day", X_FECHA_DAY, Y_FECHA, W_FECHA_DAY),
    "fecha_month": FieldBox("fecha_month", X_FECHA_MONTH, Y_FECHA, W_FECHA_MONTH),
    "fecha_year": FieldBox("fecha_year", X_FECHA_YEAR, Y_FECHA, W_FECHA_YEAR),
    "nombre_apellido": FieldBox("nombre_apellido", X_NOMBRE, Y_NOMBRE, W_NOMBRE),
    "dni": FieldBox("dni", X_DNI, Y_DNI, W_DNI),
    "edad": FieldBox("edad", X_EDAD, Y_DNI, W_EDAD),
    "diagnostico": FieldBox(
        "diagnostico",
        X_DIAG,
        Y_DIAG[0],
        W_DIAG_FIRST,
        max_lines=3,
        continuation_x=LEFT,
        continuation_width=W_DIAG_CONT,
    ),
    "prestacion": FieldBox(
        "prestacion",
        X_PREST,
        Y_PREST[0],
        W_PREST_FIRST,
        max_lines=2,
        continuation_x=LEFT,
        continuation_width=W_PREST_CONT,
    ),
    "frecuencia_semanal": FieldBox("frecuencia_semanal", X_FREQ, Y_FREQ, W_FREQ),
    "periodo_desde_day": FieldBox(
        "periodo_desde_day", X_DESDE_DAY, Y_PERIODO, W_DESDE_DAY
    ),
    "periodo_desde_month": FieldBox(
        "periodo_desde_month", X_DESDE_MONTH, Y_PERIODO, W_DESDE_MONTH
    ),
    "periodo_desde_year": FieldBox(
        "periodo_desde_year", X_DESDE_YEAR, Y_PERIODO, W_DESDE_YEAR
    ),
    "periodo_hasta_day": FieldBox(
        "periodo_hasta_day", X_HASTA_DAY, Y_PERIODO, W_HASTA_DAY
    ),
    "periodo_hasta_month": FieldBox(
        "periodo_hasta_month", X_HASTA_MONTH, Y_PERIODO, W_HASTA_MONTH
    ),
    "periodo_hasta_year": FieldBox(
        "periodo_hasta_year", X_HASTA_YEAR, Y_PERIODO, W_HASTA_YEAR
    ),
}


@dataclass(frozen=True)
class OverlaySegment:
    field: str
    text: str
    x: float
    y: float
    width: float
    font_size: float
    line_index: int = 0


@dataclass(frozen=True)
class OverlayPlan:
    segments: tuple[OverlaySegment, ...]


class PrescriptionLayoutError(ValueError):
    """Submitted value cannot fit legibly in its printable field."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(message)


def get_pdf_template_path() -> Path:
    override = getattr(settings, "TERAPIAS_AMBULATORIAS_PDF", None)
    return Path(override) if override else DEFAULT_PDF_TEMPLATE


def period_range_days(month_value: date) -> tuple[date, date]:
    """Return first and last calendar days for a form month/year value."""
    first = date(month_value.year, month_value.month, 1)
    last_day = calendar.monthrange(month_value.year, month_value.month)[1]
    last = date(month_value.year, month_value.month, last_day)
    return first, last


def _normalize_text(text: str) -> str:
    return " ".join(str(text).split())


def _text_width(text: str, font_size: float, font_name: str = FONT_NAME) -> float:
    return stringWidth(text, font_name, font_size)


def fit_single_line(
    text: str,
    max_width: float,
    *,
    field: str,
    font_size: float = FONT_SIZE,
    min_font_size: float = MIN_FONT_SIZE,
    font_name: str = FONT_NAME,
) -> tuple[str, float]:
    """Fit text on one line, shrinking font size within limits; never truncate."""
    value = _normalize_text(text)
    if not value:
        raise PrescriptionLayoutError(field, "Este campo no puede estar vacío.")

    size = font_size
    while size >= min_font_size - 1e-9:
        if _text_width(value, size, font_name) <= max_width:
            return value, size
        size = round(size - 0.5, 2)
    raise PrescriptionLayoutError(
        field,
        "El texto no entra en el campo del PDF de forma legible. "
        "Acortá el contenido e intentá de nuevo.",
    )


def wrap_text_to_widths(
    text: str,
    widths: list[float],
    *,
    field: str,
    font_size: float = FONT_SIZE,
    min_font_size: float = MIN_FONT_SIZE,
    font_name: str = FONT_NAME,
) -> tuple[list[str], float]:
    """Wrap text into at most ``len(widths)`` lines using measured widths."""
    value = _normalize_text(text)
    if not value:
        raise PrescriptionLayoutError(field, "Este campo no puede estar vacío.")

    size = font_size
    while size >= min_font_size - 1e-9:
        lines = _wrap_at_size(value, widths, size, font_name)
        if lines is not None:
            return lines, size
        size = round(size - 0.5, 2)

    raise PrescriptionLayoutError(
        field,
        "El texto no entra en las líneas disponibles del PDF. "
        "Acortá el contenido e intentá de nuevo.",
    )


def _wrap_at_size(
    text: str,
    widths: list[float],
    font_size: float,
    font_name: str,
) -> list[str] | None:
    words = text.split(" ")
    lines: list[str] = []
    index = 0
    for line_i, max_width in enumerate(widths):
        if index >= len(words):
            break
        current = ""
        while index < len(words):
            word = words[index]
            candidate = word if not current else f"{current} {word}"
            if _text_width(candidate, font_size, font_name) <= max_width:
                current = candidate
                index += 1
                continue
            if current:
                break
            # Single word longer than the line: reject this font size.
            return None
        if current:
            lines.append(current)
        elif line_i == 0:
            return None
    if index < len(words):
        return None
    return lines


def _segment_for_box(
    field: str,
    text: str,
    *,
    font_size: float,
    line_index: int = 0,
    center: bool = False,
) -> OverlaySegment:
    box = FIELD_BOXES[field]
    x = box.x_for_line(line_index)
    max_width = box.width_for_line(line_index)
    width = _text_width(text, font_size)
    if center and width < max_width:
        x = x + (max_width - width) / 2.0
    return OverlaySegment(
        field=field,
        text=text,
        x=x,
        y=box.y_for_line(line_index),
        width=width,
        font_size=font_size,
        line_index=line_index,
    )


def _multiline_segments(field: str, text: str) -> list[OverlaySegment]:
    box = FIELD_BOXES[field]
    widths = [box.width_for_line(i) for i in range(box.max_lines)]
    lines, size = wrap_text_to_widths(text, widths, field=field)
    return [
        _segment_for_box(field, line, font_size=size, line_index=i)
        for i, line in enumerate(lines)
    ]


def plan_overlay(data: dict) -> OverlayPlan:
    """Validate capacity and return drawable overlay segments."""
    segments: list[OverlaySegment] = []

    fecha = data["fecha"]
    day, size = fit_single_line(f"{fecha.day:02d}", W_FECHA_DAY, field="fecha")
    segments.append(
        _segment_for_box("fecha_day", day, font_size=size, center=True)
    )
    month, size = fit_single_line(f"{fecha.month:02d}", W_FECHA_MONTH, field="fecha")
    segments.append(
        _segment_for_box("fecha_month", month, font_size=size, center=True)
    )
    year, size = fit_single_line(f"{fecha.year:04d}", W_FECHA_YEAR, field="fecha")
    segments.append(
        _segment_for_box("fecha_year", year, font_size=size, center=True)
    )

    name, size = fit_single_line(
        data["nombre_apellido"], W_NOMBRE, field="nombre_apellido"
    )
    segments.append(_segment_for_box("nombre_apellido", name, font_size=size))

    dni, size = fit_single_line(str(data["dni"]), W_DNI, field="dni")
    segments.append(_segment_for_box("dni", dni, font_size=size))

    edad, size = fit_single_line(str(data["edad"]), W_EDAD, field="edad")
    segments.append(_segment_for_box("edad", edad, font_size=size))

    segments.extend(_multiline_segments("diagnostico", data["diagnostico"]))
    segments.extend(_multiline_segments("prestacion", data["prestacion"]))

    freq, size = fit_single_line(
        data["frecuencia_semanal"], W_FREQ, field="frecuencia_semanal"
    )
    segments.append(_segment_for_box("frecuencia_semanal", freq, font_size=size))

    desde = data["periodo_desde"]
    hasta = data["periodo_hasta"]
    desde_first, _ = period_range_days(desde)
    _, hasta_last = period_range_days(hasta)

    desde_day, size = fit_single_line(
        f"{desde_first.day:02d}", W_DESDE_DAY, field="periodo_desde"
    )
    segments.append(
        _segment_for_box("periodo_desde_day", desde_day, font_size=size, center=True)
    )
    desde_month, size = fit_single_line(
        _MONTH_NAMES[desde.month - 1], W_DESDE_MONTH, field="periodo_desde"
    )
    segments.append(
        _segment_for_box(
            "periodo_desde_month", desde_month, font_size=size, center=True
        )
    )
    desde_year, size = fit_single_line(
        f"{desde.year:04d}", W_DESDE_YEAR, field="periodo_desde"
    )
    segments.append(
        _segment_for_box("periodo_desde_year", desde_year, font_size=size, center=True)
    )

    hasta_day, size = fit_single_line(
        f"{hasta_last.day:02d}", W_HASTA_DAY, field="periodo_hasta"
    )
    segments.append(
        _segment_for_box("periodo_hasta_day", hasta_day, font_size=size, center=True)
    )
    hasta_month, size = fit_single_line(
        _MONTH_NAMES[hasta.month - 1], W_HASTA_MONTH, field="periodo_hasta"
    )
    segments.append(
        _segment_for_box(
            "periodo_hasta_month", hasta_month, font_size=size, center=True
        )
    )
    hasta_year, size = fit_single_line(
        f"{hasta.year:04d}", W_HASTA_YEAR, field="periodo_hasta"
    )
    segments.append(
        _segment_for_box("periodo_hasta_year", hasta_year, font_size=size, center=True)
    )

    return OverlayPlan(segments=tuple(segments))


def build_overlay(data: dict, plan: OverlayPlan | None = None) -> BytesIO:
    overlay_plan = plan or plan_overlay(data)
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    c.setFillColor(VALUE_COLOR)
    for segment in overlay_plan.segments:
        c.setFont(FONT_NAME, segment.font_size)
        c.drawString(segment.x, segment.y, segment.text)
    c.save()
    buffer.seek(0)
    return buffer


def fill_prescription_pdf(data: dict, template_path: Path | None = None) -> bytes:
    template = Path(template_path) if template_path else get_pdf_template_path()
    if not template.is_file():
        raise FileNotFoundError(f"PDF template not found: {template}")

    plan = plan_overlay(data)
    overlay_buf = build_overlay(data, plan=plan)
    writer = PdfWriter(clone_from=str(template))
    overlay_reader = PdfReader(overlay_buf)
    writer.pages[0].merge_page(overlay_reader.pages[0])

    out = BytesIO()
    writer.write(out)
    return out.getvalue()
