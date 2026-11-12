# Data provenance

Every number that enters or leaves a SolarWise engine carries a provenance tag. The tag answers one question:
*where does this value come from, and how much may we rely on it?* The implementation is in
`backend/solarwise/core/provenance.py`.

## The four classes

| Class | Meaning | Examples |
|---|---|---|
| `MEASURED` | Direct observation from a sensor, a SCADA historian, a revenue meter or a documented inspection | Energy at the grid meter, a pyranometer reading, a soiling-station ratio |
| `MODELLED` | Output of an engineering or simulation model | A PVGIS average, a satellite-derived irradiance, a temperature computed from ambient conditions, an expected-energy baseline |
| `SYNTHETIC` | Artificially generated for testing or demonstration. Never real. | Every dataset in `data/demo` |
| `UNKNOWN` | Origin or reliability cannot be established | Any column for which nothing was declared |

A tag also records the source (which instrument, which model, who ran it) and, where relevant, the method.

## Two rules, enforced in one place

1. **Synthetic never becomes real.** Any value derived from at least one synthetic input is itself synthetic.
   No operation turns a `SYNTHETIC` tag into `MEASURED` or `MODELLED`.
2. **A derived value is never better than its weakest input.** A model applied to measured inputs yields a
   modelled value; an unknown input makes the result unknown.

Every engine relies on these rules, so the tag of a final figure - a gap, a recoverable energy, a net benefit -
says what the whole chain behind it was made of.

## What each class may support

| Role in the analysis | `MEASURED` | `MODELLED` | `SYNTHETIC` | `UNKNOWN` |
|---|---|---|---|---|
| Production (actual energy) for an operational decision | yes | no | no | no |
| Baseline (expected energy) | yes | yes, when its method and source are declared | no | no |
| Soiling evidence | yes | no | no | no |
| Weather context | yes | yes | no | no: an unknown input makes the result unknown |
| Anything, inside a demonstration | - | - | yes, as a *simulated* result | no |

Consequences:

- A satellite or reanalysis product can serve as a baseline or as context. It contains no information about
  dust on the modules and never counts as proof of soiling.
- A soiling figure that was modelled gives no recoverable energy.
- Data whose origin was not declared are recorded as `UNKNOWN` and treated like it. Nothing is assumed.

## What the platform can and cannot know

Declaring a channel `MEASURED` is a statement by the person who imports the file. The platform cannot check it.
What it does is:

- require the declaration channel by channel (unit, provenance, source), and record what was not declared as
  unknown;
- refuse a shipped template that was not filled in, so that an example declaration cannot be imported by mistake;
- record who imported the file and when, with the SHA-256 of its content;
- keep the declaration with the dataset, which is immutable, and with every result derived from it.

## Demonstrations: synthetic data that exercise the real logic

The demonstration has to show the rules that apply to measured evidence, without ever relabelling artificial
numbers as measurements. A synthetic channel may therefore declare which class it **emulates** inside its
scenario:

    "actual_energy":   { "provenance": "SYNTHETIC", "emulates": "MEASURED", ... }
    "expected_energy": { "provenance": "SYNTHETIC", "emulates": "MODELLED", ... }

- The emulated class is honoured only in the `DEMONSTRATION` context. The value stays `SYNTHETIC` everywhere
  it is shown: "SYNTHETIC (emulates MEASURED)".
- Only synthetic channels may emulate another class, and a synthetic dataset must carry a generator record
  (generator, version, seed, statement, injected effects).
- The same files evaluated as operational data are not accepted as evidence: the answer is `INVESTIGATE`.
- Scenario 9 is numerically identical to scenario 2 but declares no emulated class: even in the demonstration
  the engine refuses to draw a cleaning conclusion from it.

### The context is decided by the server

| Situation | Context | Marking |
|---|---|---|
| A demonstration plant (flag set at creation, one-way: it can never become an operational plant) | `DEMONSTRATION` | every decision *simulated* |
| Anything done from a demonstration session - including a visitor's own plant and a file declared `MEASURED` | `DEMONSTRATION` | every decision *simulated* |
| A registered account on an operational plant | `OPERATIONAL` | an authorisation is possible when every condition holds |
| Figures evaluated without being stored (`/recommendations/evaluate`, `solarwise analyze`) | as requested | advisory: never an authorisation |

Evidence entered during a demonstration session is recorded as synthetic.

## The reference case

The demonstration plant is named after El Foulia (Guemar, El Oued), nominal 300 MWp.

| Item | Status |
|---|---|
| Name, commune and wilaya, nominal capacity | Public information about an existing plant, used only as a setting |
| Coordinates | Approximate location of Guemar - not a surveyed site coordinate |
| AC rating, tilt, azimuth, tracking, temperature coefficient, NOCT, system losses, block layout | Illustrative assumptions - not the actual design of the plant |
| Every time series | Computed by the scenario generator from a seeded pseudo-random sequence. None was measured at El Foulia or anywhere else |
| Prices and costs of the demonstration | Illustrative assumptions - not a market price, tariff or contractual value |

This statement is attached to the plant, to each dataset and to each report.

## External sources

| Source | What it provides | Tag |
|---|---|---|
| PVGIS (European Commission, Joint Research Centre), `PVcalc` | Long-term monthly averages for a typical-year baseline. Not the weather of any particular period | `MODELLED` |
| NASA POWER (NASA Langley Research Center), daily point data | Daily weather context: satellite-derived irradiance, reanalysis meteorology, averaged over a grid cell of about half a degree to one degree | `MODELLED` |

Both are optional and called only on request. A failure leaves the data absent: nothing is made up in their
place, and a fill value of the service becomes a missing value, not a number.

## Economic references

`backend/solarwise/reference/economic_references.json` lists documented references - Algerian regulatory texts
on water tariffs, purchase tariffs for photovoltaic electricity, electricity tariffs and the minimum wage - by
title. **No amount is recorded for them**: their status is `PENDING_VERIFICATION`, because the figures were not
checked against the official texts. The amounts used in the demonstration are stored separately, classified
`DEMONSTRATION_VALUE`. No reference is ever applied automatically: every monetary input of an analysis is
supplied by the user, with its classification and source.

## Where provenance is shown

- **Interface**: a badge next to each figure; a "Provenance and quality" tab on every analysis; the simulated
  banner on every demonstration result.
- **Reports** (PDF, HTML, CSV, JSON): the provenance statement and the simulated marking are part of every
  format.
- **API**: each quantity is an object with its value, unit, tag, uncertainty and basis.
