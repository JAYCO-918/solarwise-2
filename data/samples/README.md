# Templates for your own data

These files show the upload format. The **templates contain no data**: every text to fill in starts with
`REPLACE` and every number to supply is `null`; the platform refuses a file that still contains a
`REPLACE` marker, so a template cannot be imported by mistake. The two **examples** contain 14 days of
**invented** values for a hypothetical 1 MWp plant, to show the format at work; they describe no real
installation.

For complete worked examples with values, see [`../demo`](../demo) - all of them synthetic and
labelled as such.

## Operational data, as an operator's system exports them

The four files offered for download on the page **Upload operational data** (they are copies of the files the
application serves; a test keeps them identical). Their columns carry their units in their names and are
recognised at upload without any declaration: `timestamp`, `energy_kwh`, `expected_energy_kwh`,
`poa_irradiance_w_m2`, `module_temp_c`, `ambient_temp_c`, `relative_humidity_pct`, `wind_speed_m_s`, `rainfall_mm`,
`soiling_ratio`, `cleaning_event`, `alarm`. None of the columns but the first two is required.

| File | Purpose |
|---|---|
| `solarwise-operational-data.template.csv` | the column names, and no row |
| `solarwise-operational-data.example.csv` | 14 invented days, one cleaning, an inverter alarm over two days and a grid outage |
| `solarwise-operational-data.template.json` | one record with every field and no value |
| `solarwise-operational-data.example.json` | the same 14 invented days as JSON records |

The steps of an upload are described in [`docs/data-upload.md`](../../docs/data-upload.md).

## The canonical format, with its declaration file

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
