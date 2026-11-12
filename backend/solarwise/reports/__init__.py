"""Reports of one analysis: HTML, PDF, CSV and JSON.

All four are produced from the stored result of the analysis - never from a
fresh computation - so a report always says what the recommendation said when
it was issued.  Every format carries the provenance labels, the assumptions and
the "simulated decision" marking.
"""

from solarwise.reports.document import ReportDocument, ReportMeta, build_document
from solarwise.reports.render import render_csv, render_html, render_json, render_pdf

__all__ = [
    "ReportDocument",
    "ReportMeta",
    "build_document",
    "render_csv",
    "render_html",
    "render_json",
    "render_pdf",
]
