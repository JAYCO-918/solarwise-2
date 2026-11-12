# Decision rules

The decision - `CLEAN_NOW`, `INVESTIGATE` or `MONITOR` - is produced by a deterministic rule engine
(`backend/solarwise/core/decision.py`). It reads ten *gates* prepared by the evidence assessment and applies seven
rules in a fixed order; the first rule that applies decides. No statistical or language model takes part.

The same description is served by the application (`GET /api/v1/reference/decision-rules`, page **Rules and
data**) from `core/rules.py`; tests check that it stays in step with the engine.

## The ten gates

A gate is a condition that a cleaning recommendation depends on. Each gate is reported with the evidence it rests
on and the provenance of that evidence, whatever the decision.

| # | Gate | Requirement |
|---|---|---|
| 1 | Reliable measured production data | The production channel is of the measured class, its metering is declared reliable enough, and the assessment window is sufficiently complete. Synthetic, modelled or unknown-origin production never passes outside a demonstration. |
| 2 | Baseline of documented origin | The expected energy comes from a baseline whose method and source are declared. |
| 3 | Significant under-performance now | In the assessment window the gap exceeds both the materiality threshold and the combined expanded uncertainty of baseline and metering. |
| 4 | Credible measured soiling evidence | A direct soiling measurement (soiling station, clean/dirty reference pair, or equivalent) of the measured class, recent enough, showing a loss above the credibility floor and above its own uncertainty. A production gap is not soiling evidence. |
| 5 | Soiling measurement consistent with the production gap | The measured soiling loss and the gap left after the other quantified factors agree within the tolerance. |
| 6 | No unresolved technical issue | No open outage, under-performing device, availability alert or unresolved fault record in the assessment window. |
| 7 | No critical contradiction in the evidence | No pair of sources contradict each other in a way that changes the conclusion (for example an inspection finding clean modules while a sensor reports heavy soiling). |
| 8 | Recoverable energy estimated from measured soiling | Cleaning effectiveness and benefit horizon were supplied, and the estimate rests on the credible soiling measurement. |
| 9 | Economic inputs complete and decision-grade | Every cost item and the value of energy were supplied, and the value of energy is a selling price, an avoided purchase cost or an internal valuation - not a consumer-tariff stand-in. |
| 10 | Cleaning profitable in the conservative case | The net benefit is positive with the low recoverable-energy estimate and the high cost estimate. |

## The rules, in order

| Rule | Decision | Applies when | Why |
|---|---|---|---|
| R0 | `INVESTIGATE` | Production data are not reliable measured data, or the baseline is not documented. | Without trustworthy production and a known reference there is no gap to reason about. |
| R1 | `INVESTIGATE` | A technical issue is open in the assessment window. | Its losses cannot be separated from soiling, and cleaning would not recover them. |
| R2 | `INVESTIGATE` | The evidence contains a critical contradiction. | A decision resting on one of two contradicting sources would be arbitrary. |
| R3 | `CLEAN_NOW` | Every one of the ten gates is passed. | Measured under-performance, explained by measured soiling, with nothing else open, and a cleaning that pays even in the conservative case. |
| R4 | `INVESTIGATE` | The deviation is significant, a material part of it is unexplained, and soiling is not credibly measured and consistent with it. | A production gap alone does not prove soiling. |
| R5 | `INVESTIGATE` | Soiling is credibly measured and matches the deviation, but the recoverable energy or the economic inputs are not decision-grade. | It cannot yet be shown that cleaning pays. |
| R6 | `MONITOR` | None of the above: no significant deviation, a deviation explained by something cleaning does not change, or a cleaning that would not pay. | Nothing to act on now; the analysis is repeated after the review interval. |

The order matters. R0 to R2 come first because they describe situations in which no conclusion about soiling can
be trusted; `CLEAN_NOW` is reachable only after them, and only with all ten gates.

### The safety interlock

After the rules, a `CLEAN_NOW` result is checked again, independently of the path that led to it: every gate, and
the provenance of the decisive evidence. If the check fails the decision becomes `INVESTIGATE` with rule
`INTERLOCK`. This is defence in depth: a programming error in the rules must not be able to issue a cleaning
order.

## Reasons

Every decision carries a reason code, a one-sentence headline, the detailed reasons, the next actions, and what
would change the decision.

| Rule | Reason code | Headline |
|---|---|---|
| R0 | `INSUFFICIENT_DATA` | the data are not sufficient to support a decision |
| R0 | `NON_MEASURED_PRODUCTION` | the production data are not measured data and cannot support a cleaning decision |
| R1 | `TECHNICAL_ISSUE` | a technical issue is open and has to be resolved first |
| R2 | `CONFLICTING_EVIDENCE` | the evidence contradicts itself |
| R3 | `CLEANING_JUSTIFIED` | measured soiling explains the loss and cleaning pays even in the conservative case |
| R4 | `UNEXPLAINED_DEVIATION` | a significant loss is not explained, and a production gap alone does not prove soiling |
| R5 | `ECONOMIC_INPUTS_INCOMPLETE` | soiling is measured, but it cannot yet be shown that cleaning pays |
| R6 | `NO_SIGNIFICANT_DEVIATION` | production is in line with the baseline |
| R6 | `DEVIATION_EXPLAINED_NOT_SOILING` | the loss is explained by a cause that cleaning does not address |
| R6 | `CLEANING_NOT_PROFITABLE` | soiling is measured, but cleaning now would cost more than it recovers |
| R6 | `CLEANING_MARGINAL` | soiling is measured, but cleaning now is not robustly profitable |
| R6 | `EVIDENCE_WEAK` | the evidence does not point to a loss that cleaning would recover |
| INTERLOCK | `SAFETY_INTERLOCK` | a cleaning decision was withheld by the safety interlock |

## Simulated decisions and operational authorisation

A decision and an authorisation are two different things.

- **Context.** An evaluation is either `OPERATIONAL` or `DEMONSTRATION`. The server decides: a demonstration
  plant, or anything evaluated from a demonstration session, is a demonstration.
- **Simulated.** In a demonstration every decision is marked *simulated*; the headline starts with
  "SIMULATED DECISION" and ends with "Not an operational instruction", in the interface and in every export.
- **Operational authorisation** is given only when all of this holds: the decision is `CLEAN_NOW`, the context is
  operational, the plant is not a demonstration plant, no synthetic evidence is present, and the analysis was run
  on stored, attributable data. Even then the text says that the cleaning must still be approved and scheduled
  by the responsible operator.
- **Advisory evaluations** - `POST /api/v1/recommendations/evaluate` and `solarwise analyze` - work on figures
  that are not recorded. They can show `CLEAN_NOW` but never carry an authorisation.
- Synthetic data evaluated as operational data are not accepted as evidence: gate 1 fails and the answer is
  `INVESTIGATE` (R0). Scenario 9 demonstrates the same refusal inside the demonstration.

## Thresholds

Engineering defaults, applied unless an analysis is run with other values. They are judgement values, not
calibrated on any plant (see [limitations.md](limitations.md)); every analysis records the values it used.

| Threshold | Default | Meaning |
|---|---|---|
| `gap_materiality_pct` | 3 % | A relative gap below this is treated as normal variation. |
| `gap_severe_pct` | 10 % | A relative gap above this is called severe. |
| `coverage_factor` | 2 | Coverage factor k applied to standard uncertainties (2 corresponds to about 95 %). |
| `min_data_completeness` | 0.90 | Minimum share of daylight intervals with both expected and actual data. |
| `assessment_window_days` | 7 | Length of the most recent window describing the current state of the plant. |
| `soiling_credibility_floor_pct` | 2 % | A measured soiling loss below this is not treated as credible evidence. |
| `soiling_measurement_max_age_days` | 7 | Maximum age of a spot soiling measurement relative to the period end. |
| `consistency_tolerance_pct` | 3 points | Allowed disagreement between the measured soiling loss and the gap it should explain. Widened to k times the combined uncertainty of the two when that is larger. |
| `rain_cleaning_threshold_mm` | 6 mm | Daily rainfall assumed to clean the array (Kimber et al. 2006 use about 6 mm). |
| `min_dry_days_for_trend` | 14 | Minimum dry spell before a downward trend is read as possible soiling. |
| `availability_alert_fraction` | 0.99 | Availability below this in the assessment window counts as an open equipment issue. |
| `device_underperformance_ratio` | 0.90 | A device yielding less than this share of the fleet median is under-performing. |
| `outage_actual_fraction` | 0.02 | Actual energy below this share of expected energy, in daylight, marks an outage interval. |
| `shading_edge_excess_pct` | 10 points | Excess loss near sunrise or sunset over midday that suggests shading. |
| `step_change_min_drop_pct` | 3 points | A level shift of the performance index larger than this is an abrupt change. |
| `factor_materiality_pct` | 1 % | A quantified effect smaller than this share of expected energy is immaterial. |

## A worked example: scenario 2

Synthetic data, so the decision is simulated. The assessment window is 23 to 29 June 2026.

| Gate | Result | Evidence reported |
|---|---|---|
| 1 Production measured | passed | Actual energy stands in for revenue-meter energy; completeness 100 % over the period and in the window |
| 2 Baseline documented | passed | Stand-in for a weather-adjusted performance model (`TELEMETRY_MODEL`) |
| 3 Deviation significant | passed | Gap 8.6 %; combined standard uncertainty 2.05 % (k = 2: 4.10 %); materiality threshold 3 % |
| 4 Soiling evidence credible | passed | Soiling loss 8.5 % from the soiling-ratio channel, last reading on the last day of the period |
| 5 Soiling consistent with gap | passed | Deviation left for soiling to explain 8.4 % against 8.5 % measured: difference -0.1 point (tolerance 4.2) |
| 6 No technical issue | passed | No equipment, outage or sensor issue open in the window |
| 7 No contradiction | passed | None found |
| 8 Recoverable energy estimated | passed | Over 30 days: 2,078 to 6,907 MWh (central 3,784 MWh) |
| 9 Economics decision-grade | passed | All cost items and a decision-grade energy value supplied |
| 10 Profitable, conservative case | passed | Conservative net benefit 4,965,999 DZD |

Ten of ten: rule R3, `CLEAN_NOW`, marked simulated. Scenario 10 passes nine gates - soiling is measured and
consistent - and fails only the last one, because the benefit would last three days: rule R6, `MONITOR`. The ten
scenarios are in [demo-scenarios.md](demo-scenarios.md).

## What the tests guarantee

The backend tests marked `safety` (`pytest -m safety`) hold the invariants that must never be relaxed, among
them: a production gap alone never yields `CLEAN_NOW`; production that is not measured cannot support a decision;
synthetic production never yields `CLEAN_NOW` on an operational plant; no demonstration scenario ever carries an
operational authorisation; an evaluation of figures that are not stored never authorises anything; a missing cost
is not counted as zero. The tests of the language-model layer check, separately, that a model cannot change the
decision statement and that an answer urging a cleaning the engine did not decide is rejected.
