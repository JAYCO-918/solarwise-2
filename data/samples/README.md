# Templates for your own data

These files show the upload format. **They contain no data.** Every text to fill in starts with
`REPLACE` and every number to supply is `null`; the platform refuses a file that still contains a
`REPLACE` marker, so a template cannot be imported by mistake.

For complete worked examples with values, see [`../demo`](../demo) - all of them synthetic and
labelled as such.

| File | Purpose |
|---|---|
| `plant.template.json` | description of the plant (used by `solarwise analyze`; in the web interface the same fields are a form) |
| `daily_measured.template.csv` | column headers of a daily time series |
| `daily_measured.template.metadata.json` | what the columns are: unit, provenance and source of each channel, and what the baseline accounts for |
| `evidence.template.json` | discrete evidence: cleaning events, soiling measurements, inspections, fault and curtailment logs |
| `options.template.json` | cleaning and economic assumptions for the recoverable-energy and cost-benefit calculation |

## The time series

One row per interval (15, 30 or 60 minutes, or one day). CSV separated by commas, by semicolons (decimal commas are then accepted) or by tabs, or JSON
(`{"metadata": {...}, "records": [{...}]}`).

* `timestamp` marks the **start** of the interval. Give a UTC offset (`2026-06-01T00:00+01:00`); a
  timestamp without one is read in the time zone declared in the metadata.
* **An empty cell means "not observed".** It is never read as zero and never filled in. Write `0`
  only when zero was actually measured.
* Energy is the energy of the interval, not a counter reading.

| Column | Unit | Meaning |
|---|---|---|
| `actual_energy_kwh` | kWh | energy delivered at the declared metering boundary |
| `expected_energy_kwh` | kWh | baseline for the same boundary (optional: the platform can compute one) |
| `baseline_irradiation_kwh_m2` | kWh/m² | irradiation the supplied baseline assumed, if it is not weather-adjusted |
| `poa_irradiation_kwh_m2` | kWh/m² | in-plane irradiation |
| `ghi_kwh_m2` | kWh/m² | global horizontal irradiation |
| `ambient_temp_c`, `module_temp_c` | °C | temperatures |
| `wind_speed_ms` | m/s | wind speed |
| `relative_humidity_pct` | % | relative humidity |
| `precipitation_mm` | mm | rain |
| `availability_fraction` | 0-1 | share of the plant available |
| `curtailed_energy_kwh` | kWh | energy not produced because output was limited, from the dispatch log |
| `soiling_ratio` | 0-1 | measured soiling ratio (1 = clean) |
| `device_code` | - | when filled in, the row belongs to one device (inverter, block) and `actual_energy_kwh` is its energy |

Other units are accepted when declared in the metadata (`MWh`, `Wh`, `Wh/m2`, `MJ/m2`, `K`, `degF`,
`km/h`, `percent`...). `GET /api/v1/reference/schema` lists them all.

## The declarations decide what the data can support

For every channel the metadata states a provenance:

| Provenance | Meaning | Can it support an operational decision? |
|---|---|---|
| `MEASURED` | read from an instrument that is identified in `source` | yes |
| `MODELLED` | computed by a model, a satellite product or a reanalysis | as a baseline or as context, never as proof of soiling |
| `SYNTHETIC` | artificial values | no - demonstrations only |
| `UNKNOWN` | origin not documented (the default when nothing is declared) | no |

Declaring a channel `MEASURED` is a statement that it was measured. The platform cannot check it:
it records who imported the file and keeps the declaration with every result.

A production gap alone is not evidence of soiling. `CLEAN_NOW` requires a direct soiling
measurement (soiling station, clean-reference comparison, string comparison or I-V test) that is
recent and consistent with the gap, among other conditions - see `docs/decision-rules.md`.

## Analyse without the web interface

    solarwise validate my_data.csv --plant my_plant.json --metadata my_data.metadata.json
    solarwise analyze  my_data.csv --plant my_plant.json --metadata my_data.metadata.json \
        --evidence my_evidence.json --options my_options.json --format html -o report.html

An offline analysis is advisory: nothing about it is recorded, so it never carries an operational
authorisation.
