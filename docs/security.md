# Security

What protects accounts, sessions, uploads and results, and what is deliberately left to the installation.
Implementation: `backend/solarwise/security.py`, `api/deps.py`, `api/middleware.py`, `services/`.

## Accounts and passwords

- **Sign-up** is open by default: whoever can reach the application can create an account for themselves on the
  sign-in page. Such an account gets the `ENGINEER` role - never `ADMIN`; a request that names a role is
  refused - and sees no plant of anybody else until an owner shares one. `SOLARWISE_ALLOW_REGISTRATION=false`
  closes sign-up; accounts are then created only by an administrator or with `solarwise create-user`.
- What sign-up does not do: the **e-mail address is not verified**. It identifies the account; it does not
  prove who uses it. And the answer "an account with this e-mail address already exists" necessarily tells
  that an address is registered, which the sign-in never does. Sign-up is therefore limited to 20 attempts per
  address in 10 minutes, refused attempts included, and every account created is written to the audit trail.
- An administrator is created by another administrator, on the command line, or at start-up from the
  bootstrap settings while the installation has none. If somebody has already signed up with the bootstrap
  address, that account is left as it is - promoting it would give administrator rights to whoever holds its
  password - and the server log says what to do.
- Passwords are hashed with **Argon2id** (argon2-cffi, its recommended parameters) and re-hashed when those
  parameters change. A password needs at least 12 characters, at most 256, no leading or trailing space, and at
  least 5 different characters.
- Every failed sign-in looks the same - "e-mail address or password is incorrect" - and takes the same effort:
  an unknown address is verified against a dummy hash, so timing does not reveal which addresses exist.
- **Throttling.** 5 failures per account and address within 5 minutes block further attempts (429); a wider
  limit applies per address across accounts. The account itself locks for 15 minutes, in the database, so the
  lock holds across server instances - and holds even for the right password.
- A demonstration account has no password and cannot sign in with one.

## Sessions

- A session is a signed token (JWT, HS256) holding the account, its role and an expiry; 60 minutes by default
  (`SOLARWISE_ACCESS_TOKEN_MINUTES`). The key is `SOLARWISE_SECRET_KEY`: at least 32 characters, mandatory in
  production. Without a key outside production a random one is used and sessions end when the process stops.
- On every request the account is read again: a deactivated account, or a demonstration account once
  demonstration mode is off, is refused immediately, whatever its token says.
- The web interface keeps the token in memory and in the browser's session storage - it ends with the tab and
  is never written to local storage - and sends it in the `Authorization` header and in `X-SolarWise-Token`. No cookie is used, so the API is not exposed to cross-site request forgery. The second
  header exists because some proxies remove or replace `Authorization`; the server logs a warning when it had to
  use it.
- A 30-second tolerance on the time claims absorbs a clock step on the server.
- Every refusal is logged with its reason (`401 on METHOD PATH: reason`, logger `solarwise.api`); the client
  only learns that authentication is required.

## Who may do what

Two levels, both checked on the server for every request.

| Account role | May |
|---|---|
| `ADMIN` | Everything, on every plant; manage accounts |
| `ENGINEER` | Register plants; work on the plants shared with them according to their plant role. The role of an account created by sign-up |
| `VIEWER` | Read the plants shared with them; never write, whatever the plant role |

| Plant role | May |
|---|---|
| `OWNER` | Everything on the plant, including deleting it and granting access |
| `EDITOR` | Import datasets, record evidence, run analyses |
| `VIEWER` | Read |

An unknown plant and a plant the account may not see give the same answer (404), so identifiers cannot be
probed. An administrator cannot deactivate or demote their own account.

## The demonstration

Demonstration mode lets anyone in without an account, so it is isolated:

- each visit gets its own throw-away account, removed after 24 hours (at most 500 are kept);
- a visitor reads the shared demonstration plant but cannot change what other visitors see; analyses a visitor
  runs are visible to that visitor only;
- everything a visitor creates is a demonstration: their plants are demonstration plants (the flag is one-way,
  even for an administrator), the evidence they enter is recorded as synthetic, and every decision is marked
  simulated - including for a file declared `MEASURED`;
- limits: 3 plants, 8 datasets per plant, 5 MB per upload; opening sessions, calling external services and
  asking the language model for anything are rate-limited, so that anonymous visitors can neither send
  unbounded traffic to third parties nor spend the operator's model budget. Events found in a file uploaded in a
  demonstration session are recorded as synthetic, like the evidence a visitor enters.

Turn demonstration mode off (`SOLARWISE_DEMO_MODE=false`) on an installation that holds real data and is
reachable by others.

An account created by sign-up is not a demonstration session, even on a server in demonstration mode: it does
not see the shared demonstration plant, the plants it registers are ordinary plants, and none of the limits
above applies to it.

## HTTP

Every response - refusals and failures included - carries:

| Header | Value |
|---|---|
| `Content-Security-Policy` | `default-src 'self'`; scripts from the same origin only; no objects; `frame-ancestors` as configured |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `no-referrer` |
| `Permissions-Policy` | camera, geolocation, microphone and payment disabled |
| `X-Frame-Options` | `SAMEORIGIN` or `DENY`, matching `frame-ancestors` |
| `Strict-Transport-Security` | one year, in production |
| `Cache-Control: no-store` | on everything under `/api/` |

- **Framing**: by default only the application itself may frame it. `SOLARWISE_FRAME_ANCESTORS` names other
  origins when the application must be shown inside another page.
- **CORS** is off unless `SOLARWISE_CORS_ORIGINS` lists origins; a wildcard is refused in production. The web
  interface does not need it: it is served from the same origin.
- **Host header**: `SOLARWISE_ALLOWED_HOSTS` restricts the host names the server answers to.
- **Body size**: a request larger than the upload limit is refused before it is buffered or parsed.
- **Errors**: one JSON shape; an unexpected error is logged with its cause and answered with a generic message.
- The interactive API documentation (`/api/docs`) loads its assets from a public CDN and has its own, wider
  policy for that page only.

## Uploads

- Files are parsed as data only: CSV or JSON, never executed, never written to disk under a name chosen by the
  client. Size, row and column limits apply (25 MB, 400,000 rows, 200 columns).
- Every value is validated against the declarations and physical ranges; what cannot be trusted is stored as
  missing.
- A stored dataset is immutable and identified by the SHA-256 of its content.
- **The uploaded file is kept**, compressed, in the database (`dataset_files`), with its own SHA-256, and can be
  downloaded by whoever may read the dataset. It is always sent back as an attachment of type
  `application/octet-stream`, under a file name reduced to letters, digits, dot, dash and underscore: a browser
  never renders it, whatever it contains. Deleting the plant deletes its files.
- The first look at a file (`preview`) and the review by the language model store nothing.
- The CSV of rejected rows gives the uploader's own cells back unchanged, except that a cell starting with `=` or
  `@` is prefixed with an apostrophe so that a spreadsheet does not run it as a formula. A leading plus or minus
  is left alone: those are numbers.
- Free text supplied by users (plant names, descriptions, sources) is escaped in every report; the HTML reports
  are rendered with auto-escaping.

## Integrity of the results

Part of security here is that a result cannot claim more than its evidence supports:

- the evaluation context is decided on the server, never by the client;
- synthetic, modelled and unknown-origin data cannot lead to an operational `CLEAN_NOW`; a final interlock
  re-checks every cleaning decision;
- an analysis is stored as issued, with the engine version, the options and the content hash of its dataset;
- state-changing actions are recorded in an audit trail with the account and the remote address.

## The language model

Off by default. The complete description is in [ai.md](ai.md); what matters for security:

- **The key stays on the server.** It is read from the environment, held in memory and sent to the provider only.
  No response of the API contains it, the interface has no setting for it, and it is written nowhere: not to the
  database, not to the audit trail, not to a stored insight, not to a report, not to the log. A provider's error
  is reported by its status only; the body of its answer, which may echo the request, is never passed on. Tests
  look for the key in every answer, stored row and log line.
- **The model has no power.** It has no tool and no access to the database; nothing it returns is executed. The
  decision, the gates, the rating of each cause, the evidence, the steps and every figure of an insight are
  copied from the stored analysis by the server: a model's answer has no field for them.
- **What it writes is checked** before it is shown: the requested structure, then ten checks against the engine's
  result (length, figures from the engine only, no certainty the engine does not state, no other decision, no
  soiling stated as a fact without measured evidence, no recoverable energy the engine did not estimate, synthetic
  data never called measurements, no claimed validation or authorisation, plain text, no anomaly of the engine
  passed over). One failure discards the whole
  answer; the engine's own text is shown, with the reason.
- **What is sent** to the provider is bounded: for an analysis, the findings of the engine as plain data - no time
  series, no file, no account; for an uploaded file, column names, counts, extremes and at most five sample values
  per column. Free text from users is stripped of control characters, bounded, and kept in a data channel apart
  from the instructions; a model that obeys an instruction hidden in it is caught by the checks.
- **Suggestions for a mapping are never applied by the server**, never name a provenance and never change a value.
  What the uploader accepts goes through the same validation as anything typed by hand.
- **Traceability**: every generated insight is stored with provider, model, time, the version of the prompt, the
  fingerprint of the evidence it was written from and the result of every check; generating one is recorded in
  the audit trail.
- **Availability**: a provider that is slow, unreachable, rate-limited or wrong leaves the engine's text; the
  request of the user succeeds. Demonstration visitors share a bounded allowance of model calls.
- If nothing about a plant may leave your network, use a model served on your own machines, or leave the layer off.

## Left to the installation

| Topic | State |
|---|---|
| TLS | Not terminated by the application: put a reverse proxy in front and start with `--proxy-headers` |
| Secrets | Read from the environment or `.env`; `.env` is git-ignored; nothing secret has a usable default in production |
| Verification of e-mail addresses | Not implemented: the application sends no mail. Close sign-up where the identity of account holders matters |
| Password change and reset | Not implemented: an administrator deactivates the account and creates a new one |
| Multi-factor authentication, single sign-on | Not implemented |
| Rate limiting | In the memory of one process: adequate for a single instance; several instances need a limit at the proxy. The per-account lock is in the database and stays effective |
| Token revocation | A token stays valid until it expires unless the account is deactivated |
| Backups, log retention, monitoring | To be organised by the operator |
| Independent security review | None has been made |

`solarwise check-config` shows the effective configuration and warns about weak settings.
