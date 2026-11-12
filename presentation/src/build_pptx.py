"""Builds the PowerPoint file from what ``build.cjs`` wrote in ``presentation/.work``.

Each slide is a background picture (everything that is drawn) with real text boxes on top (everything that is
written), so that the text can be edited, corrected or translated in PowerPoint.  The speaker's script goes into
the notes of each slide.

    python presentation/src/build_pptx.py

Needs ``python-pptx`` and ``Pillow`` (``pip install -r presentation/src/requirements.txt``).
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls, qn
from pptx.util import Emu, Pt

OUT = Path(__file__).resolve().parents[1]
WORK = OUT / ".work"

#: One CSS pixel of the 1280 x 720 slide, in English Metric Units (96 px per inch, 914 400 EMU per inch).
PX = 9525
#: The slides are designed with Arimo, which has the metrics of Arial; PowerPoint uses the Arial of the computer.
FONT = "Arial"
#: With a line spacing given as an exact height, the first baseline is this share of the font size above the bottom
#: of the first line (measured on LibreOffice: 0.200 for every size and spacing tried; the descent of Arial is 0.212).
BASELINE_ABOVE_LINE_BOTTOM = 0.2
ALIGN = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT, "justify": PP_ALIGN.JUSTIFY}


def box_top(box: dict) -> float:
    """Top of the text box, in pixels, for its first baseline to fall where the browser put it.

    The browser centres the text in its line: half of the extra height above, half below.  An office suite puts the
    whole extra height above.  So the box is placed from the baseline that the browser measured, not from its top.
    """
    return box["baseline"] - (box["lineHeight"] - BASELINE_ABOVE_LINE_BOTTOM * box["fontSize"])


def box_width(box: dict) -> float:
    """A width at which the lines break exactly where they break in the browser, with the largest margin both ways."""
    if not box["wrap"]:
        return box["w"]
    if box["most"] is None:
        # One line, or forced breaks only: any width from the widest line up.
        return max(box["w"], box["least"]) + 6.0
    return (box["least"] + box["most"]) / 2


def plate_bytes(path: Path) -> tuple[bytes, str]:
    """The background picture: the PNG as drawn, or a high-quality JPEG when that is much smaller."""
    png = path.read_bytes()
    buffer = io.BytesIO()
    Image.open(path).convert("RGB").save(buffer, "JPEG", quality=92, subsampling=0, optimize=True)
    jpeg = buffer.getvalue()
    return (jpeg, "jpg") if len(jpeg) < 0.7 * len(png) else (png, "png")


def set_background(slide, picture: bytes) -> None:
    """Use the picture as the background of the slide (not as a shape: it cannot be selected or moved by accident)."""
    _, r_id = slide.part.get_or_add_image_part(io.BytesIO(picture))
    background = parse_xml(
        f"<p:bg {nsdecls('p', 'a', 'r')}><p:bgPr>"
        f'<a:blipFill dpi="0" rotWithShape="1"><a:blip r:embed="{r_id}"/><a:srcRect/><a:stretch><a:fillRect/></a:stretch></a:blipFill>'
        "<a:effectLst/></p:bgPr></p:bg>"
    )
    c_sld = slide.element.find(qn("p:cSld"))
    existing = c_sld.find(qn("p:bg"))
    if existing is not None:
        c_sld.remove(existing)
    c_sld.insert(0, background)


def add_text(slide, box: dict, number: int) -> None:
    line_px = box["lineHeight"]
    x, y, h = box["x"], box_top(box), box["h"]
    w = box_width(box)
    if box["align"] == "center":
        x += (box["w"] - w) / 2
    elif box["align"] == "right":
        x += box["w"] - w
    shape = slide.shapes.add_textbox(Emu(round(x * PX)), Emu(round(y * PX)), Emu(round(w * PX)), Emu(round(h * PX)))
    shape.name = f"Text {number}"
    frame = shape.text_frame
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    frame.word_wrap = bool(box["wrap"])
    frame.auto_size = MSO_AUTO_SIZE.NONE
    frame.vertical_anchor = MSO_ANCHOR.TOP
    paragraph = frame.paragraphs[0]
    paragraph.alignment = ALIGN.get(box["align"], PP_ALIGN.LEFT)
    paragraph.line_spacing = Pt(round(line_px * 75) / 100)
    paragraph.space_before = Pt(0)
    paragraph.space_after = Pt(0)
    for item in box["runs"]:
        if item.get("br"):
            paragraph.add_line_break()
            continue
        run = paragraph.add_run()
        run.text = item["text"]
        font = run.font
        font.name = FONT
        font.size = Pt(round(item["size"] * 75) / 100)  # hundredths of a point, rounded: 13.3333 px is 10 pt
        font.bold = bool(item["bold"])
        font.italic = bool(item["italic"])
        font.color.rgb = RGBColor.from_string(item["color"])
        properties = run._r.get_or_add_rPr()
        # No pair kerning, as in the browser: both then use the plain advance widths of the font.
        properties.set("kern", "0")
        if item["spacing"]:
            properties.set("spc", str(round(item["spacing"] * 75)))
        properties.set("lang", "en-GB")


def notes_text(slide: dict, main: list[dict]) -> str:
    lines: list[str] = []
    if slide["backup"]:
        lines.append(f"BACKUP SLIDE - {slide['name']} (not part of the five minutes)")
    else:
        start = sum(s["seconds"] for s in main if s["index"] < slide["index"])
        end = start + slide["seconds"]
        lines.append(
            f"Slide {slide['index'] + 1} of {len(main)} - {slide['name']} - {slide['seconds']} s "
            f"(from {start // 60}:{start % 60:02d} to {end // 60}:{end % 60:02d})"
        )
    for note in slide["notes"]:
        lines.append("")
        lines.append(f"[{note['text']}]" if note["cue"] else note["text"])
    return "\n".join(lines)


def build() -> Path:
    deck = json.loads((WORK / "deck.json").read_text(encoding="utf-8"))
    slides = deck["slides"]
    main = [s for s in slides if not s["backup"]]

    presentation = Presentation()
    presentation.slide_width = Emu(1280 * PX)
    presentation.slide_height = Emu(720 * PX)
    properties = presentation.core_properties
    properties.title = "SolarWise DZ - 5-minute pitch"
    properties.subject = "Decision support for the cleaning of photovoltaic plants"
    properties.author = "SolarWise DZ"
    properties.last_modified_by = "SolarWise DZ"
    properties.keywords = "photovoltaic, soiling, cleaning, decision support, Algeria"
    properties.comments = "Demonstration figures are synthetic. Built from presentation/src/deck.html."

    blank = presentation.slide_layouts[6]
    total_boxes = 0
    for data in slides:
        slide = presentation.slides.add_slide(blank)
        picture, _ = plate_bytes(WORK / f"plate-{data['index'] + 1:02d}.png")
        set_background(slide, picture)
        for number, box in enumerate(data["boxes"], start=1):
            add_text(slide, box, number)
        total_boxes += len(data["boxes"])
        slide.notes_slide.notes_text_frame.text = notes_text(data, main)

    target = OUT / f"{deck['name']}.pptx"
    presentation.save(str(target))
    print(f"written: {target.name} ({target.stat().st_size / 1e6:.1f} MB, {len(slides)} slides, {total_boxes} editable text boxes)")
    return target


if __name__ == "__main__":
    if not (WORK / "deck.json").is_file():
        sys.exit("run `node presentation/src/build.cjs` first: presentation/.work/deck.json is missing")
    build()
