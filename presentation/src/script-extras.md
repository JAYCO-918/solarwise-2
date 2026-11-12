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
