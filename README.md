# StorePulse — Voice-of-Store Intelligence Engine

**From feedback to foresight.** Talent AP Mega Hackathon 2026 · Problem Statement R5 · proof of concept

StorePulse turns unstructured, multilingual retail feedback (online reviews, in-app ratings, store-staff
notes and call-centre transcripts) into prioritised, owned and explainable operational actions:

```
Feedback → Classification → Deduplication → Severity → Trend detection → Prioritisation → Ownership → Action brief
```

> **Synthetic-data disclosure.** No official dataset, store master, taxonomy or evaluation script was provided.
> Every record, store, incident and metric in this repository is **synthetic**, generated locally by
> `src/data_generator.py`. Nothing here represents a real retailer, and no figure is an official hackathon
> result. The three planted incidents are our own test scenarios, not the organisers' hidden incidents.

---

## Features

| Area | What it does |
|---|---|
| Synthetic data | Deterministic generator (seed `20260`): 40,000 records, 60 stores in 5 regions, 4 store formats, 4 channels, 26 weeks, seasonality, duplicate reports, typos, abbreviations, emojis, truncation, Hinglish and a small controlled set of transliterated Tamil/Telugu/Marathi/Bengali/Kannada phrases, plus out-of-taxonomy feedback. |
| Planted scenarios | **A** emerging refrigeration failure (S013), **B** single-report allergen concern (S002), **C** emerging payment failure (S039), plus negative controls **N1** (chronic high-volume store) and **N2** (network-wide seasonal AC rise). Documented in `data/generated/scenario_manifest.json`. |
| Classification | Normalisation + documented glossary → weighted keyword/phrase rules + TF-IDF (word 1–2 g, char 3–5 g) logistic regression → hybrid probability → *auto* / *review* / *unclassified*. Every prediction is explained (rule hits, contributing terms, top-3 alternatives). |
| Severity policy | Deterministic rules (`src/taxonomy.py`): allergen, food safety, hygiene/pests, physical safety and staff misconduct are High/Critical from a **single** report; aggravating terms (injury, reaction, harassment) lift to Critical. Category, severity, confidence, verification and required action are separate fields. |
| Deduplication | Conservative: same store + predicted category + within 36 h of the cluster's first report + text/entity/time score. Uncertain matches are *possible duplicates*, never silently merged. All originals preserved. |
| Emerging issues | Store × category unique-incident counts vs an empirical-Bayes baseline, adjusted for store volume and network trend, negative-binomial tail test on 7- and 14-day windows, Benjamini–Hochberg control and minimum-evidence rules. |
| Prioritisation & routing | Policy tiers (P1 Critical policy > P2 High policy / high-severity trend > P3 trend) override a 0–100 score from normalised severity, evidence, trend, breadth and persistence. Provisional owner mapping to Store Ops, Supply Chain, Merchandising, Digital, HR. |
| Workflow | Case status (New / Under Review / Assigned / Resolved), owner override, verification state (Allegation → Under investigation → Verified / Not substantiated), notes and audit trail persisted locally in DuckDB. |
| Reporting | One-page weekly regional action brief; downloadable as self-contained HTML (print to PDF from the browser) and CSV. |
| Evaluation | `python -m src.evaluation`: classification P/R/F1 + confusion matrix, escalation precision, dedup precision/recall, detection rate, false positives, detection delay, scenario checks. |

## Architecture

```
config.py                 all thresholds and paths (single source of truth)
app.py                    Streamlit entry point + Overview page (st.navigation)
app_pages/                1_Command_Centre … 6_Model_Evaluation (presentation only)
src/
  data_generator.py       synthetic stores, feedback, planted scenarios, training corpus, validation
  phrasebank.py           generator-only text templates (never used by the classifier)
  preprocessing.py        normalisation, glossary, emoji tokens, negation, entity extraction
  taxonomy.py             provisional categories, owners, severity policy rules
  classifier.py           hybrid rules + TF-IDF logistic regression with abstention and explanations
  severity.py             deterministic policy engine
  deduplication.py        conservative incident clustering
  anomaly_detection.py    store × category emerging-issue detector (+ rolling replay)
  prioritization.py       case building, tiers, priority score, explanations
  routing.py              owner assignment and recommended actions
  reporting.py            regional brief (dict → HTML / CSV)
  evaluation.py           synthetic-ground-truth evaluation and scenario checks
  storage.py              DuckDB analytics tables + separate case-state database
  pipeline.py             orchestration (`python -m src.pipeline`)
  ui.py                   shared Streamlit styling and cached loaders
tests/                    pytest suite (66 tests)
data/generated/           synthetic data, model inputs, analytics DB (git-ignored)
data/state/               case workflow state (git-ignored)
artifacts/                trained model, evaluation report (git-ignored)
```

Business logic lives in `src/` and has no Streamlit dependency; pages only present results.
The page folder is named `app_pages/` rather than `pages/` on purpose: a folder called `pages/` switches on
Streamlit's legacy auto-discovery, which bypasses `st.navigation` (and the app's styling) when a page URL is
opened directly as the first request after the server starts.
Ground-truth columns are stripped by `pipeline.strip_ground_truth` before any inference.

## Technology stack

Python 3.13 · Streamlit · pandas · NumPy · scikit-learn · SciPy · Plotly · DuckDB · PyArrow · pytest.
No paid APIs, API keys, LLM services or internet access are needed at runtime. Tested with Python 3.13.16,
Streamlit 1.66, pandas 3.0, scikit-learn 1.9, DuckDB 1.5.

## Installation (Windows, PowerShell)

```powershell
cd StorePulse                      # the repository folder
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

macOS/Linux: `python3.13 -m venv .venv && source .venv/bin/activate`, then the same `pip` commands.

## Running

```powershell
python -m src.data_generator       # 1. generate 40,000 synthetic records + training corpus (~5 s)
python -m src.classifier --train   # 2. train / initialise the classifier (~7 s)
python -m src.pipeline             # 3. classify, score, deduplicate, detect, build cases (~40 s)
python -m src.evaluation           # 4. synthetic evaluation + scenario checks (~10 s, exit code 1 if a check fails)
streamlit run app.py               # 5. open http://localhost:8501
```

`python -m src.pipeline` alone also works: it generates data and trains the model if they are missing.
Options: `python -m src.pipeline --regenerate` (rebuild data), `--retrain` (retrain model);
`python -m src.data_generator --seed 7 --records 20000`; `python -m src.classifier --text "fridge thanda nahi hai"`.
The Overview page offers the same controls as buttons (run pipeline, retrain, regenerate, reset case state).

Tests:

```powershell
python -m pytest -q
```

The suite uses small fixtures and one shared 12,000-record dataset; it never regenerates the 40,000 records.

## Results on the synthetic dataset (seed 20260)

All numbers below come from `python -m src.evaluation` on the default dataset. They are **synthetic-data
evaluation results**, optimistic by construction, and not official results.

| Metric | Value |
|---|---|
| Scenario checks (A, B, C, N1) | 15 / 15 pass |
| Classification macro F1 — hold-out phrasings (never seen in training), incident level | 0.645 (P 0.679, R 0.639, coverage 0.888, accuracy when classified 0.896) |
| Classification macro F1 — all incidents (mostly seen phrasings) | 0.953 |
| Out-of-taxonomy feedback left unclassified / sent to review / force-labelled | 87.3% / 11.9% / 0.7% |
| Escalation precision (true actionable escalations / all escalations), record level | 0.980 (3,229 / 3,294) |
| Escalation precision, case level | 0.989 (93 / 94) |
| Recall of true Critical reports (escalated) | 0.988 |
| Deduplication pairwise precision / recall | 0.853 / 0.445 (deliberately conservative) |
| Estimated vs true unique incidents | 36,010 vs 33,025 |
| Planted trend detection rate | 2 / 2 |
| Detection delay after onset (rolling replay, no look-ahead) | A 12.4 days · C 11.4 days |
| Unplanted flag episodes over 121 as-of days × 1,800 cells | 12 (11 match genuinely elevated synthetic counts, 1 pipeline artefact) |
| Flag-day precision: StorePulse vs naive "top-10 by raw volume" | 31.4% vs 1.4% (naive flags chronic store N1 on 121/121 days) |

**How to read these honestly.** The gap between hold-out (0.645) and seen phrasings (0.999) shows that the
headline 0.953 mostly measures template recall; the hold-out figure is the better estimate. A naive raw-volume
ranking surfaces the planted cells sooner (A after 2.4 days) because duplicate reports inflate raw counts, but it
is almost all noise. StorePulse waits for independent incidents above baseline, which costs about 1–1.5 weeks
of delay on these scenarios.

## Key definitions

* **Escalation precision** = true actionable escalations / all escalations. Record level: an escalation is a
  report with a mandatory policy escalation; it is truly actionable when the synthetic ground truth says
  actionable and its true severity is High or Critical.
* **Incident onset** = timestamp of the first synthetic report of a planted scenario. **Detection time** =
  end of the first as-of day on which the detector, using only data up to that moment, confirms a flag for
  the scenario's store and category. **Detection delay** = detection time − onset.
* **Verification** is never inferred. Every case starts as *Allegation (unverified)*; only a user can mark it
  *Under investigation*, *Verified incident* or *Not substantiated*.

## Severity and escalation policy (provisional)

| Rule | Applies to | Floor | Critical when |
|---|---|---|---|
| POL-ALLERGEN | allergen labelling, or allergen terms in any text | Critical | always |
| POL-FOODSAFETY | food safety / contamination, illness terms | Critical | always |
| POL-FOODSAFETY-EXPIRY | expired product | High | illness terms |
| POL-HYGIENE | hygiene, pests, pest terms | High | contamination of food |
| POL-SAFETY | physical hazards | High | injury terms |
| POL-CONDUCT | staff misconduct | High | harassment, assault, threats, public accusation |
| Trend escalation | confirmed emerging trend (q ≤ 0.01) | +1 level, max High | — |

Critical policy → P1 *Mandatory escalation (24h)*; High policy → P2 *Mandatory review (72h)*. Report volume is
never an input to policy severity, so a single report always escalates.

## Supported language phrases

Only the phrases in `src/preprocessing.py::GLOSSARY` are understood beyond what the model learnt from the
synthetic corpus: about 40 Hinglish expressions and a handful each of transliterated Tamil, Telugu, Marathi,
Bengali and Kannada. The language hint shown in the UI is a heuristic based on that glossary. Other languages
(e.g. Malayalam, or any native script) are **not supported** and are routed to human review when vocabulary is
unrecognised.

## Known limitations

* Synthetic data only; templates and noise were authored by the same team as the classifier, so all metrics are
  optimistic. Real feedback will be messier and the hold-out F1 of 0.645 already shows a large generalisation gap.
* The taxonomy, owner mapping, severity policy and thresholds are provisional assumptions awaiting official
  definitions.
* Deduplication favours precision; recall is about 0.45, so unique incidents are over-estimated (~9%).
* Emerging detection confirms the planted trends about 11–12 days after onset; faster detection would need
  stronger priors or a policy-aware early-warning rule. Twelve unplanted flag episodes occurred in the replay.
* Detection operates per store; a multi-store problem appears as several store flags plus the network-movement
  view, not as one cross-store incident.
* Case IDs are tied to the reporting week of the current data; regenerating data with a different seed creates
  new cases (old workflow state remains in `data/state` but no longer matches).
* DuckDB allows one writer: run the pipeline from the Overview page, or stop the app before running
  `python -m src.pipeline` in another terminal if you see a lock error.
* The HTML brief is the export format; PDF is produced with the browser's "Print → Save as PDF".

See `DEMO_GUIDE.md` for the two-minute demonstration script.
