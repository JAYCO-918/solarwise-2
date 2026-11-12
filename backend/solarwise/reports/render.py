"""Renderers of a report document."""

from __future__ import annotations

import csv
import io
import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from jinja2 import Environment, PackageLoader, select_autoescape
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from solarwise.core.pipeline import AnalysisResult
from solarwise.reports.document import ReportDocument, ReportMeta, TextBlock

_DECISION_COLOURS = {"CLEAN_NOW": "#0b6b4f", "INVESTIGATE": "#9a5a00", "MONITOR": "#27507a"}
_FONT_CANDIDATES = (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
)


@lru_cache(maxsize=1)
def _environment() -> Environment:
    return Environment(
        loader=PackageLoader("solarwise.reports", "templates"),
        autoescape=select_autoescape(enabled_extensions=("html",), default=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_html(document: ReportDocument) -> str:
    """Self-contained HTML (inline style sheet, no script, no external resource)."""
    return _environment().get_template("report.html").render(doc=document)


# --------------------------------------------------------------------------- PDF


@lru_cache(maxsize=1)
def _fonts() -> tuple[str, str, bool]:
    """(regular, bold, unicode?) - a Unicode font when the system has one, else the PDF base fonts."""
    for regular, bold in _FONT_CANDIDATES:
        if Path(regular).is_file() and Path(bold).is_file():
            try:
                pdfmetrics.registerFont(TTFont("SolarWise", regular))
                pdfmetrics.registerFont(TTFont("SolarWise-Bold", bold))
            except Exception:  # noqa: S112 - an unreadable font file simply means the fallback is used
                continue
            return "SolarWise", "SolarWise-Bold", True
    return "Helvetica", "Helvetica-Bold", False


def _text(value: str) -> str:
    """Escape for reportlab's paragraph mark-up; without a Unicode font, keep to Latin-1."""
    _, _, unicode_font = _fonts()
    if not unicode_font:
        value = value.encode("latin-1", "replace").decode("latin-1")
    return escape(value)


def render_pdf(document: ReportDocument) -> bytes:
    regular, bold, _ = _fonts()
    sheet = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=sheet["BodyText"], fontName=regular, fontSize=9, leading=12.5, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10.5, textColor=colors.HexColor("#5b6876"))
    cell = ParagraphStyle("cell", parent=body, fontSize=8, leading=10.5)
    head = ParagraphStyle("head", parent=cell, fontName=bold, textColor=colors.HexColor("#5b6876"))
    h1 = ParagraphStyle("h1", parent=body, fontName=bold, fontSize=16, leading=20, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=body, fontName=bold, fontSize=11.5, leading=15, spaceBefore=12, spaceAfter=5)
    h3 = ParagraphStyle("h3", parent=body, fontName=bold, fontSize=9.5, leading=13, spaceBefore=7, spaceAfter=2)
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=11, bulletIndent=2)
    line = colors.HexColor("#d9dee5")

    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"{document.title} - {document.subtitle}", author="SolarWise DZ",
        subject="SIMULATED DECISION" if document.simulated else "Assessment",
    )
    width = A4[0] - 36 * mm
    flow: list[Any] = [Paragraph(_text(document.title), h1), Paragraph(_text(document.subtitle), small), Spacer(1, 6)]

    banner_colour = colors.HexColor("#7a1f1f") if document.simulated else colors.HexColor("#16202b")
    banner = Table([[Paragraph(f"<b>{_text(document.banner)}</b>", ParagraphStyle("banner", parent=body, textColor=banner_colour))]], colWidths=[width])
    banner.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, banner_colour), ("LINEBEFORE", (0, 0), (0, -1), 4, banner_colour),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fdf3f3") if document.simulated else colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    flow += [banner, Spacer(1, 8)]

    accent = colors.HexColor(_DECISION_COLOURS.get(document.decision, "#27507a"))
    label = "SIMULATED DECISION" if document.simulated else "DECISION"
    decision = Table(
        [[[
            Paragraph(_text(label), ParagraphStyle("tag", parent=small, fontName=bold)),
            Paragraph(_text(document.decision_label), ParagraphStyle("dl", parent=h1, fontSize=18, leading=23)),
            Paragraph(_text(document.headline), body),
            Paragraph(_text(document.authorization_note), small),
        ]]],
        colWidths=[width],
    )
    decision.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, line), ("LINEBEFORE", (0, 0), (0, -1), 5, accent),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    flow.append(decision)

    def pairs(title: str, rows: list[tuple[str, str]]) -> None:
        flow.append(Paragraph(_text(title), h2))
        table = Table(
            [[Paragraph(_text(k), small), Paragraph(_text(v), cell)] for k, v in rows], colWidths=[width * 0.32, width * 0.68]
        )
        table.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, line), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ]))
        flow.append(table)

    def block(item: TextBlock, style: ParagraphStyle) -> None:
        flow.append(Paragraph(_text(item.title), style))
        for paragraph in item.paragraphs:
            flow.append(Paragraph(_text(paragraph), body))
        for entry in item.bullets:
            flow.append(Paragraph(_text(entry), bullet, bulletText="\u2022" if _fonts()[2] else "-"))

    pairs("Subject of the assessment", document.facts)
    pairs("Key figures", document.key_figures)
    for item in document.blocks:
        block(item, h2)
    for spec in document.tables:
        flow.append(Paragraph(_text(spec.title), h2))
        widths = spec.widths or [1.0 / len(spec.columns)] * len(spec.columns)
        data = [[Paragraph(_text(c), head) for c in spec.columns]]
        data += [[Paragraph(_text(value), cell) for value in row] for row in spec.rows]
        table = Table(data, colWidths=[width * w for w in widths], repeatRows=1)
        table.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#8a96a3")), ("LINEBELOW", (0, 1), (-1, -1), 0.4, line),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(table)
        if spec.note:
            flow += [Spacer(1, 3), Paragraph(_text(spec.note), small)]
    flow.append(Paragraph("Diagnostic hypotheses", h2))
    flow.append(Paragraph(
        "Each hypothesis is rated by the strength of the evidence for it. No probability is stated: the data do not support one.",
        small,
    ))
    for item in document.hypotheses:
        block(item, h3)
    flow.append(Paragraph("Explanation", h2))
    for item in document.explanation:
        block(item, h3)
    flow.append(Paragraph("Statements that apply to this document", h2))
    for entry in document.disclaimers:
        flow.append(Paragraph(_text(entry), bullet, bulletText="\u2022" if _fonts()[2] else "-"))
    flow += [Spacer(1, 10), Paragraph(_text(document.footer), small)]

    marking = "SIMULATED DECISION - NOT AN OPERATIONAL INSTRUCTION" if document.simulated else "SolarWise DZ"

    def decorate(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(regular, 7.5)
        canvas.setFillColor(colors.HexColor("#7a1f1f") if document.simulated else colors.HexColor("#5b6876"))
        canvas.drawString(18 * mm, 10 * mm, marking)
        canvas.setFillColor(colors.HexColor("#5b6876"))
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    pdf.build(flow, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


# --------------------------------------------------------------------------- CSV and JSON


def render_csv(result: AnalysisResult, meta: ReportMeta) -> str:
    """Daily figures.  The provenance travels in the rows themselves, not only in the preamble."""
    out = io.StringIO()
    rec = result.recommendation
    preamble = [
        "SolarWise DZ daily export",
        f"plant: {result.plant.name}",
        f"dataset: {meta.dataset_name or result.dataset_name or ''}",
        f"period: {result.period_start.isoformat()} to {result.period_end.isoformat()} ({result.timezone})",
        f"decision: {rec.decision.value} (rule {rec.rule}); simulated: {str(rec.simulated).lower()}; "
        f"operational authorisation: {str(rec.operational_authorization).lower()}",
        f"engine: {result.engine_version}; analysis: {meta.analysis_id if meta.analysis_id is not None else 'not stored'}",
        "missing values are empty cells: they are not zeros",
        *result.disclaimers,
    ]
    if rec.simulated:
        preamble.insert(1, "SIMULATED DECISION - demonstration only, not an operational instruction")
    writer = csv.writer(out, lineterminator="\n")
    for item in preamble:
        # One quoted cell per line, starting with '#': free text (plant and dataset names are user input) can
        # neither spill into further cells nor be read as a formula by a spreadsheet.
        writer.writerow(["# " + " ".join(item.split())])
    writer.writerow([
        "day", "expected_energy_kwh", "actual_energy_kwh", "gap_kwh", "gap_pct", "performance_index_pct",
        "data_coverage", "status", "weather_adjusted_expected_kwh", "irradiance_loss_kwh", "temperature_loss_kwh",
        "degradation_loss_kwh", "downtime_loss_kwh", "equipment_loss_kwh", "curtailment_loss_kwh",
        "soiling_loss_kwh", "residual_kwh", "soiling_ratio", "availability", "cell_temp_c",
        "expected_provenance", "actual_provenance", "decision_simulated",
    ])
    attribution = {d.day: d for d in result.attribution.daily}

    def cell(value: float | None, digits: int = 3) -> str:
        return "" if value is None else f"{value:.{digits}f}"

    expected_label = result.gap.expected.tag.label
    actual_label = result.gap.actual.tag.label
    for day in result.gap.daily:
        a = attribution.get(day.day)
        writer.writerow([
            day.day.isoformat(), cell(day.expected_kwh), cell(day.actual_kwh), cell(day.gap_kwh),
            cell(day.relative_gap_pct), cell(day.performance_index), cell(day.coverage), day.status,
            cell(a.weather_adjusted_expected_kwh) if a else "", cell(a.irradiance_kwh) if a else "",
            cell(a.temperature_kwh) if a else "", cell(a.degradation_kwh) if a else "",
            cell(a.downtime_kwh) if a else "", cell(a.equipment_kwh) if a else "",
            cell(a.curtailment_kwh) if a else "", cell(a.soiling_kwh) if a else "", cell(a.residual_kwh) if a else "",
            cell(a.soiling_ratio, 4) if a else "", cell(a.availability, 4) if a else "", cell(a.cell_temp_c, 2) if a else "",
            expected_label, actual_label, str(rec.simulated).lower(),
        ])
    return out.getvalue()


def render_json(result: AnalysisResult, meta: ReportMeta) -> str:
    rec = result.recommendation
    envelope = {
        "report": {
            "format": "solarwise-analysis",
            "format_version": 1,
            "analysis_id": meta.analysis_id,
            "dataset_name": meta.dataset_name or result.dataset_name,
            "dataset_sha256": meta.dataset_sha256,
            "issued_at": meta.created_at.isoformat(),
            "simulated": rec.simulated,
            "operational_authorization": rec.operational_authorization,
            "marking": "SIMULATED DECISION - not an operational instruction" if rec.simulated else None,
            "disclaimers": result.disclaimers,
        },
        "result": result.model_dump(mode="json"),
    }
    return json.dumps(envelope, indent=2, ensure_ascii=False, allow_nan=False)
