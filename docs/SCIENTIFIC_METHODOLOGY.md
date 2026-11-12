# Scientific methodology

This document describes how each figure is obtained. The implementation is in `backend/solarwise/core`; every
relation below is a closed-form calculation with a published reference, tested against independent values where
one exists.

**What the method is, and is not.** It is an engineering accounting of energy, with explicit uncertainty and
explicit provenance. It is not a soiling model: it never infers soiling from production. It does not learn from
data, and it has not been validated on a real plant - the thresholds are engineering judgement
(see [limitations.md](limitations.md)).

## 1. The starting point

    gap = expected energy - actual energy

A gap is an observation about production. It is silent on causes: soiling, heat, an equipment fault, shading,
curtailment and bad data all produce one. The method therefore keeps four quantities strictly apart:

| Quantity | What it is |
|---|---|
| Observed gap | Expected minus actual energy. A fact about production. |
| Soiling-related loss | The part of the loss that a *soiling measurement* accounts for. It exists only when soiling was measured. |
| Recoverable energy | What a cleaning is expected to bring back over the time its benefit lasts. A projection. |
| Uncertainty | A range traceable to declared measurement uncertainty and to the declared range of each assumption. |

## 2. Units and time

One canonical unit per dimension (kWh, kW, kWh/m², W/m², °C, m/s, mm, fraction); other units are converted
explicitly at import and an unknown unit is refused. Timestamps mark the start of an interval and are stored in
UTC. The analysis lays out the full grid of intervals the period *should* contain (15, 30 or 60 minutes, or one
day) and matches observations onto it, so that a missing record is counted as missing instead of vanishing.
Night intervals are identified from solar geometry and are not counted as missing production.

## 3. The baseline: what should the plant have produced?

Five sources, of very different quality, behind one interface:

| Method | Source | Adjusted to the actual weather? |
|---|---|---|
| `OPERATOR_SUPPLIED`, `TELEMETRY_MODEL` | An expected-energy channel delivered with the data | as declared by the uploader |
| `ENGINEERING_MODEL` | SolarWise's own estimate from irradiation, temperature and the plant's design parameters | yes |
| `HISTORICAL_CLEAN_REFERENCE` | The same model, its system factor calibrated on a period declared clean and fully available | yes |
| `PVGIS_TYPICAL_YEAR` | Long-term monthly averages from PVGIS, scaled to the installed capacity | no |

Every baseline carries a descriptor stating what it accounts for (irradiance, temperature and its reference cell
temperature, degradation, a soiling allowance), a provenance tag and its limitations. A modelled reference is
never presented as the plant's measured clean-condition performance.

### The engineering model

For one interval, in the structure of the PVWatts DC model (Dobos 2014):

    E = P0 × (H_poa / G_STC) × (1 + γ (T_cell − 25)) × (1 − L_sys) × d

with `P0` the installed DC capacity, `H_poa` the in-plane irradiation, `G_STC` = 1 kW/m², `γ` the power
temperature coefficient of the modules (negative), `L_sys` the lumped losses of a clean, fully available array
other than temperature (wiring, mismatch, inverter and transformer efficiency), and `d` the degradation factor.
The result is capped at the AC rating. Soiling is deliberately not part of `L_sys`.

**Cell temperature**, in order of preference:

1. the measured module temperature, used as it is;
2. the Faiman (2008) model: `T_mod = T_amb + G / (u0 + u1·v)`, from ambient temperature, irradiance and wind speed;
3. the NOCT model (Ross 1976): `T_cell = T_amb + (NOCT − 20) / 800 × G`.

**In-plane irradiation**: the in-plane channel when present. For daily data of a fixed array with a known tilt,
global horizontal irradiation is transposed with the isotropic-sky model (Liu and Jordan), the diffuse fraction
coming from Erbs, Klein and Duffie (1982) and the extraterrestrial radiation from the FAO-56 relations (Allen et
al. 1998). The result is then a *modelled* quantity and is tagged so.

**Daily data.** A day known only by its total has no irradiance profile. The irradiance driving the temperature
models is then the energy-weighted mean of an assumed half-sine day, `(π²/8) × H / D` for a day of length `D`.
It is a proxy for clear days and is labelled as one.

**Performance ratio** and its temperature-corrected form follow IEC 61724-1:
`PR = E / (P0 × H_poa / G_STC)`.

## 4. The gap and its significance

    gap = Σ expected − Σ actual      relative gap = gap / Σ expected × 100

computed only over intervals for which **both** values exist. A missing measurement is never replaced by zero:
it removes the interval from the comparison and lowers the reported coverage. The gap is reported for the whole
period and for the *assessment window* - the last 7 days by default - which describes the current state of the
plant and is what the decision uses.

With relative standard uncertainties `u_E` (baseline) and `u_A` (metering), assumed independent:

    u(gap) / E = sqrt( u_E² + (u_A × A / E)² )

The gap is

- **material** when it reaches the materiality threshold (3 % by default);
- **distinguishable** from zero when it exceeds `k` times that combined uncertainty (`k` = 2, about 95 %);
- **significant** when it is material and not contradicted by the uncertainty test.

In the demonstration the declared uncertainties are 2 % for the baseline and 0.5 % for the meter, which gives a
combined standard uncertainty of 2.05 % and a distinguishability limit of 4.1 %. When no uncertainty was
declared the test cannot be made, and that is reported.

## 5. Attribution: the loss chain

Starting from the baseline, each matched interval is walked through a chain of factors. A factor is applied only
when the inputs needed to *calculate* it exist; otherwise it is reported as `NOT_QUANTIFIED` and whatever effect
it may have stays - visibly - inside the unexplained residual.

    baseline expected energy
      / (1 − declared soiling allowance)                  -> clean reference
      × irradiance ratio  H_actual / H_baseline           (baselines not adjusted to irradiance)
      × temperature ratio (1+γ(T−25)) / (1+γ(T_ref−25))   (baselines not adjusted to temperature)
      × degradation factor                                (baselines that ignore ageing)
      = weather-adjusted expected energy of a clean, available plant
      − downtime      (intervals with no production while energy was expected)
      − equipment     (logged availability, or the device-to-fleet comparison)
      − curtailment   (energy logged as curtailed)
      = pre-soiling expected energy
      − soiling       (measured soiling ratio)
      − actual energy
      = unexplained residual

Soiling is never inferred from the gap: the soiling step exists only where a soiling ratio was observed. A
factor already reflected in the baseline is reported as `ACCOUNTED_IN_BASELINE`, not counted twice.

## 6. Signatures

The *shape* of a loss says something about its cause but never proves it. Each signature is treated as indirect
evidence.

| Signature | Method | What it can suggest |
|---|---|---|
| Trend of the daily performance index | Theil-Sen slope with Sen's distribution-free confidence interval (Sen 1968), over the dry spell since the last rain of at least 6 mm or the last cleaning; at least 14 dry days | A slow steady decline: soiling accumulation - or vegetation, or a drifting sensor |
| Level shift | Largest drop between adjacent windows, compared with the robust point-to-point noise | An abrupt lasting drop: an equipment fault - or a dust storm |
| Recovery after rain or a cleaning | Level before and after the event | Removal of soiling |
| Device against fleet | Specific yield (kWh/kWp) of each inverter block against the fleet median; below 0.90 is under-performing | A problem on that device; plant-wide soiling does not produce it |
| Shape of the day (sub-daily data) | Loss near sunrise and sunset against midday; an excess of 10 points on one side, day after day | Shading by a fixed obstruction |
| Plateau (sub-daily data) | Output held flat below what the plant could deliver while the expected output keeps rising | Curtailment |
| Outage intervals | Actual energy below 2 % of expected energy in daylight | Downtime |

Outliers are detected with the modified z-score of Iglewicz and Hoaglin (1993). All estimators are
non-parametric and resistant to outliers.

## 7. Diagnostic hypotheses

Seven hypotheses are evaluated side by side: soiling, temperature, inverter or equipment, shading, curtailment or
downtime, insufficient data, and unclassified. None is "the answer" by construction. Each receives an ordinal
*support level* from explicit rules, with the evidence for and against it, what is missing, and what to
investigate:

| Level | Meaning |
|---|---|
| `STRONG` | Direct evidence of the measured class, consistent with the data |
| `MODERATE` | Indirect evidence (a pattern, a document), or direct but incomplete |
| `WEAK` | Compatible with the data, not specifically evidenced |
| `NOT_SUPPORTED` | The evidence that exists argues against it |
| `NOT_EVALUABLE` | The evidence needed to judge it is missing |

**Why levels and not percentages.** A numeric "confidence" would need a probability model of plant failures
that does not exist here. Numeric uncertainty is therefore attached only to quantities whose uncertainty follows
from declared measurement uncertainty. Several hypotheses may remain plausible at once, and evidence may
conflict; both are reported as such (`MULTIPLE_PLAUSIBLE`, `CONFLICTING_EVIDENCE`) instead of being resolved by
fiat.

## 8. Soiling evidence

Soiling evidence is a direct measurement: a soiling station (soiling ratio channel), a clean-reference module or
string comparison, an I-V curve test, or an equivalent. With soiling ratio `SR` (1 = clean), the loss is
`1 − SR`. A measurement is **credible** when it is

- of the measured class (in a demonstration: a synthetic value explicitly declared to stand in for one),
- recent: at most 7 days before the end of the period,
- above the credibility floor of 2 % *and* above `k` times its own declared uncertainty.

It is **consistent** with the production gap when the loss it shows and the gap left after the other quantified
factors differ by no more than the tolerance: 3 percentage points, or `k × sqrt(u_gap² + u_soiling²)` when that
is larger. A visual inspection is evidence too, of a weaker kind; an inspection that contradicts a sensor is a
contradiction, not a tie to be broken.

## 9. Recoverable energy

With the measured soiling loss fraction `L`, the cleaning effectiveness `η` (share of the soiling loss a cleaning
removes), the projected daily energy of a clean array `E_d` and the benefit horizon `H` (days until rain or the
next scheduled cleaning would have reset the array anyway):

    recoverable = L × η × E_d × H

Soiled and cleaned arrays are assumed to keep accumulating dust at the same rate, so the advantage of the
cleaned array stays `L × η` until the horizon. A low, central and high value are obtained from the uncertainty
of the measurement and the declared range of each assumption. `η` and `H` are supplied by the user with their
source; nothing is assumed. Without a credible, quantified soiling measurement the engine returns
`INSUFFICIENT_EVIDENCE` and no number.

## 10. Economics

    gross benefit = recoverable energy × value of energy
    total cost    = water + labour + equipment + operational + downtime
    net benefit   = gross benefit − total cost
    ROI           = net benefit / total cost × 100
    break-even    = total cost / value of energy          [kWh to be recovered]

evaluated in three cases: **conservative** (low recoverable energy, high cost), **base** (central values) and
**optimistic** (high recoverable energy, low cost). No price is built in. Every monetary input is supplied with
the request, with a classification and a source. A missing cost item is reported as missing - it is not counted
as zero - and the result is then incomplete.

The *basis* of the value of energy matters: the price a plant is actually paid is not the tariff a consumer
pays. A consumer tariff used as a stand-in is accepted for illustration but is not decision-grade, and gate 9
then fails. The decision requires a positive net benefit in the conservative case.

## 11. Data quality and adequacy of the evidence

Row-level validation happens at import (see [data-format.md](data-format.md)). The analysis then looks at each
series as a whole: completeness and gaps, values physically impossible for *this* plant, stuck sensors,
production at night, statistical outliers. Nothing is repaired: suspect values are reported, not altered.

The adequacy of the data for diagnosis is graded `HIGH`, `MEDIUM`, `LOW` or `INSUFFICIENT`. The grade is a
transparent checklist count, shown with its items; it is not a probability.

## 12. Projections

Three reference methods project the daily performance index: persistence, a moving average and a robust linear
trend. They are the kind of method any forecast must beat to be worth using. They are **not validated**: the
back-test shown with each is computed on the very dataset being analysed and covers a few weeks at most. The
projections are shown for orientation only, are labelled as unvalidated, never enter a decision, and are not
soiling forecasts.

## 13. Provenance through the calculation

Every value entering or leaving an engine carries a provenance tag. A derived value is never better than its
weakest input, and a value derived from at least one synthetic input is synthetic. See
[data-provenance.md](data-provenance.md).

## References

- IEC 61724-1:2021. *Photovoltaic system performance - Part 1: Monitoring.*
- Dobos, A. (2014). *PVWatts Version 5 Manual.* NREL/TP-6A20-62641.
- Faiman, D. (2008). Assessing the outdoor operating temperature of photovoltaic modules. *Progress in
  Photovoltaics* 16, 307-315.
- Ross, R. G. (1976). The NOCT approach to cell temperature.
- Allen, R., Pereira, L., Raes, D., Smith, M. (1998). *Crop evapotranspiration.* FAO Irrigation and Drainage
  Paper 56 (extraterrestrial radiation, declination, sunset hour angle, daylight hours).
- Liu, B., Jordan, R. (1962, 1963). Isotropic-sky model for tilted surfaces, as given in Duffie and Beckman,
  *Solar Engineering of Thermal Processes.*
- Erbs, D., Klein, S., Duffie, J. (1982). Estimation of the diffuse radiation fraction for hourly, daily and
  monthly-average global radiation. *Solar Energy* 28(4).
- Sen, P. K. (1968). Estimates of the regression coefficient based on Kendall's tau. *Journal of the American
  Statistical Association* 63, 1379-1389.
- Iglewicz, B., Hoaglin, D. (1993). *How to Detect and Handle Outliers.*
- Kimber, A. et al. (2006). The effect of soiling on large grid-connected photovoltaic systems in California and
  the Southwest region of the United States (daily rainfall threshold assumed to clean an array).
