# Data format

What a file must look like to be imported, and what has to be declared about it. Empty templates and small
examples are in [`data/samples`](../data/samples); complete worked examples - all synthetic - are in
[`data/demo`](../data/demo). The application serves the same dictionary under `GET /api/v1/reference/schema` (page
**Rules and data**). For the steps of an upload as an operator sees them, read [data-upload.md](data-upload.md)
first.

An analysis uses up to five things:

| Item | In the web interface | On the command line |
|---|---|---|
| Plant description | the form **Register a plant** | `--plant plant.json` |
| Time series | the file chosen under **Upload operational data** | the file argument |
| Declarations about the file ("metadata") | the mapping shown after choosing the file, pre-filled from the headers | `--metadata data.metadata.json` |
| Evidence records | the **Evidence** section of the plant, and the event columns of the file | `--evidence evidence.json` |
| Cleaning and economic assumptions | the form shown before running an analysis | `--options options.json` |

## 1. The time series

One row per interval. The interval is 15, 30 or 60 minutes, or one day (1440 minutes); it is inferred from the
timestamps when not declared.

**CSV**: separated by commas, by semicolons (decimal commas are then accepted) or by tabs, with a header line.
**JSON**: either `{"metadata": {...}, "records": [{...}, ...]}` or a bare list of records.

Limits: 25 MB by default (`SOLARWISE_MAX_UPLOAD_MB`), 400,000 rows, 200 columns.

### Three rules

- `timestamp` marks the **start** of the interval. Give a UTC offset (`2026-06-01T00:00+01:00`); a timestamp
  without one is read in the time zone declared in the metadata, or the plant's.
- **An empty cell (or JSON null) means "not observed".** It is never read as zero and never filled in. Write `0`
  only when zero was actually measured.
- Energy is the energy of the interval, not a counter reading.

### Columns

| Column | Canonical unit | Accepted range | Meaning |
|---|---|---|---|
| `timestamp` | - | - | start of the interval |
| `actual_energy_kwh` | kWh | ≥ 0 | energy delivered at the declared metering boundary |
| `expected_energy_kwh` | kWh | ≥ 0 | baseline for the same boundary (optional: the platform can compute one) |
| `baseline_irradiation_kwh_m2` | kWh/m² | ≥ 0 | irradiation the supplied baseline assumed, when it is not weather-adjusted |
| `poa_irradiation_kwh_m2` | kWh/m² | ≥ 0 | in-plane irradiation |
| `ghi_kwh_m2` | kWh/m² | ≥ 0 | global horizontal irradiation |
| `ambient_temp_c` | °C | -60 to 65 | ambient temperature |
| `module_temp_c` | °C | -60 to 110 | module temperature |
| `wind_speed_ms` | m/s | 0 to 75 | wind speed |
| `relative_humidity_pct` | % | 0 to 100 | relative humidity |
| `precipitation_mm` | mm | 0 to 500 | rain |
| `availability_fraction` | fraction | 0 to 1 | share of the plant available |
| `curtailed_energy_kwh` | kWh | ≥ 0 | energy not produced because output was limited, from the dispatch log |
| `soiling_ratio` | fraction | 0 to 1.05 | measured soiling ratio (1 = clean) |
| `device_code` | - | - | when filled in, the row belongs to one device and `actual_energy_kwh` is its energy |

Only `timestamp` and at least one data column are required. Columns may have other names, declared per channel
(`"column": "E_meter"`). A column that is neither known nor declared is reported and ignored.

**Reading the headers.** In the web interface (and through `POST /plants/{plant_id}/datasets/preview`) the server
proposes the declaration of the columns from their headers: `Energy (kWh)`, `Énergie produite (MWh)`, `Tmod_C`,
`Irradiance (W/m2)`, `soiling_loss_pct` are read as what they are, with their units. The vocabulary is fixed, in
English and French; a header that is ambiguous is proposed with a flag, one that states a unit of another
quantity (`Power (kW)` for energy) is not proposed at all. The proposal is only that: it never contains a
provenance, and the uploader confirms or corrects it before anything is validated.

**Device rows.** A file may hold plant-level rows and device-level rows (inverters, blocks) together: a row with
a `device_code` is a device row. The device codes must be registered on the plant with their capacity. Device
rows enable the device-to-fleet comparison.

**Other units** are accepted when declared: energy in `Wh`, `MWh`, `GWh`, `J`, `kJ`, `MJ`; irradiation in
`Wh/m2`, `MJ/m2`, `J/m2`; temperature in `K`, `degF`; speed in `km/h`; ratios in `percent`; rain in `cm`, `in`.
An unknown unit blocks the import: nothing is guessed.

**Irradiance.** The two irradiation columns and the baseline irradiation also accept `W/m2` and `kW/m2`. The value
is then read as the **mean over the interval** and converted with its length: `kWh/m2 = W/m2 x hours / 1000` (for a
daily row, the mean over the 24 hours of the day). Values above 1,600 W/m² are rejected. The report states the
conversion with a warning: spot values or daylight-only means would give a wrong irradiation, and the platform
cannot tell.

**Soiling loss.** A soiling column may hold the measured loss (0 = clean) instead of the ratio (1 = clean):
declare `"reported_as": "LOSS"` on the `soiling_ratio` channel, with `"unit": "percent"` or `"fraction"`. It is
stored as `ratio = 1 - loss`. A loss above 100 % or clearly negative is rejected, not clipped.

**Event columns.** Two optional columns hold events instead of quantities; see `events` below.

## 2. The declarations (metadata)

```json
{
  "name": "June 2026 - grid meter",
  "description": "Exported from the SCADA historian on 2026-07-02 by ...",
  "timezone": "Africa/Algiers",
  "interval_minutes": 1440,
  "channels": {
    "actual_energy": {
      "unit": "kWh", "provenance": "MEASURED",
      "source": "Revenue meter at the delivery point, serial ..., accuracy class 0.2S",
      "uncertainty_pct": 0.5, "boundary": "GRID_METER"
    },
    "expected_energy": {
      "unit": "kWh", "provenance": "MODELLED",
      "source": "Performance model ..., version ...", "method": "...",
      "uncertainty_pct": 2.0, "boundary": "GRID_METER"
    },
    "soiling_ratio": {
      "unit": "fraction", "provenance": "MEASURED",
      "source": "Soiling station ..., reference device cleaned daily",
      "uncertainty_abs": 0.005, "soiling_method": "SOILING_STATION"
    }
  },
  "baseline": {
    "method": "TELEMETRY_MODEL",
    "irradiance_adjusted": true, "temperature_adjusted": true,
    "degradation_adjusted": false, "soiling_allowance_fraction": 0.0,
    "description": "What the model takes into account and what it does not"
  },
  "capacity_dc_kwp": 300000
}
```

| Field | Meaning |
|---|---|
| `name` (required), `description` | How the dataset is called and where it comes from |
| `timezone` | IANA zone applied to timestamps without an offset; defaults to the plant's |
| `interval_minutes` | 15, 30, 60 or 1440; inferred when omitted |
| `timestamp_column`, `device_column` | Names of those columns when they differ from the defaults |
| `channels` | One declaration per channel, keyed by channel name (the column name without its unit suffix: `actual_energy`, `expected_energy`, `poa_irradiation`, `ghi`, `ambient_temp`, `module_temp`, `wind_speed`, `relative_humidity`, `precipitation`, `availability`, `curtailed_energy`, `soiling_ratio`, `baseline_irradiation`) |
| `events` | Columns that hold events: `cleaning_column`, `event_column`, with the `provenance` (`emulates` for synthetic events) and the `source` of the events |
| `baseline` | What a supplied expected-energy channel accounts for |
| `capacity_dc_kwp` | Installed capacity the file refers to; checked against the plant |
| `synthetic` | Mandatory for artificial data: generator, version, seed, statement, injected effects |
| `disclaimer` | A statement displayed with every result derived from the dataset |

**A channel declaration**

| Field | Meaning |
|---|---|
| `column` | Name of the column in the file, when it is not the canonical one |
| `unit` | Unit of the values in the file, when it is not the canonical one |
| `provenance` | `MEASURED`, `MODELLED`, `SYNTHETIC` or `UNKNOWN` (the default when nothing is declared) |
| `emulates` | Synthetic channels only: the class the values stand in for in a demonstration |
| `source`, `method` | Which instrument or model, and how the value is obtained |
| `uncertainty_pct`, `uncertainty_abs` | Standard uncertainty (one sigma), relative in % or absolute in the canonical unit |
| `boundary` | Energy channels: `GRID_METER`, `INVERTER_AC`, `DC_COMBINER`, `UNKNOWN` |
| `plane` | Irradiation channels: `POA` or `GHI` |
| `soiling_method` | `SOILING_STATION`, `CLEAN_REFERENCE_MODULE`, `STRING_COMPARISON`, `IV_CURVE`, `OPTICAL_SENSOR`, `VALIDATED_MODEL`, `VISUAL_ESTIMATE`, `UNSPECIFIED` |
| `reported_as` | Soiling channel only: `RATIO` (1 = clean; also what is assumed when nothing is said) or `LOSS` (0 = clean) |
| `notes` | Free text |

What is declared decides what the data can support: see [data-provenance.md](data-provenance.md). A field the
uploader leaves out is not guessed: undeclared provenance is `UNKNOWN`, an undeclared uncertainty makes the
significance test impossible, an undescribed baseline is reported as such.

The shipped templates declare channels as `MEASURED` to show what a real declaration looks like; every text to
fill in starts with `REPLACE`. A file that still contains such a marker is refused
(`TEMPLATE_NOT_FILLED_IN`), so that a template cannot vouch for data nobody described.

**Events in the file**

```json
"events": {
  "cleaning_column": "Cleaning",
  "event_column": "Alarms",
  "provenance": "MEASURED",
  "source": "SCADA event log, exported with the production data"
}
```

| Column | A cell means | Becomes |
|---|---|---|
| `cleaning_column` | `1`, `x`, `yes`, `y`, `oui`, `true`, `vrai`, `cleaned`, `cleaning`, `nettoyage`, `done`: a cleaning in that interval. Empty or `0`: none | one `CLEANING_EVENT` record per day with a mark |
| `event_column` | text or a code: an alarm or an event. Empty, `0`, `ok`, `no`, `none`, `normal`, `false`, `running`, `ras`, `-`, `n/a`: nothing happened | one record per run of consecutive intervals with the same text |

The text of an event is read with a fixed vocabulary, first match: cleaning (`clean`, `wash`, `nettoy`, `lavage`),
curtailment (`curtail`, `dispatch`, `limitation`, `écrêt`), grid outage (`grid`, `outage`, `blackout`, `réseau`,
`coupure`), sensor fault (`sensor`, `pyranomet`, `capteur`, `logger`, `communication`, `comm`), shading (`shad`,
`ombr`), equipment fault (`inverter`, `onduleur`, `inv`, `trip`, `tracker`, `fault`, `défaut`, `panne`, `failure`).
Anything else is recorded as `OTHER`: kept and shown, **not used by the diagnosis**, with a warning in the report.
`GET /api/v1/reference/schema` returns the vocabulary under `events`.

Each event becomes an evidence record attached to the dataset, with the declared provenance, the text of the cell
and the rows it came from. An event still marked on the last row of the file has no end: it counts as not closed.
One that stopped being reported has an end, and is not marked resolved either - the file does not say it was. A
column that would give more than 500 events is taken for a status column and is not read. Events can only make the
engine more cautious: an open fault leads to `INVESTIGATE`; nothing in an event column can lead to `CLEAN_NOW`.

## 3. The plant

```json
{
  "name": "...", "capacity_dc_kwp": 300000, "capacity_ac_kw": 250000,
  "latitude": 33.49, "longitude": 6.80, "timezone": "Africa/Algiers",
  "tracking": "FIXED", "tilt_deg": 30, "azimuth_deg": 180,
  "module_temp_coeff_per_c": -0.0035, "noct_c": 45, "system_loss_fraction": 0.14,
  "commissioning_date": null, "annual_degradation_rate": null,
  "parameter_notes": { "capacity_dc_kwp": "as-built documentation, revision ..." }
}
```

`name`, `capacity_dc_kwp`, `latitude` and `longitude` are required. `tracking` is `FIXED`, `SINGLE_AXIS` or
`DUAL_AXIS`; `azimuth_deg` is 180 for an array facing south. The other parameters are needed only for what uses
them: the engineering baseline needs the temperature coefficient and the system losses; the transposition of
horizontal irradiation needs a fixed tilt. `parameter_notes` records where each figure comes from. Devices are a
list of `{ "code", "capacity_kwp", "kind" }`.

## 4. Evidence records

Discrete facts that are not time series: a soiling test, an inspection, a fault, a curtailment order, a cleaning.

```json
[
  {
    "reference": "SOILING-001",
    "evidence_type": "SOILING_MEASUREMENT",
    "observed_start": "2026-06-27T12:00:00+01:00",
    "tag": { "provenance": "MEASURED", "source": "Test report ..." },
    "description": "Freshly cleaned strings compared with adjacent uncleaned strings at midday",
    "value": 0.913, "unit": "fraction", "std_uncertainty": 0.006,
    "soiling_method": "STRING_COMPARISON"
  }
]
```

| Field | Meaning |
|---|---|
| `reference` (required) | Your identifier of the record |
| `evidence_type` (required) | `SOILING_MEASUREMENT`, `VISUAL_INSPECTION`, `INVERTER_FAULT`, `SHADING_OBSERVATION`, `CURTAILMENT_EVENT`, `GRID_OUTAGE`, `SENSOR_FAULT`, `CLEANING_EVENT`, `OTHER` |
| `observed_start` (required), `observed_end` | When, with a UTC offset |
| `tag` | Provenance and source of the record |
| `value`, `unit`, `std_uncertainty` | For a measurement: a soiling ratio as a fraction, with its standard uncertainty |
| `soiling_method` | How the soiling was measured |
| `finding` | For an inspection: `SOILING_HEAVY`, `SOILING_LIGHT`, `CLEAN`, `SHADING`, `EQUIPMENT_DAMAGE`, `NO_FINDING` |
| `device_code`, `resolved` | For a fault: the device concerned, and whether it has been repaired |
| `document_ref`, `description` | Where the record is documented |

Through the API a record is sent with `provenance`, `source` and `method` as plain fields instead of a `tag`
object: see [api.md](api.md).

## 5. Cleaning and economic assumptions

```json
{
  "cleaning": {
    "cleaning_effectiveness": 0.9, "cleaning_effectiveness_low": 0.8, "cleaning_effectiveness_high": 0.98,
    "benefit_horizon_days": 30, "benefit_horizon_days_low": 21, "benefit_horizon_days_high": 45,
    "source_note": "Why these values: past cleanings, contractor data, expected time to the next rain"
  },
  "economics": {
    "currency": "DZD",
    "energy_value_per_kwh": 5.0, "energy_value_basis": "SELLING_PRICE", "energy_value_source": "...",
    "water_volume_m3": 1500, "water_price_per_m3": 80,
    "labour_hours": 6000, "labour_rate_per_hour": 400,
    "equipment_cost": 1500000, "operational_cost": 500000, "downtime_cost": 0,
    "cost_uncertainty_pct": 20, "cost_source": "..."
  }
}
```

Nothing has a default: a value that is not supplied is missing, the estimate is then incomplete, and the decision
cannot be `CLEAN_NOW`. The value of energy must say what it is (`energy_value_basis`): `SELLING_PRICE`,
`AVOIDED_PURCHASE_COST` and `INTERNAL_VALUATION` are decision-grade; `CONSUMER_TARIFF_PROXY`, a consumer tariff
used as a stand-in, is not. The
figures above are those of the demonstration: illustrative, not market prices. The same document may carry
`thresholds` to override the engineering defaults listed in [decision-rules.md](decision-rules.md).

## 6. Validation

**Check the file** validates a file without storing it; **Import the dataset** (or **Import and run the analysis**)
validates and stores. The report lists every finding with its severity, a count, examples and, for what the
uploader can act on, **what to do** about it. It also lists the events read from the file.

| Severity | Effect |
|---|---|
| `BLOCKING` | The file cannot be imported: no timestamp column, no data column, an unknown unit or time zone, an unsupported or inconsistent interval, a capacity that does not match the plant, no usable row, or energy above what the plant can deliver in most rows (a sign that the unit or the capacity is wrong) |
| `ERROR` | Rows or values are rejected and stored as missing: unreadable or misaligned timestamps, non-numeric or non-finite values, negative values, values out of range, rows that share a timestamp but disagree (none is kept: the platform does not choose), a declared column that is absent. Energy above the plant's capacity in a few rows is kept and flagged |
| `WARNING` | Imported, but it limits what the data can support: provenance not declared, baseline not described, soiling method not declared, rows for a device that is not registered, an empty channel, production that is zero throughout, timestamps in the future, identical duplicate rows (one copy is kept) |
| `INFO` | For the record: a synthetic dataset, gaps in time, uncertainty or metering boundary not declared, a column that was not mapped, a time zone taken from the plant |

A value that cannot be trusted is **rejected and stored as missing** - never repaired, clipped or replaced by
zero - and every later analysis of the dataset still shows what was rejected. The rows concerned can be downloaded
as they are in the file, with the reason next to each: before the import
(`POST /plants/{plant_id}/datasets/rejected-rows`) and afterwards (`GET /datasets/{dataset_id}/rejected-rows.csv`).

A stored dataset is immutable, and **the uploaded file is kept byte for byte** (`GET /datasets/{dataset_id}/file`).
Importing the same file with the same declarations a second time is refused (`DUPLICATE_DATASET`), identified by
the SHA-256 of file and declarations together. The same file under another declaration, and another file for some
of the same days, are imported and pointed out.

## 7. Without the web interface

```sh
solarwise validate my_data.csv --plant my_plant.json --metadata my_data.metadata.json
solarwise analyze  my_data.csv --plant my_plant.json --metadata my_data.metadata.json \
    --evidence my_evidence.json --options my_options.json --format html -o report.html
```

An offline analysis is advisory: nothing about it is recorded, so it never carries an operational authorisation.
