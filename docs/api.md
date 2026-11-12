# API

The web interface uses the same API as any other client. Everything is under `/api/v1`.

- Interactive description: `/api/docs` on a running server; machine-readable: `/api/openapi.json`.
- The description committed in the repository is `frontend/openapi.json` (43 operations on 34 paths), written
  by `solarwise openapi`.

## Conventions

**JSON** in and out, except file uploads (`multipart/form-data`) and report downloads. Timestamps are ISO 8601
in UTC. A value that is not known is `null`, never `0`.

**Quantities** are objects: `{"value": 10556889.1, "unit": "kWh", "tag": {"provenance": "...", "source": "..."},
"std_uncertainty": null, "basis": "..."}`. The provenance travels with the number.

**Errors** always have the same shape, with a stable code:

```json
{"error": {"code": "DUPLICATE_DATASET", "message": "this file, with the same declarations, has already been imported for this plant", "details": {"dataset_id": 11}}}
```

| Status | Codes |
|---|---|
| 401 | `NOT_AUTHENTICATED` (with `WWW-Authenticate: Bearer`), `INVALID_CREDENTIALS` |
| 403 | `FORBIDDEN`, `REGISTRATION_CLOSED` (sign-up is switched off) |
| 404 | `NOT_FOUND` - also for something that exists but that the account may not see |
| 405 | `METHOD_NOT_ALLOWED` (with an `Allow` header) |
| 409 | `CONFLICT`, `DUPLICATE_DATASET`, `DEMO_LIMIT`, `EMAIL_TAKEN` |
| 413 | `PAYLOAD_TOO_LARGE` |
| 422 | `INVALID` (the request is not valid; `details` lists the fields); for uploads `UNREADABLE_FILE`, `INVALID_METADATA`, `TEMPLATE_NOT_FILLED_IN`; `WEAK_PASSWORD`, `INVALID_EMAIL`; `EXTERNAL_REJECTED` |
| 429 | `TOO_MANY_ATTEMPTS` (sign-in), `TOO_MANY_REQUESTS` (sign-up, demonstration sessions), with `Retry-After` |
| 500 | `INTERNAL_ERROR` - the cause is logged, never returned |
| 502, 503 | `EXTERNAL_UNEXPECTED_RESPONSE`; `EXTERNAL_DISABLED`, `EXTERNAL_UNAVAILABLE` |

`HEAD` is answered wherever `GET` is. Answers under `/api/` carry `Cache-Control: no-store`.

## Authentication

```sh
curl -s -X POST http://localhost:8000/api/v1/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"email": "you@example.org", "password": "..."}'
```

```json
{"access_token": "eyJ...", "token_type": "bearer", "expires_at": "2026-11-12T00:13:54Z",
 "user": {"id": 1, "email": "you@example.org", "full_name": "...", "role": "ADMIN", "is_demo": false, "is_active": true}}
```

Send the token with every other request:

```
Authorization: Bearer eyJ...
```

A proxy that removes or replaces the `Authorization` header would end the session. The token is therefore also
accepted in `X-SolarWise-Token: eyJ...`; the web interface sends both, and the server logs a warning when it had
to fall back on the second one. Tokens last 60 minutes by default; there is no refresh: sign in again.

`POST /api/v1/auth/demo-login` (no body) opens a demonstration session when the server runs in demonstration
mode. `GET /api/v1/auth/me` returns the signed-in account.

**Sign-up.** `POST /api/v1/auth/register` creates an account for the person who sends the request and answers
`201` with the same body as a sign-in, so the new account is signed in at once:

```sh
curl -s -X POST http://localhost:8000/api/v1/auth/register \
     -H 'Content-Type: application/json' \
     -d '{"full_name": "Amina Benali", "email": "amina@example.org", "password": "a sentence of several words"}'
```

The three fields are required and no other is accepted: the account always gets the `ENGINEER` role, and a
request that names a role is refused (`422`). Other refusals: `EMAIL_TAKEN` (`409`), `WEAK_PASSWORD` and
`INVALID_EMAIL` (`422`), `TOO_MANY_REQUESTS` (`429`), and `REGISTRATION_CLOSED` (`403`) on a server started
with `SOLARWISE_ALLOW_REGISTRATION=false`. `GET /api/v1/meta` says whether sign-up is open
(`registration_open`). The e-mail address is not verified.

Accounts with another role are created by an administrator (`POST /api/v1/users`) or with
`solarwise create-user`.

## A complete session

```sh
B=http://localhost:8000/api/v1
H="Authorization: Bearer $TOKEN"

# 1. register a plant
curl -s -X POST $B/plants -H "$H" -H 'Content-Type: application/json' -d '{
  "spec": {"name": "My plant", "capacity_dc_kwp": 300000, "capacity_ac_kw": 250000,
           "latitude": 33.49, "longitude": 6.8, "timezone": "Africa/Algiers",
           "tracking": "FIXED", "tilt_deg": 30, "azimuth_deg": 180,
           "module_temp_coeff_per_c": -0.0035, "noct_c": 45, "system_loss_fraction": 0.14},
  "description": "..."}'                                   # 201 {"id": 2, "role": "OWNER", ...}

# 2. check a file without storing it, then import it
curl -s -X POST $B/plants/2/datasets/validate -H "$H" \
     -F "file=@data.csv" -F "metadata=<data.metadata.json"  # 200 {"accepted": true, "stored": false, "report": {...}}
curl -s -X POST $B/plants/2/datasets -H "$H" \
     -F "file=@data.csv" -F "metadata=<data.metadata.json"  # 201 {"stored": true, "dataset": {"id": 11, ...}}

# 3. run an analysis
curl -s -X POST $B/datasets/11/analyses -H "$H" -H 'Content-Type: application/json' \
     -d '{"options": {"cleaning": {...}, "economics": {...}}}'   # 201 {"id": 11, "decision": "...", "rule": "...", ...}

# 4. read it again, or download a report
curl -s $B/analyses/11 -H "$H"
curl -s $B/analyses/11/report.pdf -H "$H" -o report.pdf     # also .html, .csv, .json
```

The `metadata` form field is a JSON document ([data-format.md](data-format.md)). When it is absent the
declarations are taken from the `metadata` block of a JSON file; when that is absent too, nothing is declared
and every channel is recorded as `UNKNOWN`. The `options` are the cleaning and economic assumptions; `{}` is
accepted and means that none is supplied.

An analysis answers with the summary used in lists - `decision`, `rule`, `reason_code`, `context`, `simulated`,
`operational_authorization`, `gap_pct`, `window_gap_pct`, `headline` - and the complete `result`: every stage of
the pipeline, with the gates, the reasons, the next actions and what would change the decision. The context is
not something a client can choose: the server decides it.

## Endpoints

### Service

| Method and path | Purpose |
|---|---|
| `GET /health` | Liveness and database check. No authentication |
| `GET /meta` | Version, engine version, whether demonstration mode, sign-up, external data and the language model are on. No authentication |

### Accounts

| Method and path | Purpose |
|---|---|
| `POST /auth/login` | Sign in with e-mail address and password |
| `POST /auth/register` | Sign-up: create an account for yourself (role `ENGINEER`) and sign it in. No authentication; only while the server allows it |
| `POST /auth/demo-login` | Enter the demonstration (demonstration mode only) |
| `GET /auth/me` | The signed-in account |
| `GET /users`, `POST /users`, `PATCH /users/{user_id}` | List, create and change accounts (administrators): role, active or not, name |

### Plants

| Method and path | Purpose |
|---|---|
| `GET /plants`, `POST /plants` | Plants the account may see; register a plant |
| `GET`, `PATCH`, `DELETE /plants/{plant_id}` | One plant; change its description; delete it with its datasets and analyses |
| `GET`, `POST /plants/{plant_id}/devices`, `DELETE .../devices/{device_id}` | Inverters or blocks of a plant |
| `GET`, `PUT /plants/{plant_id}/permissions`, `DELETE .../permissions/{user_id}` | Who may access a plant (`OWNER`, `EDITOR`, `VIEWER`) |
| `PUT /plants/{plant_id}/pvgis` | Store PVGIS monthly averages entered by hand |

### Datasets

| Method and path | Purpose |
|---|---|
| `GET /plants/{plant_id}/datasets` | Datasets of a plant |
| `POST /plants/{plant_id}/datasets/validate` | Validate a file without storing it |
| `POST /plants/{plant_id}/datasets` | Import a file |
| `GET /datasets/{dataset_id}` | One dataset with its declarations and its validation report |
| `GET /datasets/{dataset_id}/series` | Plant-level time series in canonical units, for charts and export |
| `DELETE /datasets/{dataset_id}` | Archive a dataset |

### Evidence

| Method and path | Purpose |
|---|---|
| `GET`, `POST /plants/{plant_id}/evidence` | Evidence records of a plant; record one |
| `DELETE /plants/{plant_id}/evidence/{evidence_id}` | Delete a record |

A record is sent flat - `provenance`, `source` and `method` are plain fields:

```json
{"reference": "SOILING-001", "evidence_type": "SOILING_MEASUREMENT",
 "observed_start": "2026-06-27T12:00:00+01:00",
 "provenance": "MEASURED", "source": "Test report ...",
 "value": 0.913, "unit": "fraction", "std_uncertainty": 0.006, "soiling_method": "STRING_COMPARISON"}
```

`provenance` defaults to `UNKNOWN` when it is not given. This differs from the file format of
`solarwise analyze`, where the same information sits in a `tag` object: a `tag` sent to this endpoint is ignored.

### Analyses

| Method and path | Purpose |
|---|---|
| `POST /datasets/{dataset_id}/analyses` | Run an analysis |
| `GET /plants/{plant_id}/analyses` | Analyses of a plant |
| `GET /analyses/{analysis_id}` | One analysis, exactly as it was issued |
| `GET /analyses/{analysis_id}/report.{fmt}` | Export it: `html`, `pdf`, `csv` or `json` |
| `GET /analyses/{analysis_id}/forecast` | Unvalidated reference projections of the performance index |
| `POST /analyses/{analysis_id}/explanation` | Plain-language explanation (the engine's text, or a model's rephrasing when configured and accepted) |

### Advisory calculations

Nothing is stored and nothing is authorised.

| Method and path | Purpose |
|---|---|
| `POST /economics/calculate` | Cost-benefit arithmetic for one cleaning, from figures supplied in the request |
| `POST /recommendations/evaluate` | Evaluate a complete case (plant, records, metadata, evidence, options) without storing it |

### External data

Only when `SOLARWISE_EXTERNAL_DATA_ENABLED` is on; rate-limited for demonstration sessions; both sources are
labelled `MODELLED`. A failure is reported as such: no substitute data are ever produced.

| Method and path | Purpose |
|---|---|
| `POST /plants/{plant_id}/pvgis/fetch` | Fetch the PVGIS typical-year monthly averages for the plant |
| `POST /plants/{plant_id}/weather/nasa-power` | Fetch daily weather context from NASA POWER for a period |

### Reference

| Method and path | Purpose |
|---|---|
| `GET /reference/decision-rules` | The decision rules, gates and thresholds |
| `GET /reference/schema` | Data dictionary: columns, units, declarations |
| `GET /reference/economic` | Documented economic references |

## Limits

| Limit | Value |
|---|---|
| Request body | upload limit + 1 MB; refused before being read (413) |
| Upload | 25 MB by default; 5 MB in a demonstration session |
| Failed sign-ins | 5 per account and address in 5 minutes, then 429; the account locks for 15 minutes |
| Sign-up | 20 attempts per address in 10 minutes, refused ones included, then 429 |
| Demonstration session | 3 plants, 8 datasets per plant, removed after 24 hours |
| External data and model rephrasing, from demonstration sessions | 20 requests per 10 minutes per address |

## Keeping clients in step

`frontend/openapi.json` is generated (`make openapi`), and the TypeScript types of the web interface are
generated from it. A test fails when the committed file differs from what the server describes, so the
description cannot drift from the implementation unnoticed.
