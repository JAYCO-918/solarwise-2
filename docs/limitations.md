# Limitations

What SolarWise DZ does not do, what it assumes, and what has not been verified. Read this before relying on a
result or presenting the project.

## 1. No real plant data have ever been analysed

- Every dataset in the repository is synthetic. The scenario generator produces plausible series and injects one
  known effect per scenario; the engine is then shown to find what was injected. This demonstrates that the
  logic behaves as designed. It does not demonstrate that the method works on a real plant.
- The reference case uses the name, location and nominal capacity of El Foulia, which are public. Every
  technical parameter - AC rating, tilt, temperature coefficient, system losses, block layout - is an
  illustrative assumption. Nothing here describes how that plant is built or how it operates, and the project
  has no relationship with its owner or operator.
- Real telemetry is messier than a generator: drifting sensors, clock errors, partial outages, meter
  substitutions, changing baselines. The validation rules were written for such problems but have met them only
  in tests.

A pilot on one plant's measured data is the necessary next step, and until then the results are simulations.

## 2. The thresholds are engineering judgement

The sixteen thresholds (materiality 3 %, coverage factor 2, soiling credibility floor 2 %, assessment window of
7 days, and the others in [decision-rules.md](decision-rules.md)) are reasoned defaults. None has been calibrated
on a plant, a climate or a module technology. They can be changed per analysis and every analysis records the
values it used, but the right values for a given plant are not known.

## 3. What the method cannot see

- **Without a soiling measurement there is no cleaning recommendation.** This is deliberate - a gap is not
  proof of soiling - but it means a plant with no soiling station, no reference device and no string tests will
  receive `INVESTIGATE` or `MONITOR`, never `CLEAN_NOW`. The software does not estimate soiling from production
  or from weather.
- **A soiling station measures one place.** The method takes the measurement as representative of the plant.
  Uneven soiling over a 300 MWp site is not modelled.
- **Shading and curtailment signatures need sub-daily data.** With daily totals those hypotheses cannot be
  evaluated and are reported as such.
- **Signatures are indirect.** A slow decline, a level shift or a morning loss make a hypothesis plausible; they
  do not identify a cause.
- **The device comparison cannot see a problem that affects every device equally.**
- **The engineering baseline is a simple model**: one lumped loss factor, a single cell-temperature estimate, an
  isotropic-sky transposition for fixed arrays only. Tracking systems need an in-plane irradiation channel or a
  supplied baseline. Spectral effects, bifacial gain, clipping detail and snow are not modelled.
- **Daily data lose information**: the irradiance driving the temperature models is then a proxy for clear days.
- **Uncertainty** is combined from the declared standard uncertainties assuming independence. When none is
  declared, the significance test cannot be made. No uncertainty is attached to the diagnosis itself: support
  levels are ordinal, on purpose.

## 4. Recoverable energy and economics are projections

- The cleaning effectiveness and the time the benefit lasts are supplied by the user. The result is only as good
  as those two assumptions; the software gives a low-to-high range, not a forecast of the weather.
- Soiled and cleaned arrays are assumed to accumulate dust at the same rate after the cleaning.
- No price is built in. The amounts of the demonstration (5 DZD/kWh, 4.52 M DZD per cleaning) are illustrative
  and are not market prices, tariffs or contractual values.
- The Algerian regulatory texts listed as economic references are listed by title only. Their amounts were not
  verified against the official texts and are deliberately left empty (`PENDING_VERIFICATION`).
- Water availability, the logistics of a cleaning campaign and the wear of modules are outside the calculation.

## 5. Projections are not validated

The three projections of the performance index (persistence, moving average, robust trend) are reference
methods. Their back-test runs on the dataset being analysed. They are labelled unvalidated, never enter a
decision, and are not soiling forecasts.

## 6. The platform

- **Files only.** Data arrive as CSV or JSON uploads. There is no live connection to a SCADA system, no
  scheduled import and no alerting. Excel files are not read.
- **Reading a file is a proposal.** Columns are recognised from their headers with a fixed vocabulary, in English
  and French. A header nobody could read is left for the uploader to assign. A recognised column can still be the
  wrong one - a horizontal irradiance taken for an in-plane one when the header does not say: that is why
  ambiguous headers are flagged, and why nothing is imported before the uploader has seen the mapping.
- **One column for the date and the time.** A file with separate date and time columns is pointed out, not merged.
  Counter readings are pointed out, not converted to energy per interval.
- **Irradiance in W/m² is taken as the mean over each interval.** Spot values or daylight-only means give a wrong
  irradiation; the platform cannot tell, and says so each time.
- **Events are read with a fixed vocabulary.** An alarm text it does not know is kept as "other" and does not
  enter the diagnosis. Whether an alarm that stopped being reported was actually resolved is not known: it is
  recorded as not confirmed closed.
- **Declarations are trusted.** The platform cannot verify that a channel declared `MEASURED` was measured. It
  records who declared it.
- **One language.** The interface, the reports and the slides are in English. There is no French or Arabic
  version.
- **Accounts**: sign-up does not verify the e-mail address (the application sends no mail); no password change
  or reset, no multi-factor authentication.
- **Scale**: designed for one instance. The sign-in throttling lives in the memory of the process. Analyses run
  inside the request, and no load test was made.
- **The language model was never run against a real provider.** Everything that uses it - the diagnostic
  analysis, the operational report, the review of an uploaded file, the rewording of the explanation - was tested
  against a stand-in that speaks the OpenAI chat-completions protocol and gives scripted answers. The protocol,
  the handling of failures, the checks, the storage and the display are verified that way; how well a given model
  writes, how often its answers pass the checks, what it costs and how long it takes are not. See [ai.md](ai.md).
- **The checks on a model's text are patterns.** They catch the overreaches they were written for - soiling
  stated as a fact, an invented figure, another decision, a claimed validation - and they are in English. They do
  not verify that every sentence is true. This is why every fact that matters is copied from the engine by the
  server and each section of the page says who wrote it.
- **No independent review** of the code, the method or the security has been made.

## 7. What could not be verified where the project was built

The project was built and tested in a Linux sandbox without Docker, without Microsoft Office and with restricted
network access.

| Item | State |
|---|---|
| `docker build`, `docker compose up` | **Never run.** The same installation steps were verified without Docker, on SQLite and on PostgreSQL 16 ([deployment.md](deployment.md)) |
| Windows and macOS | Not tested. The Windows commands in the README are the equivalent of the tested Linux ones |
| PVGIS and NASA POWER | The services could not be reached. Their clients are tested against simulated answers only; a live call has never been made |
| A language-model provider | **Never called**: none could be reached, and no key was available. The layer is tested against a stand-in on a local port that speaks the OpenAI chat-completions protocol and gives scripted answers - over real HTTP, including time-outs, rate limits and refused keys. The Anthropic protocol is tested against simulated answers only |
| The PowerPoint file | Checked by rendering it with LibreOffice and comparing every line of text with the PDF. Never opened in PowerPoint, Keynote or Google Slides |
| Browsers | The browser checks run in Chromium only |
| The public preview link | Opened by a visitor successfully, as the server log shows; it cannot be opened from inside the sandbox |

## 8. What it is, then

A complete, tested demonstrator of a method: a production gap is examined before it is blamed on dust, every
figure says where it comes from, and a cleaning is recommended only when the evidence and the economics both
support it. Whether that method is useful on a real plant is what a pilot would establish.
