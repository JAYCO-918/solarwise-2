# Demonstration scenarios

**Every file in this directory is synthetic.** SYNTHETIC DEMONSTRATION DATASET. Every value was computed by the SolarWise DZ scenario generator from a seeded pseudo-random sequence. It contains no measurement from the El Foulia plant or from any other plant and does not describe the actual operation of any plant. The plant name, location and nominal capacity are public reference information; all technical parameters are illustrative assumptions.

The files were written by `solarwise export-demo` (generator seed 20260607, engine 0.1.0) and are
reproduced exactly by running the command again. Do not edit them by hand.

For each scenario:

| File | Content |
|---|---|
| `<scenario>.csv` | time series in the upload format (plant rows first, then one row per device and interval) |
| `<scenario>.metadata.json` | what the file declares: units, provenance of each channel, baseline, synthetic statement |
| `<scenario>.evidence.json` | discrete evidence records attached to the scenario (soiling measurements, logs, inspections) |
| `<scenario>.options.json` | the cleaning and economic assumptions used in the demonstration (illustrative, not prices) |

`plant.json` and `devices.json` describe the demonstration plant. Its name, location and nominal capacity are
public reference information; every technical parameter is an illustrative assumption.

Run one from the files:

    solarwise analyze S02_confirmed_soiling.csv --plant plant.json --devices devices.json \
        --metadata S02_confirmed_soiling.metadata.json --evidence S02_confirmed_soiling.evidence.json \
        --options S02_confirmed_soiling.options.json --demonstration

Without `--demonstration` the same command evaluates the file as operational data; synthetic values are then
not accepted as evidence and the engine answers INVESTIGATE.

| Scenario | Shows | Simulated decision |
|---|---|---|
| `S01_normal_operation` | Normal operation | MONITOR (rule R6) |
| `S02_confirmed_soiling` | Confirmed soiling | CLEAN_NOW (rule R3) |
| `S03_temperature_effect` | Temperature effect | MONITOR (rule R6) |
| `S04_inverter_fault` | Inverter fault | INVESTIGATE (rule R1) |
| `S05_shading` | Morning shading | INVESTIGATE (rule R4) |
| `S06_curtailment` | Grid curtailment | MONITOR (rule R6) |
| `S07_missing_data` | Missing data | INVESTIGATE (rule R0) |
| `S08_conflicting_evidence` | Conflicting evidence | INVESTIGATE (rule R2) |
| `S09_synthetic_demonstration` | Synthetic demonstration (no evidence role declared) | INVESTIGATE (rule R0) |
| `S10_unprofitable_cleaning` | Unprofitable cleaning | MONITOR (rule R6) |
