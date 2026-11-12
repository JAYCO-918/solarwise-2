# SolarWise DZ - speaker script

Written by `presentation/src/build.cjs` from the notes in `presentation/src/deck.html`. Edit the notes there, not this file.

**11 slides, 5:00 planned, 622 words to say** - that is 124 words a minute, a calm pace. The same text is in the notes pane of the PowerPoint file and behind the `N` key of the HTML version.

| # | Slide | From | To | Seconds | Words |
|---|---|---|---|---|---|
| 1 | Title | 0:00 | 0:15 | 15 | 28 |
| 2 | The problem | 0:15 | 0:50 | 35 | 97 |
| 3 | The solution | 0:50 | 1:25 | 35 | 72 |
| 4 | Why: the bridge | 1:25 | 1:55 | 30 | 65 |
| 5 | Ten gates | 1:55 | 2:30 | 35 | 70 |
| 6 | Same symptom, different answers | 2:30 | 3:10 | 40 | 74 |
| 7 | Does cleaning pay? | 3:10 | 3:40 | 30 | 66 |
| 8 | Four rules | 3:40 | 4:05 | 25 | 53 |
| 9 | Where we are | 4:05 | 4:30 | 25 | 45 |
| 10 | Next steps and what we ask | 4:30 | 4:55 | 25 | 42 |
| 11 | Close | 4:55 | 5:00 | 5 | 10 |

## What to say

### 1. Title (0:00 to 0:15)

*Introduce yourself in one sentence, then:*

This is SolarWise DZ. It tells the operator of a solar plant why the plant is producing less than expected, before anyone decides to send the cleaning crews.


### 2. The problem (0:15 to 0:50)

On the 26th of October, Algeria inaugurated El Foulia, its largest solar plant: 300 megawatts in El Oued. And in the Sahara, dust is real. At Ouargla, researchers measured 8 percent less power after only eight weeks without cleaning.

Now picture the control room. Production is 9 percent below expected. Is it dust? Maybe. But heat, an inverter fault, shading, grid curtailment or bad data look exactly the same on the meter.

Clean for the wrong reason, and you spend water and money for nothing. Wait when it really is dust, and you lose energy every day.


### 3. The solution (0:50 to 1:25)

SolarWise DZ answers three questions, in order.

One: how much is really missing, against a documented baseline and beyond the measurement uncertainty.

Two: why. Each cause is quantified only from data that actually measure it. What we cannot explain stays “unexplained”.

Three: does cleaning pay. The energy we would recover, against the full cost of cleaning.

The result is one of three answers: clean now, investigate, or monitor. Always with its reasons.


### 4. Why: the bridge (1:25 to 1:55)

Here is the second question, on a simulated case. Expected energy on the left, actual energy on the right.

The soiling sensor reads eight and a half percent. The loss left to explain, once equipment is removed, is eight point four. They agree. And only a tenth of a percent stays unexplained.

The key point: soiling is measured. It is never guessed from the gap.


### 5. Ten gates (1:55 to 2:30)

Then comes the decision. A cleaning order has to pass ten gates: reliable measured data, a real loss, credible soiling evidence that matches this loss, nothing else open, and economics that hold in the conservative case.

Ten out of ten: clean now. Anything less: investigate, or monitor.

These are explicit rules, not a black box. Same data, same answer. And an independent check verifies every cleaning order a second time.


### 6. Same symptom, different answers (2:30 to 3:10)

So what does it change? Here are six simulated cases, all with about nine percent less production. A simple threshold would clean six times.

SolarWise DZ says clean once: when the dust is measured and the cleaning pays.

Heat, or curtailment: cleaning changes nothing, so we monitor. An inverter fault: repair it first. Shading, or evidence that contradicts itself: investigate.

Five needless cleanings avoided. And each time, the operator knows what to do instead.


### 7. Does cleaning pay? (3:10 to 3:40)

And even real dust does not always justify a cleaning. The cleaning cost is the same in both cases.

On the left, dry weeks ahead: the cleaning recovers about four times its cost. Clean now.

On the right, rain is expected within days: the cleaning would lose money. So we wait.

The prices are the operator's own: nothing is built in. The figures here are illustrative.


### 8. Four rules (3:40 to 4:05)

Why trust the answer? Because of four rules the software never breaks.

A gap is not a diagnosis. Every value carries its origin, and only measured data can justify a cleaning. Rules decide: an AI model may only rephrase the explanation. And a missing value stays missing: it is never replaced by zero.

*If you are short of time, this is the slide to shorten: read the four titles only.*


### 9. Where we are (4:05 to 4:30)

And this is a working application, not a mock-up. A web interface and an API. Ten demonstration scenarios. More than eight hundred automated tests. Reports in four formats.

We are also clear about its limit: so far, it has been validated on synthetic data only.

*If you may show the live demonstration, do it here: open the demonstration, then the plant, then the analysis “Confirmed soiling”.*


### 10. Next steps and what we ask (4:30 to 4:55)

So the next step is a pilot. One plant's historical data, to calibrate the thresholds with its engineers. Then soiling stations, weather feeds, and more plants.

That is what we are looking for today: an operator ready to test it with us.


### 11. Close (4:55 to 5:00)

SolarWise DZ. Clean when the evidence says so. Thank you.

*Leave this slide on the screen during the questions. The slides after it are backups.*


## Backup slides (only if a question calls for them)

### 12. Backup: the rules, in order

*Use it when someone asks “how exactly is the decision taken?” or “why not machine learning?”.*

The rules are checked in this order, and the first that applies decides. Only rule R3 can order a cleaning, and it needs all ten gates. A second, independent check must agree before the order goes out.


### 13. Backup: how it is built

*Use it for technical questions: stack, deployment, security.*

A file goes in with a declaration of each column. It is validated, then five engines compute the gap, the causes, the diagnosis, the recoverable energy and the economics. The rule engine decides. The result is stored as issued and can be exported as a report.


### 14. Backup: the ten demonstration scenarios

*Use it when someone asks what the demonstration contains, or wants to see a case you did not show.*

Scenario 9 uses the same numbers as scenario 2, but the file does not say that they stand for measurements. The answer changes from “clean now” to “investigate”: data of unknown origin can never justify a cleaning.


### 15. Backup: limits, stated plainly

*Use it when someone asks about real data, accuracy or validation. Saying these limits yourself is stronger than being asked.*

We have not used real plant data yet: that is exactly what the pilot is for. And the software will never order a cleaning without a direct soiling measurement.


## Three numbers to keep in your head

- **9 %**: the drop that every case on slide 6 shares.
- **10**: the gates a cleaning order has to pass.
- **1 in 6**: the cleanings that were justified.

If you forget everything else, say: *"Six cases, the same 9 % drop, one cleaning justified. SolarWise DZ tells which
one, and shows the evidence."*

## If you are short of time

| You have | Show |
|---|---|
| 5 minutes | slides 1 to 11, as written |
| 4 minutes | on slide 8 read the four titles only; on slide 9 say one sentence |
| 3 minutes | slides 1, 2, 3, 6, 10, 11 |
| 1 minute | slide 6, then slide 11 |

## Optional: 40 seconds of the real application

Only if the room allows it and the application is already open in a browser tab before you start. It replaces what
you say on slide 9. How to start the application is in `README.md` at the root of the repository.

1. On the sign-in page, click **Open the demonstration**. No account is needed.
2. Click the plant **El Foulia reference case (synthetic data)**.
3. In the row **02 · Confirmed soiling**, click the green **Clean now** badge: it opens the analysis.
4. Show the decision: **Clean now**, marked *simulated*, with its reasons. Scroll to **Gates: 10 of 10 passed**.
5. Click the tab **Attribution**: this is the chart of slide 4, drawn by the application.
6. Go back to the slides for slide 10.

Say while you click: *"This is the same case as on the slides, in the application. The decision, its reasons, the ten
gates, and where every number comes from."*

If anything fails, do not debug in front of the room: say "the screenshots on the slide come from this application"
and go on. Slide 9 shows the same page.

## Questions you should expect

**Are these real data from El Foulia?**
No. Every figure in the demonstration is synthetic: it is produced by a scenario generator from a fixed seed. Only
the name, the location and the nominal capacity of the plant are real, and they are public. The application marks
every such decision as *simulated*. (Backup slide 15.)

**Why rules, and not machine learning?**
Because a cleaning order costs water and money, so it has to be explained and checked. With rules, the same data
always give the same answer and every gate can be audited. And a production gap alone cannot tell dust from heat or
from a fault, whatever the model: the missing information has to be measured. (Backup slide 12.)

**What does the AI do, then?**
It is optional and switched off by default. When it is on, a language model may only rephrase the explanation that
the engine has already written. Its text is checked against the engine's figures before it is shown, and thrown
away if a number or the decision does not match.

**What if the plant has no soiling sensor?**
Then the software does not order a cleaning: it answers "Investigate" and says which measurement is missing. A
soiling station, a clean reference module, a comparison of strings, an I-V curve or an optical sensor all count as
direct measurements. A visual estimate does not.

**Where does the "expected energy" come from?**
From a baseline whose method is declared: the operator's own expected energy, a model fed with the plant's
telemetry, a clean period of the plant's own history, an engineering model computed from irradiance and
temperature, or a typical year from PVGIS. An undocumented baseline fails the second gate.

**How do you know the thresholds are right?**
They are documented defaults, for example a 7-day window and a 2 % floor for a credible soiling reading. They are
published in the application and have to be calibrated with each operator. That is the purpose of the pilot.

**How is it different from the monitoring system the plant already has?**
A monitoring system shows that production is below expected. SolarWise DZ says why, with what evidence, whether a
cleaning would pay, and what to do instead when it would not.

**How much water or money does it save?**
We do not claim a figure yet: that needs the data of a real plant. What the demonstration shows is the mechanism: in
six cases with the same drop, five cleanings were not justified. In the two economic cases, one cleaning earns about
14 million dinars and the other would lose about 3 million, with illustrative prices.

**What do you need for a pilot?**
Time series of the energy really produced and of the expected energy (or irradiance and temperature to compute it),
the availability of the equipment, curtailment records, soiling measurements, the maintenance log, and the
operator's own cleaning costs. CSV or JSON files are enough.

**Can it run on the operator's own servers?**
Yes. It is one web application with its database. The operator can switch sign-up off, so that only an
administrator creates accounts; each plant has its own owners, editors and viewers; and sign-ins, imports,
analyses and exports are recorded. The connections to outside services are optional and can stay switched off.
(Backup slide 13.)

**Who pays for it, and how?**
The product does not answer this: decide your own answer before the pitch. A simple and defensible one is "the
operator of the plant, per plant and per year, because each avoided needless cleaning and each justified one has a
value we can show on the economics page".

**In which languages?**
The interface is in English today. Arabic and French are on the roadmap (slide 10).

## Words you will say

| Word | Meaning | Say it |
|---|---|---|
| soiling | dust and dirt on the modules | SOY-ling |
| curtailment | the grid operator limits what the plant may inject | kur-TAYL-ment |
| baseline | the energy the plant was expected to produce | BAYSS-line |
| gate | one condition that must be true before a cleaning is ordered | |
| El Foulia | 300 MWp plant at Guemar, El Oued: the reference case | |
