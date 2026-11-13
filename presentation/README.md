# SolarWise DZ - the 5-minute pitch

Everything needed to present the solution in five minutes.

| File | What it is | Use it to |
|---|---|---|
| `SolarWise-DZ-pitch.pptx` | The slides for PowerPoint, Keynote, Google Slides or LibreOffice. The text is real text: it can be corrected or translated. The script is in the notes of each slide. | present with the presenter view, or edit |
| `SolarWise-DZ-pitch.pdf` | The same slides as a PDF. Looks the same on every computer. | present full screen, send, print |
| `SolarWise-DZ-pitch.html` | The same slides in one file for a browser. Works without a network. | rehearse: it has the script and a clock |
| `SPEAKER-SCRIPT.md` | What to say on each slide, with times, then the questions to expect and their answers. | learn the talk |
| `serve.py` | A small server that shows the slides in a browser from these files. | show them without copying files |

## The talk

11 slides for the five minutes, then 4 backup slides for the questions (rules, architecture, the ten
demonstration scenarios, limits).

| # | Slide | Seconds |
|---|---|---|
| 1 | Title | 15 |
| 2 | The problem: production is down 9 %, is it dust? | 35 |
| 3 | The solution: three questions, in order | 35 |
| 4 | Why: from expected to actual energy | 30 |
| 5 | The decision: ten gates | 35 |
| 6 | Six cases with the same drop, one cleaning order | 40 |
| 7 | Does cleaning pay? Same cost, opposite answers | 30 |
| 8 | Four rules the software never breaks | 25 |
| 9 | Where we are: a working application | 25 |
| 10 | Next steps, and what we ask for | 25 |
| 11 | Close | 5 |

## Presenting

- **PowerPoint**: open the `.pptx`, start the slide show. With a second screen, the presenter view shows the script.
- **PDF**: open it and switch to full screen (in most readers: `Ctrl+L`, or `F11` in a browser).
- **Browser**: open the `.html`. Arrow keys or a click move; `N` shows the script, `T` starts the 5-minute clock,
  `R` resets it, `F` is full screen.
- **From a server** (to show the slides on another device, or in a preview pane): `python3 presentation/serve.py`
  serves the slides at `http://localhost:8012/` and the three files next to them. It needs nothing but Python.
  Inside a pane of another page, click the slides once so that the keys reach them; if the pane refuses full
  screen, the slides say so and offer to open in their own tab.

For the pitch itself, use a file that is on your computer (`.pptx`, `.pdf` or `.html`), not a link to a server
that may be asleep or out of reach on the day.

The title slide carries no name: add yours in PowerPoint, or say it.

## What the figures are

Every figure about the solution comes from the application's own demonstration, which is **synthetic**: no
measurement from El Foulia or from any other plant is used, and the money amounts rest on illustrative prices. The
slides say so wherever such a figure appears.

Two figures come from outside, with their source on slide 2:

- the 8.4 % loss of power after eight weeks without cleaning, measured at Ouargla: Dida, Boughali, Bechki and
  Bouguettaia, *Output power loss of crystalline silicon photovoltaic modules due to dust accumulation in Saharan
  environment*, Renewable and Sustainable Energy Reviews 124 (2020), 109787;
- El Foulia (300 MWp, inaugurated on 26 October 2026) and the 15,000 MW planned for 2035: pv magazine France,
  28 October 2026.

The test counts on slides 9 and 13 (1,135 and 122) are the results of the test suites on the day the slides were
built. Run the suites again and correct the slides if you present a later version of the code.

## Changing the slides

Small changes (a word, a name, a translation) can be made directly in PowerPoint.

To change the design, edit `src/deck.html` and `src/deck.css`, then build the files again:

```sh
# once: the tools
(cd frontend/e2e && npm install)                    # puppeteer-core
pip install -r presentation/src/requirements.txt    # python-pptx, Pillow

# every time
export CHROMIUM_PATH=/path/to/chromium-or-chrome
node presentation/src/build.cjs                     # PDF, single-file HTML, speaker script, pictures
python presentation/src/build_pptx.py               # PowerPoint file
```

`build.cjs` stops with a list of problems when a text leaves its box, overlaps another one or uses a character
the font does not have. The script of the talk is the `<aside class="notes">` of each slide in `src/deck.html`;
`src/script-extras.md` holds the questions and answers.

How the PowerPoint file is made: everything that is drawn (cards, charts, screenshots) becomes the background
picture of the slide, and everything marked `data-tx` in `deck.html` becomes a text box in Arial placed where the
browser placed it. The slides are designed with Arimo, a free font with the same metrics as Arial.

Optional check of the PowerPoint file (`src/check_pptx.mjs`, then `src/check_pptx.py`): LibreOffice renders the
file and every line of text is compared with the PDF: same words on each line, same size, weight and colour, and
its position. It needs `npm install @matbee/libreoffice-converter` and `pip install pymupdf`.

Other sources: `src/capture.cjs` takes the screenshots of the application from a demonstration server (run it with
`frontend/e2e/run.sh "$PWD/presentation/src/capture.cjs"`), `src/make_icons.mjs` writes the icon sprite.

## Licences of what the slides embed

- Arimo font: SIL Open Font License 1.1 (`src/fonts/OFL.txt`).
- Icons: Lucide, ISC licence.
