# Uploading operational data

How the measurements of a plant get into SolarWise DZ: as a file, through the page **Upload operational data**.
This guide is for the person who runs the plant. The technical reference of the file format is
[data-format.md](data-format.md).

## Two separate things

| | What it is | Where | How often |
|---|---|---|---|
| **Plant configuration** | what the plant *is*: name, location, installed capacity, mounting, tilt and azimuth, module and loss parameters, devices | the form **Register a plant**, then the tabs *Description* and *Devices* of the plant | once, and when the plant changes |
| **Operational data** | what the plant *measured*: production, expected production, irradiance, temperatures, humidity, wind, rain, soiling, cleaning events, alarms | a CSV or JSON file, uploaded from the plant's page | for every period to analyse |

Nothing the plant measured is typed into a form. The plant form asks for no production figure, and the upload page
asks for no plant parameter.

## What a file may contain

One row per interval: 15, 30 or 60 minutes, or one day. Only the first two columns are needed.

| Column | Needed | Units accepted | What it gives the analysis |
|---|---|---|---|
| Date, or date and time | yes | `2026-05-01`, `01/05/2026`, with `13:00` and an optional UTC offset | the interval of each row |
| Energy produced | yes | Wh, kWh, MWh, GWh | the production to explain |
| Expected or reference production | no | Wh, kWh, MWh, GWh | the baseline; without it the plant's typical year is used |
| Irradiance or irradiation, in the plane of the modules or horizontal | no | W/m², kW/m² (mean over the interval), Wh/m², kWh/m², MJ/m² | the effect of the weather |
| Module temperature, ambient temperature | no | °C, K, °F | thermal losses |
| Relative humidity, wind speed, rainfall | no | %, fraction; m/s, km/h; mm, cm | context: dew, cooling, natural cleaning |
| Soiling ratio, or measured soiling loss | no | fraction or % | the only thing that can show soiling |
| Availability, curtailed energy | no | fraction or %; Wh to GWh | equipment and grid causes |
| Cleaning events | no | a mark: `1`, `yes`, `x`, `oui`, `true`, `cleaned`, `done` | when the array was cleaned |
| Equipment alarms, operational events | no | free text or codes; empty when nothing happened | faults, outages, curtailment, shading, sensor problems |
| Device code | no | text | one row per inverter or block and interval |

A column that is missing limits what can be concluded; it never stops the import. In particular, **without a direct
soiling measurement the result can be Investigate or Monitor, never Clean now**: a production gap alone does not show
soiling.

Your own column names are fine. `Energy (kWh)`, `Énergie produite (MWh)`, `Tmod_C`, `Irradiance (W/m2)` are read as
what they are; a header nobody could read (`T2`, `Prod`) is assigned by hand, or with the help of the assistant.

## Templates and examples

On the upload page, and under **Rules and data > Data format**:

| File | Content |
|---|---|
| `solarwise-operational-data.template.csv` | column names with their units, and no data |
| `solarwise-operational-data.example.csv` | the same columns with 14 days of **invented** values for a hypothetical 1 MWp plant, one cleaning and two alarms |
| `solarwise-operational-data.template.json` | one record with every field and no value |
| `solarwise-operational-data.example.json` | the 14 invented days as JSON records |

The same four files are in [`data/samples`](../data/samples). The examples show the format and describe no real
installation. A template cannot be imported by mistake: the CSV has no row, and the JSON has no usable date.

Columns of the templates: `timestamp`, `energy_kwh`, `expected_energy_kwh`, `poa_irradiance_w_m2`, `module_temp_c`,
`ambient_temp_c`, `relative_humidity_pct`, `wind_speed_m_s`, `rainfall_mm`, `soiling_ratio`, `cleaning_event`, `alarm`.

## The steps

Open the plant, then **Upload operational data** (at the top of the plant's page, and in its empty list of data).

### 1. The file

Choose a CSV file (comma, semicolon or tab separated; with semicolons, decimal commas are read) or a JSON file
(`{"records": [...]}` or a list of records). The server reads it at once. Nothing is stored yet.

If the very same file was already imported for this plant, the page says so here.

### 2. What the file contains

* **The first rows**, cell by cell as they are in the file. An empty cell is shown as *empty*: it means "not
  observed" and is never read as zero.
* Under each header, **what the column is used for** as the mapping stands: *Energy produced · kWh*, *Date and time*,
  *Not used* ...
* **What the reader noticed**: cells that are not numbers, a unit that does not fit the values (kelvin read as °C, Wh
  read as kWh, a percentage read as a fraction), a meter counter instead of the energy of each interval, columns the
  file lacks. Where a unit obviously fits better, a button offers it. Nothing is changed unless you press it.

This reading is deterministic: fixed vocabularies and fixed thresholds, no language model.

### 3. What each column is

The columns are **pre-selected from their headers**, with their units. Each quantity says where its assignment
comes from - *Read from the header* - and carries a *Check* mark when the header is ambiguous (an "Irradiance" that
does not name its plane, a "Temp" that could be the air or the modules) or states no unit.

Correct whatever is wrong: choose another column, another unit, or *not in the file*. For a soiling column, say
whether it holds the **ratio** (1 = clean) or the **loss** (0 = clean); a loss is stored as `ratio = 1 - loss`.

**Events.** Name the column with cleaning marks and the column with alarms, if the file has them.

**Provenance is never pre-selected.** For each column you declare where it comes from:

| Provenance | Meaning | What it can support |
|---|---|---|
| Measured | read from an instrument you name in *Source* | a decision |
| Modelled | computed by a model, a satellite product, a reanalysis | a baseline, or context; never proof of soiling |
| Unknown | not documented - the default | nothing: the analysis will answer Investigate |

Synthetic data cannot be declared in the form: they need a declaration file with the record of their generator.
The platform cannot verify a declaration. It records who imported the file and shows the declaration with every
result.

**The AI assistant** (optional, when a language model is configured). It is sent the column names, a few sample
values and simple statistics - never the file - and suggests what the reader could not place. Each suggestion was
checked by the server (the column exists, the quantity exists, the unit belongs to it). Nothing is applied until you
press **Accept**, and an accepted column is still of unknown provenance until you declare it. See [ai.md](ai.md).

Two other ways to give the declaration remain: a **declaration file** (JSON), and the declaration **inside** a JSON
upload (`metadata`).

### 4. Check, then import

**Check the file** reads the whole file and stores nothing. The report shows:

* whether the file can be imported, and how many rows;
* for each quantity: column, unit and conversion, **declared provenance**, values, empty cells, rejected cells, range;
* the **events** read from the file, how each was read, and whether an alarm is still open on the last row;
* every finding, from *blocking* to *information*, with examples and **what to do** about it;
* another dataset of the plant that covers some of the same days, if there is one.

Two downloads:

* **Validation report (JSON)** - the complete report.
* **Rejected rows (CSV)** - the rows that had something rejected, exactly as they are in the file, with the row
  number of the report and the reason next to each. Correct them and upload the file again. The list stops at
  20,000 rejections; a file with more is counted in full by the report, and the last line of the download says how
  many are not listed.

Then **Import and run the analysis**: the file is stored and the analysis pipeline runs on it at once. (Cleaning
costs and the value of energy are not needed for the diagnosis; add them afterwards with *Run again with other
assumptions*.) Or **Import the dataset** to stop at the dataset.

## What happens to the values

* A cell that cannot be trusted is **rejected and stored as missing** - never repaired, clipped or replaced by zero.
  That covers text where a number is expected, negative energy or irradiance, values outside the range of a sensor,
  and a soiling loss that is not possible (above 100 %, or clearly negative).
* A row whose date cannot be read, or that is off the interval grid, is rejected whole. Two rows for the same moment
  that disagree are both rejected: SolarWise does not choose between conflicting values.
* Intervals without a row stay missing. Nothing is interpolated.
* Irradiance in W/m² is read as the **mean over each interval** and converted with the length of the interval:
  `kWh/m² = W/m² x hours / 1000`. For daily rows that is the mean over the 24 hours of the day. If your column
  holds spot values or daylight-only means, upload the irradiation instead; the report reminds you each time.
* Values above 1,600 W/m² are rejected: they are not plausible at ground level.

## Events

A cleaning mark or an alarm found in a declared event column becomes an **evidence record of the dataset**, with the
provenance you declared for the events. Events never become numbers.

* A cleaning column gives one record per day with a mark.
* An alarm that stays the same over consecutive intervals is **one** event. If it is still marked on the last row
  of the file, it counts as *not closed*.
* The text of an alarm is read with a fixed vocabulary - first match:

| Read as | Words that are recognised |
|---|---|
| Cleaning event | clean, wash, nettoy, lavage |
| Curtailment | curtail, dispatch, limitation, écrêt |
| Grid outage | grid, outage, blackout, réseau, coupure |
| Sensor fault | sensor, pyranomet, capteur, logger, communication, comm |
| Shading observation | shad, ombr |
| Equipment (inverter) fault | inverter, onduleur, inv, trip, tracker, fault, défaut, panne, failure |
| Other | anything else: kept and shown, **not used by the diagnosis** - the report says so |

* Cells that mean nothing happened: empty, `0`, `ok`, `no`, `none`, `normal`, `false`, `running`, `ras`, `-`, `n/a`.
* A column that would produce more than 500 separate events is taken for a status column and is not read.

**An event can only make the engine more cautious.** An open fault in the assessment window leads to Investigate
whatever else the data say. No text in an event column - not even "cleaning needed" - can produce Clean now.

## What is kept

* **The file itself, byte for byte.** Download it from the dataset: *The file as uploaded*. Its SHA-256 is shown.
* The declaration, the validation report, the rejected rows as they were at import.
* The events, as evidence records that belong to the dataset.
* Who imported it and when (audit trail).

A dataset is never modified. A corrected file is imported as a new dataset.

## Duplicates

| Situation | What happens |
|---|---|
| The same file with the same declaration | refused: *Already imported*, with a link to the dataset |
| The same file with another declaration | allowed, and pointed out - a corrected declaration is a legitimate new dataset |
| Another file for some of the same days | allowed, and pointed out. Each dataset is analysed on its own: nothing is counted twice |

## Limits

* 25 MB and 400,000 rows per file by default (`SOLARWISE_MAX_UPLOAD_MB`); 5 MB in a demonstration session.
* The date and the time have to be in **one** column. A file with a date column and a separate time column is
  pointed out; it has to be merged before the upload.
* Excel files are not read: export to CSV.
* Energy has to be the energy of each interval, not the reading of a counter. A counter is recognised and pointed
  out; it is not converted.

## The same through the API

Every operation is under `/api/v1`.

| Step | Operation |
|---|---|
| First look | `POST /plants/{plant_id}/datasets/preview` |
| Suggestions of the model | `POST /plants/{plant_id}/datasets/ai-review` |
| Check | `POST /plants/{plant_id}/datasets/validate` |
| Rejected rows before import | `POST /plants/{plant_id}/datasets/rejected-rows` |
| Import | `POST /plants/{plant_id}/datasets` |
| Analysis | `POST /datasets/{dataset_id}/analyses` |
| The file as uploaded | `GET /datasets/{dataset_id}/file` |
| Rejected rows at import | `GET /datasets/{dataset_id}/rejected-rows.csv` |
| Validation report | `GET /datasets/{dataset_id}/validation-report.json` |
| Templates | `GET /reference/templates/{name}` |

Details in [api.md](api.md).
