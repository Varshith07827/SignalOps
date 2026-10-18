# StorePulse — Two-Minute Demo Guide

All numbers below were produced by running the pipeline on the default synthetic dataset
(seed `20260`, 40,000 records, as-of date 2026-09-27). If you regenerate with another seed, store IDs and
numbers will change. Re-run `python -m src.evaluation` and use its output instead.

> Say this once, at the start: *"Everything you'll see is synthetic data we generated ourselves, and the three
> incidents are our own planted test scenarios, not the organisers' incidents."*

## 1. Startup (Windows PowerShell)

```powershell
cd StorePulse
.venv\Scripts\Activate.ps1
python -m src.pipeline          # only needed the first time (~1 min); safe to re-run
python -m src.evaluation        # refreshes the Model Evaluation page; prints 15 PASS lines
streamlit run app.py            # opens http://localhost:8501
```

Before recording: open each page once so the data cache is warm. On the Overview page click
**Reset case workflow state** so every case starts as *New*.

## 2. Click path, expected results and narration

| # | Click | Expected on screen | Narration (≈15 s each) |
|---|---|---|---|
| 1 | Sidebar → **Command Centre** | KPI cards: **40,000** feedback processed (1,548 this week); **36,010** estimated unique incidents (3,990 duplicates merged); **94** high-severity cases (28 Critical P1); **2** emerging incidents; **94** escalations awaiting review. Weekly trend lines, region heatmap (incidents per 1,000 feedback), priority table, and an "Emerging this week" list with Refrigeration failure @ Bengaluru Civil Lines and Payment failure @ Ahmedabad Civil Lines. | "StorePulse processed forty thousand reviews, app ratings, staff notes and call transcripts. After deduplication that's about thirty-six thousand unique incidents. Safety escalations are ranked first by policy, and two store-level problems are emerging this week." |
| 2 | Sidebar → **Feedback Explorer** → Quick view **Hinglish examples** → type `thanda nahi` in search → click row **FB038847** | Text *"dairy chiller bilkul thanda nahi hai, yogurt garam ho raha hai"* → **Refrigeration failure**, auto-classified. Glossary chips *thanda nahi → not cold*, *garam → warm hot*; language hint Hinglish; rule evidence; contributing terms; top-3 bar chart; severity High; incident grouping. Optional: search `romba kootam` (Tamil → Queue management) or `nongra` (Bengali → Hygiene). | "Feedback arrives code-mixed, with typos and emojis. We keep the original text for audit, normalise it, and translate only phrases in a documented glossary. Every label is explained, and anything we don't recognise goes to human review instead of being forced into a category." |
| 3 | Sidebar → **Emerging Issues** | Ranked table. Row 1: **Emerging · Bengaluru Civil Lines (S013) · Refrigeration failure**, baseline 1.17/wk, 7 in the last 7 days, 13 in 14 days vs 1.15 expected, ~11× rate ratio. Evidence panel opens below automatically. | "This isn't a list of the biggest complaint counts. It shows stores rising unusually fast against their own history and the network trend." |
| 4 | Stay on row 1 and scroll the evidence panel | Cards: baseline 1.17/wk, 7 current (15 reports), p ≈ 3e-8, q ≈ 6e-5, detected 27 Sep. Weekly bar chart with the current week highlighted above the dotted baseline. "Why flagged" explanation; channels: call-centre, in-app, staff note, online review; quotes in English, Hinglish and staff shorthand; owner **Store Ops**; recommended action: dispatch refrigeration technician. | "Fifteen reports through all four channels collapse into nine unique incidents. Against a baseline of about one a week, chance is around three in a hundred million. It's routed to Store Ops with a concrete action, and it's still treated as a signal, not a verified fact." |
| 5 | Sidebar → **Incident Management** → search `S002` | Case **POL-CL035165 · Allergen labelling concern at Gurugram Central**: badges **▲ Critical**, **P1 – Mandatory escalation**, *Mandatory escalation (24h)*; verification bar highlights **Allegation (unverified)**; owner **Merchandising**; one report (BakeHouse Choco Crunch "nut-free" label lists peanut traces). Then set Status → *Under Review*, Verification → *Under investigation*, add a note, **Save** → audit trail appears. | "A single allergen report. Volume would never surface it, but policy makes it Critical, so it goes to the top tier with a 24-hour verification deadline. Notice what we don't claim: it's an allegation until someone investigates. Status changes are saved locally with an audit trail." |
| 6 | Sidebar → **Emerging Issues** → click row 2 | **Ahmedabad Civil Lines (S039) · Payment failure**: 12 incidents in 7 days (20 reports) vs 1.17/wk baseline; 17 in 14 days vs 3.10 expected; owner **Digital**; quotes about UPI/card failures with money debited across app, review, call-centre and staff channels. Case severity is shown as High (raised from Medium by the trend-escalation rule). | "Same detector, different team. A payment problem is spiking at one store across four channels, so it goes to Digital to check the POS and payment gateway." |
| 7 | Sidebar → **Regional Brief** → Region **South** → **Download brief (HTML)** | KPIs for the week; top 5 issues with severity, owner, trend vs previous week, affected stores, quotes and actions. Refrigeration failure @ S013 is in the top five and listed under Emerging incidents. The HTML opens as a printable one-page brief. | "Every Monday each regional manager gets a one-page brief: top five issues, evidence, owners, actions and what's emerging. It exports to HTML or CSV, and prints to PDF from the browser." |
| 8 | Sidebar → **Model Evaluation** | Red banner *SYNTHETIC-DATA EVALUATION*. Cards: **15/15** scenario checks; classification F1 (hold-out) **0.64**; escalation precision **98.0%** (case level 98.9%); dedup **0.85 / 0.45**; detection rate **100%** (2 planted trends, 12 unplanted episodes). Tabs show the confusion matrix, per-category metrics, false-positive diagnosis and the naive-ranking comparison. | "We evaluate against our own synthetic ground truth and report the weak spots too: on phrasings the model never saw, F1 is 0.64, and deduplication is deliberately conservative. Escalation precision is 98 percent, and both planted trends are caught with no look-ahead." |

Total: about 2 minutes at 15 seconds per step.

## 3. Where the scenarios are

| Scenario | Store | Category | Find it |
|---|---|---|---|
| A — emerging refrigeration | S013 Bengaluru Civil Lines (South, Neighbourhood) | Refrigeration failure | Emerging Issues row 1; Incident Management search `S013` |
| B — single allergen report | S002 Gurugram Central (North, Express) | Allergen labelling concern | Incident Management search `S002`; Feedback Explorer search `Choco Crunch` (FB039066) |
| C — emerging payment failure | S039 Ahmedabad Civil Lines (West, Superstore) | Payment failure | Emerging Issues row 2; Incident Management search `S039` |
| N1 — negative control | S028 (East, Hypermarket) | Stock shortage | Highest stock-shortage volume but never flagged as emerging |

The full scenario definitions (onset, report counts, channels) are in `data/generated/scenario_manifest.json`.
Detection replay: A is confirmed 12.4 days after onset and C 11.4 days after onset, using only data available
on each day.

## 4. Troubleshooting

| Symptom | Fix |
|---|---|
| "No processed data yet" on a page | Overview → **Run pipeline**, or `python -m src.pipeline`. |
| Model Evaluation shows an old report or "older than the latest pipeline run" | Click **Run evaluation now** or run `python -m src.evaluation`. |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then reactivate. |
| DuckDB "could not set lock on file" | Another process is writing to the database. Use the Overview buttons from inside the app, or stop Streamlit (Ctrl+C) before running `python -m src.pipeline`. |
| Numbers differ from this guide | You regenerated with another seed or setting. Run `python -m src.pipeline --regenerate` with the default seed, then `python -m src.evaluation`. |
| Case statuses from a rehearsal still show | Overview → **Reset case workflow state** (or delete `data/state/case_state.duckdb`). |
| First page load is slow | The first load reads 40,000 records (about 1 s) and loads the classifier; later loads are cached. |
| Port 8501 busy | `streamlit run app.py --server.port 8502`. |
| Scenario check fails in `python -m src.evaluation` | The command exits with code 1 and prints the failing check; re-run `python -m src.pipeline` and check that the data uses the default seed. |
