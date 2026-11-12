"""Compares the text of the PowerPoint file, as LibreOffice renders it, with the reference PDF made by the browser.

For every line of editable text it reports whether the same line exists in the reference (same words: the lines
break at the same places) and how far its baseline is from the reference, in pixels of the 1280 x 720 slide.

    node presentation/src/check_pptx.mjs && python presentation/src/check_pptx.py

Needs ``pymupdf``.  LibreOffice is not PowerPoint: this proves that the file is laid out as designed with fonts that
have the metrics of Arial, not that every version of PowerPoint draws it identically.
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

import pymupdf

OUT = Path(__file__).resolve().parents[1]
WORK = OUT / ".work"
PX_PER_PT = 96 / 72
#: A line is "in place" when its baseline is within this distance of the reference, in pixels.
TOLERANCE = 2.0


def lines_of(page: pymupdf.Page) -> list[tuple[str, float, float, float, bool, int]]:
    """(text, x of the first glyph, y of the baseline, font size, bold, colour), lengths in pixels."""
    found = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = " ".join("".join(s["text"] for s in spans).split())
            x, y = spans[0]["origin"]
            first = spans[0]
            found.append((text, x * PX_PER_PT, y * PX_PER_PT, first["size"] * PX_PER_PT, "Bold" in first["font"], first["color"]))
    return found


def main() -> int:
    reference = pymupdf.open(OUT / "SolarWise-DZ-pitch.pdf")
    rendered = pymupdf.open(WORK / "pptx-as-rendered.pdf")
    if len(reference) != len(rendered):
        print(f"FAIL: {len(rendered)} slides rendered, {len(reference)} in the reference")
        return 1
    fonts = sorted({f[3].split("+")[-1] for i in range(len(rendered)) for f in rendered.get_page_fonts(i)})
    print(f"{len(rendered)} slides; fonts used by LibreOffice: {', '.join(fonts)}")

    dxs: list[float] = []
    dys: list[float] = []
    problems: list[str] = []
    total = 0
    for index in range(len(rendered)):
        ref = lines_of(reference[index])
        for text, x, y, size, bold, colour in lines_of(rendered[index]):
            total += 1
            # The same line, or a line that goes on with something drawn into the background (a mark, a label).
            same = [r for r in ref if r[0] == text] or [r for r in ref if r[0].startswith(text)]
            if not same:
                problems.append(f"slide {index + 1}: no such line in the reference (different line break?): “{text[:70]}”")
                continue
            nearest = min(same, key=lambda r: abs(r[1] - x) + abs(r[2] - y))
            dx, dy = x - nearest[1], y - nearest[2]
            dxs.append(dx)
            dys.append(dy)
            if abs(size - nearest[3]) > 0.3 or bold != nearest[4] or colour != nearest[5]:
                problems.append(
                    f"slide {index + 1}: “{text[:50]}” is drawn at {size:.1f} px, bold {bold}, colour {colour:06X}; "
                    f"the reference has {nearest[3]:.1f} px, bold {nearest[4]}, colour {nearest[5]:06X}"
                )
            if abs(dx) > TOLERANCE or abs(dy) > TOLERANCE:
                problems.append(f"slide {index + 1}: “{text[:50]}” is off by {dx:+.1f} px across, {dy:+.1f} px down (font {size:.0f} px)")
    print(f"{total} lines of editable text; {len(dxs)} found word for word in the reference")
    if dxs:
        print(f"across: median {statistics.median(dxs):+.2f} px, worst {max(dxs, key=abs):+.2f} px")
        print(f"down:   median {statistics.median(dys):+.2f} px, worst {max(dys, key=abs):+.2f} px")
    for problem in problems:
        print("PROBLEM", problem)
    if not problems:
        print(f"every line has the words, the size, the weight and the colour of the reference, within {TOLERANCE:g} px of its place")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
