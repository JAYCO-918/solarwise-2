# Demonstration scenarios

Ten scenarios show how the engine behaves on a known ground truth. **Every value is synthetic**: computed by the
scenario generator (`backend/solarwise/demo`) from a seeded pseudo-random sequence (seed 20260607). None was
measured at El Foulia or at any other plant, and none describes how that plant operates. Every decision below is
a *simulated* decision and authorises nothing.

## The setting

| | |
|---|---|
| Plant | "El Foulia reference case (synthetic data)": 300 MWp DC (public nominal capacity), 250 MW AC, fixed tilt 30°, 20 inverter blocks of 15 MWp - all technical parameters are illustrative assumptions |
| Daily scenarios | 60 days, 1 May to 29 June 2026 |
| Hourly scenarios (5 and 6) | 21 days, 9 to 29 June 2026 |
| Assessment window | The last 7 days: 23 to 29 June 2026 |
| Declared uncertainties | Baseline 2 %, meter 0.5 %: combined 2.05 %, so a gap must exceed 4.1 % to be distinguishable |
| Cleaning assumptions | Effectiveness 90 % (80 to 98 %); benefit horizon 30 days (21 to 45), except scenario 10: 3 days (2 to 5) |
| Economic assumptions | Energy valued at 5 DZD/kWh; one cleaning costs 4.52 M DZD ± 20 % (water 1,500 m³ at 80 DZD, labour 6,000 h at 400 DZD, equipment 1.5 M, other 0.5 M). Illustrative - not market prices |

## The ten scenarios

Gap = shortfall of actual against expected energy in the assessment window.

| # | Scenario | What was injected | Gap | Gates passed | Decision | Rule |
|---|---|---|---|---|---|---|
| 1 | Normal operation | Nothing: array near clean, availability 99.8 % | 0.5 % | 5 of 10 | `MONITOR` | R6 |
| 2 | Confirmed soiling | Soiling accumulating at 0.15 % per day since a cleaning; a soiling station and a clean-reference string test agree | 8.6 % | 10 of 10 | `CLEAN_NOW` | R3 |
| 3 | Temperature effect | The baseline is rated at 25 °C and ignores operating temperature | 8.9 % | 6 of 10 | `MONITOR` | R6 |
| 4 | Inverter fault | Blocks BLK-07 and BLK-13 (10 % of capacity) out of service from day 45 | 10.6 % | 5 of 10 | `INVESTIGATE` | R1 |
| 5 | Morning shading | 45 % of production lost during the first third of every day | 9.2 % | 5 of 10 | `INVESTIGATE` | R4 |
| 6 | Grid curtailment | Output limited to 55 % of the AC rating between 10:00 and 16:00 on 8 days; the withheld energy is logged | 10.1 % | 6 of 10 | `MONITOR` | R6 |
| 7 | Missing data | Production telemetry missing on 10 days, 4 of them in the last 7 | 6.5 % | 4 of 10 | `INVESTIGATE` | R0 |
| 8 | Conflicting evidence | The array soils, but the soiling station keeps reporting "clean"; an inspection reports heavy soiling | 8.6 % | 4 of 10 | `INVESTIGATE` | R2 |
| 9 | Synthetic data with no evidence role | The numbers of scenario 2, declared plainly synthetic | 8.6 % | 4 of 10 | `INVESTIGATE` | R0 |
| 10 | Unprofitable cleaning | Soiling at 0.095 % per day, measured; natural cleaning expected within 3 days | 5.8 % | 9 of 10 | `MONITOR` | R6 |

Six scenarios (2, 3, 5, 6, 8, 9) show a drop between 8.6 and 10.1 %. Only one of them ends in a cleaning order.
That is the point of the demonstration: the size of a drop does not tell its cause.

## What each scenario shows

**1 - Normal operation.** Production follows the baseline. The system must be able to say that nothing calls
for action: "production is in line with the baseline".

**2 - Confirmed soiling.** The one case in which a cleaning is justified. Over the window, expected 11.55 GWh,
actual 10.56 GWh. The soiling station measures a loss of 8.5 %; once the other factors are removed, 8.4 % is left
for soiling to explain; 0.1 % stays unexplained. Recoverable over 30 days: 3,784 MWh (2,078 to 6,907).

| Case | Net benefit |
|---|---|
| Conservative (low energy, high cost) | +4,965,999 DZD |
| Base | +14,401,568 DZD (18.9 M recovered, 4.52 M spent) |
| Optimistic | +30,920,706 DZD |

All ten gates pass: `CLEAN_NOW`, simulated.

**3 - Temperature effect.** A large gap against a baseline that ignores heat. Operating temperature above the
baseline's reference explains 91 % of it. This is an expected physical effect, not a fault, and cleaning would
not recover it: "the loss is explained by a cause that cleaning does not address".

**4 - Inverter fault.** Two blocks stop producing. The device-to-fleet comparison and the fault records point at
them. While a technical issue is open, its losses cannot be separated reliably from soiling: the system asks for
a repair, not a cleaning. Next actions: review the inverter alarm logs, check the DC side of the affected blocks.

**5 - Morning shading.** Hourly data. Losses confined to the morning, every day, while midday is unaffected -
a pattern that daily totals cannot show. No factor can be credibly quantified, so 8.7 % stays unexplained:
"a production gap alone does not prove soiling". Shading and "unclassified" remain plausible side by side; the
system asks for a site inspection at the affected time of day.

**6 - Grid curtailment.** Hourly data. Output is capped on instruction and the withheld energy is logged. The
gap is fully explained; there is nothing to clean.

**7 - Missing data.** Completeness is 78 % over the period and 43 % in the window, against a minimum of 90 %.
The system does not fill the holes or guess: it asks for the data. A soiling loss is present in the underlying
series, but no soiling measurement is supplied - and none is inferred.

**8 - Conflicting evidence.** The soiling station reads 1 % (its "clean" reference cell is itself dirty), an
inspection reports heavy soiling, and production is 8.6 % short. The sources contradict each other and the system
does not pick one. Next action: check the soiling sensor and run a clean-reference test.

**9 - Synthetic data with no evidence role.** Numerically identical to scenario 2. But the data are declared
plainly synthetic, without stating which evidence class they stand in for. The system refuses to draw any
cleaning conclusion: "only measured production can support a cleaning decision".

**10 - Unprofitable cleaning.** Soiling is real and measured (5.4 %), nine gates pass. But the benefit would
last only about three days: the cleaning recovers 1.17 M DZD and costs 4.52 M. Net benefit in the base case
-3,349,692 DZD (conservative -4,859,475, optimistic -1,097,073). Break-even: the cleaning must recover 904 MWh.
The system declines and says when to look again.

Scenarios 2 and 10 share the same cleaning cost and reach opposite answers: the decision depends on how long the
benefit lasts, not on whether dust is present.

## Running them

In the application: start it with `SOLARWISE_DEMO_MODE=true` and choose **Open the demonstration**. The ten
datasets and their analyses are created at start-up. A visitor can run a scenario again with other assumptions;
only that visitor sees the result.

## A demonstration in three parts

**1. The decision depends on the evidence (2 minutes).** Open the demonstration and the plant. Read the table of
datasets: six drops of about 9 %, one cleaning order. Open scenario 2 (*Clean now*, ten gates of ten), then
scenario 5 or 8 (*Investigate*).

**2. What the findings mean (1 minute).** On an analysis, open the tab **AI analysis**. At the top, the engine's
decision in a box of its own, tagged *Engine*. Below, section by section: summary, performance, anomalies, each
possible explanation with the support the engine gave it and its evidence, data quality, economics, why the engine
decided this, next steps, what is missing, limitations. Each section says who wrote it.

* Without a language model - the default - the page says so: "No language model is configured on this server ...
  the deterministic fallback is active". Every section is tagged *Engine*. Nothing is missing.
* With a model configured, **Generate the AI analysis** asks it to write the narrative. Those sections are then
  tagged *AI interpretation*, with the model's name, the time and the checks its text passed; the gates, the
  steps and what would change the decision stay tagged *Engine*. If its answer fails a check, the page says which
  one, and shows the engine's text.
* **Operational report**: PDF, HTML or JSON, eight sections, the engine's tables in annex.

What can be shown honestly: the page, the tags, the fallback, the report. What cannot: that a real model was
tried. It was not - see [ai.md](ai.md).

**3. An operator's own file (2 minutes).** Sign out, create an account, and **Register a plant** of 1,000 kWp:
the form describes the plant and asks for no measurement. On the plant's page, **Upload operational data**, and
choose `data/samples/solarwise-operational-data.example.csv` (also offered for download on that page: *CSV
example*).

* The first rows appear as they are in the file; under each header, what the column was read as - *Energy
  produced · kWh*, *In-plane irradiation · W/m²*, *Cleaning marks*, *Alarms and events*.
* In step 3 every quantity is pre-selected from its header; every provenance is *Unknown - not documented*.
* **Check the file**: 14 rows, three events read from the file (one cleaning, an inverter alarm over two days, a
  grid outage still open on the last row), the conversion of irradiance stated, and what to do about each finding.
* **Import and run the analysis**: the answer is *Investigate* - rule R0, "the production data are not measured
  data and cannot support a cleaning decision". Nothing was declared about where the columns come from, so
  nothing can be decided from them. Declaring them measured would be a false declaration here: the values of this
  file are invented.

The browser check `frontend/e2e/upload_flow.cjs` walks part 3 with a file whose headers are an operator's own, a
correction by hand, declared provenance, and - with the stand-in - the assistant and the generated analysis.

On the command line:

```sh
solarwise scenarios                        # the table of decisions
solarwise scenario S02                     # one scenario as text
solarwise scenario S02 --format pdf -o s02.pdf
solarwise scenarios --operational          # the same data treated as operational: no decision is reached
```

From the files in `data/demo` (each scenario has a CSV, its declarations, its evidence records and its options):

```sh
cd data/demo
solarwise analyze S02_confirmed_soiling.csv --plant plant.json --devices devices.json \
    --metadata S02_confirmed_soiling.metadata.json --evidence S02_confirmed_soiling.evidence.json \
    --options S02_confirmed_soiling.options.json --demonstration
```

Without `--demonstration` the same command evaluates the file as operational data: synthetic values are then not
accepted as evidence and the engine answers `INVESTIGATE`.

## Reproducibility

The generator is seeded, so the same command always writes the same files and the same decisions.
`make demo-data` rewrites `data/demo`; a test fails if the committed files differ from what the generator
writes, and another checks that analysing the exported files reproduces each scenario exactly.
