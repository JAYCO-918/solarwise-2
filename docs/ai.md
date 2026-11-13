# The language-model layer

SolarWise DZ can use a language model to **interpret and explain** what its engineering engine found. This
document says what the model does, what it cannot do, how that is enforced, how to configure a provider, and what
has and has not been verified.

> **What was tested.** The whole path - configuration, request, answer, checks, storage, display - is tested against a
> *stand-in*: a local server that speaks the OpenAI chat-completions protocol and gives scripted answers. **No real
> provider and no real model were called**, because none was available where the software was built. That a given
> provider and model work well with it remains to be tried by whoever configures one; see
> [Trying a real provider](#trying-a-real-provider).

## The rule

**The deterministic engine is the only authority for a recommendation.** A language model reads the engine's
result and writes about it. It never decides, never supplies a fact, and never acts: it has no tool, no access to the
database, and nothing it returns is executed. Without a model the product is complete - every page that can show a
model's text shows the engine's own instead, and says so.

## What the model is used for

| Capability | Where | What the model writes | What stays the engine's |
|---|---|---|---|
| **Diagnostic analysis** | analysis page, tab *AI analysis*; `POST /analyses/{analysis_id}/insight` | summary, reading of the performance, anomalies, an interpretation of each possible cause, assessment of the data, economic implications, what is uncertain | the decision, the gates, the support given to each cause, the evidence for and against it, every figure |
| **Explanation of the decision** | same tab: *Why the engine decided this*, *Recommended next steps*, *Information that is missing* | why the engine reached its result; which of the engine's steps and missing inputs matter most, and why | the steps and the missing inputs themselves (the model chooses among them by identifier and cannot add one); the gates; what would change the decision |
| **Operational report** | same tab, *Operational report*: PDF, HTML, JSON; `GET /analyses/{analysis_id}/operational-report.{fmt}` | the narrative of its eight sections | the decision box, the gates, the annex tables |
| **Review of an uploaded file** | upload page, *Second reading by the AI assistant*; `POST /plants/{plant_id}/datasets/ai-review` | suggestions for columns the reader could not place, remarks on the values, context that is missing | the mapping (a suggestion is applied only when the uploader accepts it), the validation, every value |
| **Plain-language rewording** | analysis page, tab *Explanation*; `POST /analyses/{analysis_id}/explanation` | a rewording of the engine's explanation | the explanation itself |

The eight sections of the operational report: executive summary; plant performance overview; main detected
anomalies; evidence-based diagnostic analysis; data-quality assessment; economic implications; recommended actions;
limitations and uncertainty. Each section says who wrote it.

The diagnostic analysis treats eight possible explanations, each with the rating the engine gave it: soiling,
thermal effects, irradiance, equipment or inverter, shading, curtailment or outage, data quality, and the unexplained
remainder.

## How it works

```
 stored analysis ──► evidence packet ──► provider ──► answer
 (engine result)     (plain data: the     (HTTPS,      │
                      findings, and the    no SDK)      ▼
                      list of numbers                structure check ── not the requested JSON ──┐
                      that may be quoted)               │                                        │
                                                        ▼                                        │
                                                    ten checks against ── one fails ─────────────┤
                                                    the engine's result                          │
                                                        │ all pass                               ▼
                                                        ▼                              the engine's own text,
 decision, gates, ratings, evidence,  ──────────►   insight   ◄───────────────────────  same structure,
 steps, figures: copied by the server              (stored)                             labelled as such
```

1. **The packet** (`solarwise/ai/packet.py`). The stored result of the analysis is restated as plain data: the
   decision with its rule and reasons, the ten gates, expected and actual energy and the gap, the attribution of
   losses, the trend, each possible cause with its rating and evidence, conflicts, technical issues, the soiling
   measurement, recoverable energy, economics, data quality, the provenance of each channel, the thresholds, and the
   candidate steps and missing inputs the engine named. About 20,000 characters. **No time series, no row of the
   uploaded file, no account, no key.** Text typed by users (plant name, sources) is stripped of control characters
   and bounded; the system prompt states that the packet is data, not instructions.
2. **The request** (`solarwise/ai/providers.py`). One call, temperature 0, bounded output. No vendor SDK: plain
   HTTPS with the shared client of the server.
3. **The structure check** (`solarwise/ai/analyst.py`). The answer has to be one JSON object with the requested
   fields, types and lengths. Steps and missing inputs are given by identifier; an identifier the engine did not
   propose, or a cause the engine did not evaluate, makes the answer malformed.
4. **The checks** (`solarwise/ai/guardrails.py`). Everything the model wrote, taken together, goes through ten
   checks. One failure discards the **whole** answer.
5. **The insight.** The server assembles it: the facts are copied from the engine's result by code, the narrative
   is the model's - or, when anything failed, the engine's own sentences in the same structure.

### What a model cannot change, by construction

The following fields of an insight are filled by the server from the stored analysis. A model's answer has no field
for them; if it returns one, it is not read.

`decision` (value, rule, reason, headline, simulated, operational authorisation, the sentence that states it) ·
`gates` · `decisive_evidence` · `what_would_change` · for each cause: its rating, the engine's summary, evidence for
and against, missing evidence, estimated loss · the text of every step and of every missing input ·
`data_quality_status` · `economics_status` · `economics_decision_grade`

### The eleven checks on a narrative

The structure check, then ten checks of the text against the engine's result.

| Check | Discards an answer that ... |
|---|---|
| `requested_structure` | is not the requested JSON object, or names a step, a missing input or a cause the engine did not provide |
| `length` | is shorter than 200 or longer than 9,000 characters in all |
| `figures_from_engine_only` | quotes a number - a percentage, an energy, a date - that is not in the packet (rounding is allowed) |
| `no_overclaiming` | states a probability, a confidence percentage or a certainty ("definitely", "proven") |
| `consistent_with_decision` | urges or discourages cleaning against the decision, or names another decision than the engine's |
| `soiling_not_asserted_without_measurement` | states soiling as a fact ("caused by soiling", "the modules are dirty") while the engine holds no credible measured soiling evidence |
| `no_recoverable_energy_without_estimate` | quotes a figure for recoverable energy while the engine estimated none |
| `synthetic_not_called_measured` | speaks of measurements without saying they are synthetic, when the data are synthetic |
| `no_validation_or_authorisation_claim` | claims a validation on a real plant, or an authorisation the engine did not give |
| `plain_text_only` | contains a link, mark-up or commentary about itself |
| `anomalies_not_omitted` | lists no anomaly while the engine's findings contain some |

Negations and hedges are understood: "soiling is not shown", "the gap may be due to soiling", "the method has not
been validated on a real plant" pass. So does a confirmation that is asked for and not claimed: "a proxy until
confirmed on site", "must be verified on site".

The last check exists because an empty list of anomalies is displayed as "the findings contain no anomaly": only
the engine may say that. The packet holds the engine's own list - open technical issues, an abrupt drop of the
performance index, critical contradictions in the evidence, a material unexplained remainder, every cause rated as
supported and present in the assessment window - and a narrative may word those in its own way, not pass them over.

The checks are **patterns**. They catch the overreaches listed above, reliably and mechanically. They do not
verify that every sentence is true. A model can still write something vague, unhelpful, or subtly wrong in a way no
pattern describes - which is why every fact that matters is copied by the server and not left to the narrative, and
why each section of the page says who wrote it.

They are also strict: a correct narrative can be rejected (a number the model computed itself, the word
"measurement" on synthetic data). That costs nothing: the engine's text is shown.

### The review of an uploaded file

`solarwise/ai/data_assist.py`. The model is given, for each column: its name, how many cells are filled, empty and
numeric, the smallest and largest value, and **at most five sample values** - plus what the deterministic reader
proposed and the list of quantities with the units each accepts. Not the file.

Each suggestion is checked: the column exists; the role exists; the quantity can be assigned to a column; the unit
is a unit of that quantity; a column of text is not proposed as a quantity; the reason given does not claim a
provenance and does not propose to change values. A remark on the values may only quote numbers that are in the
summary. Whatever fails is discarded and listed. **The server applies nothing**: an accepted suggestion changes the
mapping form in the browser, the uploader still declares the provenance, and the file is validated exactly as any
other.

## Without a model

`SOLARWISE_AI_PROVIDER=none` is the default. Then:

* the *AI analysis* tab shows the insight assembled by the engine from its own findings, with the notice "No
  language model is configured on this server ... the deterministic fallback is active", and every section is marked
  **Engine**;
* the operational report is produced from the same text and says "No language model was used";
* the assistant of the upload page is switched off, and the page says the deterministic reading is complete;
* the *Explanation* tab shows the engine's explanation.

The same fallback applies, per request, when a model is configured and its answer cannot be used. The page then
says that a model was asked, which one, and why its answer was not used.

## What is kept

Every generated insight is stored (`ai_insights`): the analysis it reads, who asked, when, `AI` or
`DETERMINISTIC_ENGINE`, provider and model, the version of the prompt, the SHA-256 of the evidence packet, how long
the provider took, the reason of a fallback, the result of every check, and the complete content. The ten latest per
analysis are kept. An insight never modifies the analysis: decision, rule and result are what they were.

The audit trail records `AI_INSIGHT_GENERATED`, `AI_DATA_REVIEW` and `OPERATIONAL_REPORT_EXPORTED` with provider,
model and whether the engine's text was used instead. Reading an insight or exporting a report calls no model.

## Configuration

Environment variables, read by the server at start-up.

| Variable | Default | Meaning |
|---|---|---|
| `SOLARWISE_AI_PROVIDER` | `none` | `none`, `openai-compatible` (or its synonym `openai`), `anthropic` |
| `SOLARWISE_AI_MODEL` | - | name of the model, as the provider calls it. Required for the layer to be on |
| `SOLARWISE_AI_API_KEY` | - | key of the provider. Required, except for an OpenAI-compatible service named by `SOLARWISE_AI_BASE_URL` that takes none |
| `SOLARWISE_AI_BASE_URL` | the provider's public address | root of the service: `.../v1` for the OpenAI protocol (`/chat/completions` is appended), the host for Anthropic (`/v1/messages` is appended) |
| `SOLARWISE_AI_TIMEOUT_SECONDS` | `30` | time limit of one call |
| `SOLARWISE_AI_MAX_OUTPUT_TOKENS` | `2000` | upper bound of one answer |
| `SOLARWISE_AI_MAX_RETRIES` | `1` | further attempts after a rate limit (429), a gateway error (502, 503, 504) or a failed connection. A timeout is not attempted again |
| `SOLARWISE_AI_JSON_MODE` | `false` | ask an OpenAI-compatible service for a JSON object (`response_format`). Off by default: not every service accepts it, and the answer is parsed and checked either way |

`openai-compatible` is the protocol, not the company: any service that implements `POST {base}/chat/completions`
with `model`, `messages`, `temperature` and `max_tokens` and answers with `choices[0].message.content`. Changing
provider is a change of these variables; nothing else in the application depends on it.

Examples of settings. None of them was run against the service it names.

```sh
# A commercial API speaking the OpenAI protocol
SOLARWISE_AI_PROVIDER=openai-compatible
SOLARWISE_AI_API_KEY=...            # from the provider
SOLARWISE_AI_MODEL=...              # a chat model of that provider

# A gateway, or a model served on your own machines, speaking the same protocol
SOLARWISE_AI_PROVIDER=openai-compatible
SOLARWISE_AI_BASE_URL=http://model-server.internal:8000/v1
SOLARWISE_AI_MODEL=...
# SOLARWISE_AI_API_KEY may be left out when the service takes none

# Anthropic
SOLARWISE_AI_PROVIDER=anthropic
SOLARWISE_AI_API_KEY=...
SOLARWISE_AI_MODEL=...
```

`GET /api/v1/ai/status` (signed in) says whether a model is configured, which, and on which host - never the key.
`solarwise check-config` prints the same on the command line.

## The key

* It is read from the environment by the server and held in memory. It is sent to one place: the provider, in the
  `Authorization` header (`x-api-key` for Anthropic).
* It is never sent to the browser: no response of the API contains it, and the interface has no setting for it.
* It is never written: not to the database, not to the audit trail, not to an insight, not to a report, not to the
  log. Errors of a provider are reported by their status only - the body of the provider's answer, which may echo
  the request, is never passed on.
* Tests look for it in every answer, stored row and log line after calls that succeed and calls that fail
  (`backend/tests/api/test_ai_api.py`, and the browser check `upload_flow.cjs` with `AI=stub`).

Keep it out of the repository: `.env` files are ignored by Git; in production use the secret store of the platform.

## What is sent to the provider

For an analysis: the evidence packet described above - findings of the engine about one plant and one period,
including the plant's name and capacity and the names of the sources declared for its data. For a file: column
names, counts, minimum and maximum, and up to five sample values per column.

Nothing else: no time series, no file, no account, no e-mail address. If even that may not leave your network, use a
model served on your own machines, or leave the layer off.

## When the provider fails

| What happens | What the server does | What the user sees |
|---|---|---|
| No answer within the time limit | gives up; not attempted again | engine's text; "did not answer within the time limit" |
| Cannot be reached | one more attempt (configurable), then gives up | engine's text; "could not be reached" |
| Rate limit or quota (429) | waits what the provider asks, at most 4 s, tries once more | engine's text; "its rate limit or quota is reached" |
| Gateway error (502, 503, 504) | tries once more | engine's text; "answered HTTP 503" |
| Key refused (401, 403) | not attempted again | engine's text; "refused the credentials" |
| Answer that is not what the protocol promises | - | engine's text; "did not answer with JSON" and the like |
| Answer that is not the requested structure | - | engine's text; what was wrong with it |
| Answer that fails a check | - | engine's text; the name of the check and what it found |

In every case the request of the user succeeds, the rest of the page is unaffected, and what was asked - provider,
model, reason - is stored with the insight.

## Who may ask

* Generating an insight needs an account that may run analyses; a read-only account can read insights and export
  reports.
* Demonstration visitors share an allowance of 20 model calls per 10 minutes per address; beyond it they get the
  engine's text. This keeps anonymous visitors from spending the operator's budget.

## Limitations

* **No real provider was called.** See the note at the top.
* **The quality of the narrative is the model's.** The checks keep it within bounds; they do not make it good. A
  weak model may be rejected most of the time, and the page will then show the engine's text most of the time.
* **English only.** Prompts, checks and narrative are in English. The checks would not recognise an overreach
  written in another language; a narrative in another language is likely to be rejected by the checks on figures
  and structure, but that is not a guarantee.
* **Cost and delay are not measured.** One generation is one call with a prompt of roughly 6,000 tokens and an
  answer of up to 2,000; what that costs and how long it takes depends on the provider.
* **No streaming.** The page waits for the whole answer, at most the time limit.
* **The assistant of the upload page sees samples**, five values per column. It can miss what only shows further
  down the file. The deterministic reader and the validator read the whole file.
* **The event vocabulary is fixed.** An alarm text the vocabulary does not know is kept as "other" and does not
  enter the diagnosis; the model is not asked to classify alarms.

## Trying a real provider

1. Set the variables above and restart the server. `GET /api/v1/ai/status` should answer `"enabled": true`.
2. Open the demonstration, an analysis, the tab *AI analysis*, and press **Generate the AI analysis**.
3. Read the origin line: *Narrative written by a language model*, with the model's name - or the warning that its
   answer was not used, and why. A check that fails often points to the prompt or the model, not to the plant.
4. Try the ten demonstration scenarios: they cover each decision, synthetic data, missing data and contradictory
   evidence.
5. On the upload page, try *Ask the AI assistant* with `data/samples/solarwise-operational-data.example.csv` after
   renaming a header to an abbreviation.

## Tests

| What | Where |
|---|---|
| Packet: restates the engine, carries no series, bounds user text | `backend/tests/ai/test_analyst.py` |
| Insight without a model, on every scenario | same |
| A faithful narrative is accepted; facts stay the engine's whatever the model returns | same |
| Sixteen kinds of overreach are discarded whole; twelve kinds of malformed answer | same |
| Negations and hedges are not mistaken for claims; an instruction hidden in the data is caught | same |
| Synthetic data never reach an operational Clean now, with or without a narrative | same, and `backend/tests/api/test_upload_workflow_api.py` |
| The OpenAI protocol over a real connection: request, key, retries on 429 and 503, no retry on 401, timeout, unreachable, malformed replies | same |
| The review of a file: what is sent, what is discarded, nothing applied | `backend/tests/ai/test_data_assist.py` |
| The API: status, storage, fallback, report, access, allowance of visitors, the key appears nowhere | `backend/tests/api/test_ai_api.py` |
| The operational report | `backend/tests/reports/test_operational_report.py` |
| The interface: who wrote what, fallback notice, suggestions applied only when accepted | `frontend/src/components/analysis/AiAnalysisPanel.test.tsx`, `frontend/src/pages/UploadPage.test.tsx` |
| In a browser, with and without the stand-in | `frontend/e2e/upload_flow.cjs` |
