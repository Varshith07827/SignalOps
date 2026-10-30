# 1213 · R5: Voice-of-Store Engine

Turns 40k messy, multilingual store-feedback records into a routed, prioritised weekly action list per region,
and flags store-level problems while they are still small.

## The problem, as a story

Saffron Retail runs 60 grocery stores across five regions of India, plus an app and a website.\
Every week about 1,500 messages come in: online reviews, app comments, staff shift notes and call-centre calls.\
They are written in English, Hinglish, Tamil and Marathi, full of typos, emojis and shop-floor shorthand like "frzr down".\
Somewhere in that pile, a freezer at one store starts failing: two notes one week, four the next, then five.\
Nobody at head office notices, because each complaint looks like noise among thousands of others.\
By the time the chain-wide numbers jump, the ice cream has melted, stock is lost and customers have gone elsewhere.\
Another week, an app outage brings hundreds of complaints from every store: loud, but not one store's problem.\
Head office needs to tell these two apart and act on the right one, fast.\
That is the job of the Voice-of-Store Engine (problem statement R5).\
It reads every message and decides what it is about, how serious it is, and whether someone can act on it.\
It sends each problem to the team that owns it (Store Ops, Supply Chain, Merchandising, Digital or HR) with a deadline.\
Every week it writes a one-page brief per region: top 5 issues, real customer quotes, affected stores and a trend arrow.\
It raises an early warning when one store gets more of one problem than its size explains, before it spreads.\
Each warning uses only feedback up to that week's Sunday and cites at least two real messages as proof.\
So managers stop drowning in chatter and start each week with a short action list they can trust.

## What it does

Saffron Retail's head office receives online reviews, in-app comments, staff shift notes and call-centre
transcripts in English, Hinglish, transliterated Tamil and Marathi. The engine:

1. **Classifies every record**: issue type (30 operational types + 3 non-issues), severity (low → critical)
   and an actionable flag.
2. **Routes** every actionable record to its owning function (Store Ops, Supply Chain, Merchandising, Digital,
   HR) with an escalation tier and response SLA.
3. **Detects emerging issues**: a weekly, causal detector that flags a (store, issue) pair that is small in
   absolute volume but rising sharply, *before* the chain-wide count would show it.
4. **De-duplicates** the same incident reported through several channels (stretch goal), so briefs count
   incidents, not messages.
5. **Writes a one-page brief per region per week**: top 5 issues, owner, severity, escalation, evidence quotes,
   affected stores and a trend arrow against last week.

Users: regional managers and function heads read the briefs and owner queues in the dashboard; the
emerging-issue flags go to the regional manager.

## Results

| | This engine | Pack baseline |
|---|---|---|
| Classification, **5-fold cross-validated** (official formula) | **0.939** | 0.579 |
| — issue-type macro-F1 / severity weighted-F1 / actionable F1 | 0.934 / 0.926 / 0.963 | 0.559 / 0.448 / 0.751 |
| Lead score on the public worked example (EX-1) | 0.667 (+2 weeks, flag 2026-05-04) | 0.333 (+0) |
| Flags per week (budget 3) | 1.15 (train half), 1.85 (test half) | 2.08 |
| `evaluate.py` primary score vs training labels | 0.866 | 0.481 |

The `evaluate.py` run scores the training labels in-sample (classification 0.999), so the **cross-validated
0.939 is the honest estimate** for the hidden split. The best possible lead on EX-1 is +3, but that needs a
flag in the onset week, which held only one report at the store (the evidence rule needs two).

**Precision statement** (out-of-fold, 5-fold CV on the 3,000 labelled records): of the records we marked
actionable, **96.0%** truly were (1,785 marked); of those we marked actionable *and* high/critical (our
escalations), **95.6%** were truly actionable (410 escalated). The in-sample figures from `evaluate.py`
(99.8% / 99.8%) are optimistic.

## How to run

Needs Python ≥ 3.11. From the project root (the folder holding this README):

```bash
cd FULL_CODE
uv sync                      # or: pip install numpy pandas scikit-learn scipy fastapi uvicorn python-multipart pytest
cd ..
```

**Where to put the data:** copy the pack's `data/*.csv` files (feedback, labels, store master, taxonomy, week
calendar, incident example) into `FULL_CODE/data/`. That folder is git-ignored and never committed.

```bash
python FULL_CODE/main.py --cv                 # submission/ files, outputs/, briefs, CV report (~2.5 min)
python FULL_CODE/serve.py                     # dashboard at http://127.0.0.1:8000 (--port 8001 if 8000 is busy)
```

The dashboard is one page (plain HTML/CSS/JavaScript served by a small FastAPI backend). It opens on the
R5 dataset in `FULL_CODE/data/`. **Upload** analyses another feedback CSV with the same columns as
`feedback.csv` (for example a newer week of feedback); the model is trained on the dataset's labelled records,
and stores and taxonomy also come from `FULL_CODE/data/`. **Back to R5 dataset** appears after an upload.
Pick a week and a region to see:

* this week's numbers: messages, need action, urgent, early warnings;
* the region's **top 5 issues**: team, severity, what to do, cases, trend vs last week, stores, two quotes;
* every **early warning** with the store, problem, team, number of reports and an example message;
* **who must act this week** (routing by team and severity) and **when to escalate** (the escalation rule);
* the **official score**: **Run evaluate.py** runs the organisers' scorer on `submission/` against the labelled
  weeks and shows the primary score, its parts, the early-warning incidents and the precision statement;
  **Download report** saves the same results (plus the full scorer output) as an HTML file. Set
  `[evaluation] evaluator_path` in `FULL_CODE/config.toml` if `evaluate.py` is not in `R5_Voice_of_Store_Engine/`;
* **how accurate it is** (cross-validated scores and the precision statement).

Uploads are checked for type, size (`[server] max_upload_mb`), columns and values before analysis; the server
listens on 127.0.0.1 only, and data text is shown as plain text, never as HTML. The page uses the Archivo web
font (Google Fonts) when online and falls back to system fonts offline; everything else is served locally.

`main.py` writes:

* `submission/R5_predictions.csv`, `submission/R5_emerging_flags.csv`, `submission/detector_cmd.txt`;
* `FULL_CODE/outputs/records.csv` (every record with predictions, routing, language, incident id),
  `flags.csv`, `briefs/<week>/<region>.md` and `cv_report.json`.

The detector command (also in `submission/detector_cmd.txt`), run from the project root:

```bash
python FULL_CODE/detect.py --feedback FULL_CODE/data/feedback.csv --as-of 2026-07-13 --out FULL_CODE/outputs/week.csv
```

To score with the organisers' scorer, with the problem pack folder `R5_Voice_of_Store_Engine/` placed in the
project root (it is git-ignored):

```bash
python R5_Voice_of_Store_Engine/evaluate.py --submission submission/R5_predictions.csv --truth FULL_CODE/data/feedback_labels_train.csv --feedback FULL_CODE/data/feedback.csv --stores FULL_CODE/data/store_master.csv
```

**Environment variables** (optional, see `FULL_CODE/.env.example`): `VOS_CONFIG` points to another settings
file, `VOS_LOG_LEVEL` sets log verbosity. No secrets, API keys or network access are needed.

## How to run the tests

```bash
cd FULL_CODE && python -m pytest -q
```

58 tests on small synthetic fixtures (no pack data needed): severity floor and actionable rules, store
attribution, language detection, input validation, detector behaviour (small-store spike flagged, chain-wide
outage ignored, budget, cooldown, no future data), routing, de-duplication, the brief, the classifier, upload
checks, the dashboard API (every section, bad input, upload and reset), running evaluate.py from the
dashboard (with a stand-in scorer) and the report, and an end-to-end check that the full
build's flags equal the week-by-week detector's flags. Lint: `ruff check .` and
`ruff format .` (configured in `pyproject.toml`).

## Architecture

```
FULL_CODE/
├── main.py            entry point: full build (submission + outputs + briefs [+ CV])
├── detect.py          entry point: one week's flags (the jury re-run command)
├── config.toml        every threshold, window, weight and SLA
├── serve.py           entry point: web dashboard
├── api/server.py      FastAPI routes: JSON endpoints, upload, static page (no analysis logic)
├── web/               dashboard page: index.html, app.js, styles.css (no build step)
├── src/voice_of_store/
│   ├── data_io.py     load + validate the five CSVs from one folder; Monday-week assignment
│   ├── text.py        normalisation, store-from-locality attribution, language detection
│   ├── classifier.py  TF-IDF (word 1–2 + char 2–5 grams) → LinearSVC issue type, LogReg severity/actionable
│   ├── policy.py      guideline rules: severity floor, actionable requires a real, routable issue
│   ├── detector.py    store × issue weekly surprise test (details below)
│   ├── routing.py     owner + escalation rule + SLA
│   ├── dedup.py       cross-channel incident clustering
│   ├── brief.py       regional top-5 brief, trend arrows, evidence quotes, Markdown rendering
│   ├── evaluation.py  stratified 5-fold CV and precision statement
│   ├── pipeline.py    orchestration, causal weekly replay
│   ├── service.py     dashboard engine: train once, analyse the R5 dataset or an uploaded CSV
│   ├── insights.py    plain-English weekly numbers, top issues, early warnings, escalation rule
│   ├── scoring.py     runs evaluate.py (no shell, with a timeout), summarises it, builds the HTML report
│   └── reports.py     writes submission, record tables, briefs
└── tests/
```

Flow: `data_io` → `text.resolve_stores` → `classifier` + `policy` → `routing` / `dedup` / `brief` (reports
and dashboard) and → `detector` (flags). The dashboard: `web/` → `api/server.py` → `service` + `insights`.

### Classifier

One TF-IDF representation with character n-grams copes with typos, SMS spellings, emojis and code-mixing
without a translation step. Severity and actionable models add channel, issue type, "store known" and
specificity cues (digits, length). Guideline rules sit on top: severity is never below the taxonomy floor
(safety, hygiene, allergens, food safety and misconduct are at least high; failed payments at least medium);
praise/chatter/spam is never actionable; an issue without a known store is actionable only for order, app,
payment, refund and loyalty types (IT23–IT29). Identical texts reuse their training label, as the annotation
guideline gives identical texts the same type.

### Emerging-issue detector

For each (store, issue type, week): expected count = the store's feedback volume × the store's historical share
of that issue (shrunk toward the chain-wide mix, so small Express stores are not judged on two records) × a
chain-wide adjustment (if every store rises together it is a festival, outage or monsoon, not a store
problem). Surprise is the Poisson tail probability over 1- and 2-week windows, with a 2-week gap before the
window so a slow ramp does not hide in its own baseline. Policy issues get a 10× lower bar and need 2 reports
(others need 3). At most 3 flags a week; a store/issue already flagged is not re-raised for 4 weeks while it
stays elevated. Each flag cites every same-week, same-store record of that predicted type.

**No future data.** `detect.py` drops every feedback row created after the as-of Sunday before doing anything
else, trains the classifier only on labelled records among the remaining rows, and replays the weeks up to the
as-of week. `main.py` produces `R5_emerging_flags.csv` with the same procedure (retraining whenever the visible
label set changes); running `detect.py` for all 26 weeks reproduces the submitted file exactly. No dates, week
numbers or ids are hard-coded; every input is read from the folder holding `--feedback`.

### Routing and escalation rule

| Condition | Action | SLA |
|---|---|---|
| severity critical (injury, illness, allergic reaction, assault, harassment) | escalate to the owning function's head | 24 h |
| emerging-issue flag at a store | escalate to the regional manager + owner | 24–72 h by severity |
| severity high | owning function acts | 72 h |
| severity medium | owning function's weekly queue | 7 days |
| severity low | weekly brief only | — |

Only actionable records are routed; owners come from the taxonomy's `owner_function`.

## AI usage

* **In the app:** no LLMs, external APIs or downloaded models. The classifier is trained at run time
  (scikit-learn) on the 3,000 labelled records in the data folder; nothing is pickled or loaded from disk.
* **AI coding assistant:** this solution was built with Claude Code (Anthropic's Claude Opus 5.5), which
  explored the data, prototyped models, wrote the code, tests and this README under the team's direction.

## Pre-built and third-party code

* This project is released under the MIT licence (see `LICENSE`).
* Before Day 1 the repository held an earlier proof of concept ("StorePulse") built on self-generated
  synthetic data. It was removed when the official dataset arrived; it remains in git history only and none of
  it is used here.
* Libraries: numpy, pandas, scikit-learn, scipy, FastAPI, uvicorn, python-multipart (BSD/MIT/Apache
  licences), pytest and ruff for development; versions pinned in `FULL_CODE/uv.lock`. `pip-audit` reported no known vulnerabilities.
* No templates, starter kits or copied snippets. The pack's `baseline.py` and `evaluate.py` were read and run
  for comparison but are not included.

## Limitations

* **Hidden incidents are unknown.** Detector settings were chosen on the one public example (EX-1) and kept
  general; a plain read of the unlabelled test weeks shows two clear single-store ramps that the detector
  flags 2–3 weeks before a naive chain-wide count would, but multi-store incidents (e.g. one mislabelled
  product reported thinly at many stores, often without a store id) are detected late or only at one store.
* Flag precision is modest: most flags are statistically real but small bumps (13 of the 15 flags in the
  public half do not match the one known incident). The 3-per-week budget keeps this manageable.
* In the first weeks the detector's classifier sees only a few labelled records, so its evidence labels can
  differ from the final predictions file (2 train-half flags fail evaluate.py's own-label check). From week 14
  on, every label is visible and this cannot happen.
* Severity is the weakest label (weighted-F1 0.93); critical vs high is confused most often.
* Store attribution from text uses exact locality names; misspelt localities stay unattributed.
* Language detection is a marker-word heuristic used for display, not for modelling.
* De-duplication is conservative (same store, same predicted type, 72 h); reports without a store are never
  merged.
* Next steps: product-level clustering for multi-store incidents, active learning on low-confidence records,
  and a feedback loop from owners closing cases.
