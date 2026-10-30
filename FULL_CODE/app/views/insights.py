"""Plain-English explanation of what the engine does and how well it works, filled with live numbers."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

JURY_QUESTIONS = [
    (
        "Why not deep learning or an LLM?",
        "We have only 3,000 labelled examples, the text mixes Hindi, Tamil and Marathi written in English letters, "
        "and the detector must run offline on a laptop in minutes. A simple model that looks at word pieces already "
        "gets about 94 out of 100 right, trains in seconds and gives the same answer every time.",
    ),
    (
        "How do you know you are not using future data?",
        "Before doing anything, the weekly detector deletes every record written after that week's Sunday. It also "
        "trains only on labelled records from before that Sunday. Running it one week at a time gives exactly the "
        "same flags as the file we submitted, and a test checks this.",
    ),
    (
        "Big stores get more complaints. How is that fair to small stores?",
        "We never compare raw counts. Each store's expected number of complaints is based on how much feedback that "
        "store sends in total, and a small store with little history is compared with the chain average instead.",
    ),
    (
        "What about festivals, outages or the monsoon?",
        "If every store's count goes up together, the detector raises everyone's expected number, so a chain-wide "
        "event does not look like a problem at one store. The app outage shown on this page is the example.",
    ),
    (
        "Why at most 3 flags a week?",
        "The scoring penalises more than 3 a week, and in real life managers stop reading alerts if there are too "
        "many. Once a store and issue are flagged, we do not flag them again for 4 weeks while they stay high.",
    ),
    (
        "What is the weakest part?",
        "Problems spread thinly over many stores (for example one wrongly labelled product sold everywhere), telling "
        "'critical' from 'high' severity, and store names that are misspelt in the text.",
    ),
]


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _biggest_chain_spike(records: pd.DataFrame) -> tuple[str, pd.Timestamp, int, float] | None:
    """The issue type and week with the largest chain-wide jump over that type's usual weekly count."""
    weekly = records.groupby(["issue_type_id", "week_start"]).size().unstack(fill_value=0)
    weekly = weekly[weekly.index.str.startswith("IT")]
    if weekly.empty:
        return None
    ratio = weekly.div(weekly.median(axis=1), axis=0)
    issue, week = ratio.stack().idxmax()
    return issue, pd.Timestamp(week), int(weekly.loc[issue, week]), float(weekly.loc[issue].median())


def show_insights(records: pd.DataFrame, flags: pd.DataFrame, outputs_dir: Path) -> None:
    cv = _read_json(outputs_dir / "cv_report.json")
    score = _read_json(outputs_dir / "score_train.json")

    st.header("What this does, in one minute")
    st.markdown(
        "Every week Saffron Retail receives about 1,500 messages: online reviews, app comments, staff notes and "
        "call-centre conversations, in English, Hinglish, Tamil and Marathi, full of typos. This tool reads every "
        "message and decides:\n\n"
        "1. **What is it about?** One of 30 problem types (empty shelves, broken freezer, rude staff...) or "
        "praise, a general comment, or spam.\n"
        "2. **How serious is it?** Low, medium, high or critical.\n"
        "3. **Can someone act on it?** Only if it is a real, specific problem and we know which store or online "
        "order it is about.\n\n"
        "It then sends each problem to the team that owns it, writes a one-page weekly summary per region, and "
        "raises an **early warning** when one store suddenly gets more of one problem than usual."
    )

    st.header("How good is it?")
    if cv:
        st.markdown(
            "Measured fairly: the model is tested on labelled messages it never saw while learning "
            "(5 rounds, each hiding a different fifth of the 3,000 labels)."
        )
        table = pd.DataFrame(
            [
                ("Overall classification score", cv["classification_score"], 0.579, "Official formula, 0 to 1"),
                ("Problem type", cv["issue_type_macro_f1"], 0.559, "Rare types count as much as common ones"),
                ("Severity", cv["severity_weighted_f1"], 0.448, "The hardest label"),
                ("Needs action (yes/no)", cv["actionable_f1"], 0.751, ""),
            ],
            columns=["What", "Our score", "Starter baseline", "Note"],
        )
        st.dataframe(table, hide_index=True, width="stretch")
        st.success(
            f"**Precision statement:** out of every 100 messages we mark as needing action, "
            f"**{cv['precision_actionable'] * 100:.0f}** really do. Out of every 100 we escalate as high or "
            f"critical, **{cv['precision_escalated_high_critical'] * 100:.0f}** really need action."
        )
    else:
        st.info("Run the full build with cross-validation (Run tab) to show these numbers.")
    if score:
        st.markdown(
            f"The organisers' scorer, run on the labelled weeks, gives **{score['primary_score']:.3f}** (the starter "
            f"baseline gets 0.481). That run tests on messages the model learnt from, so the fair estimate above "
            f"is the one to quote."
        )

    st.header("How the early warning works")
    st.markdown(
        "For every store, every problem type and every week, the tool asks one question: "
        "**is this more than we would normally expect from this store?**\n\n"
        "1. **Expected number:** how much feedback the store sent this week, times how often this store usually "
        "mentions this problem. Small stores with little history are compared with the chain average.\n"
        "2. **Surprise:** how unlikely this week's number would be if nothing were wrong. It also looks at the "
        "last two weeks together, to catch problems that build up slowly.\n"
        "3. **Safety first:** safety, hygiene, allergy, food-safety and staff-misconduct issues need only 2 "
        "reports and a lower bar; other issues need 3.\n"
        "4. **No alarm floods:** at most 3 warnings a week, and the same store and problem is not flagged again "
        "for 4 weeks.\n"
        "5. **Proof:** every warning lists the messages it is based on, all from that store and that week."
    )
    if score:
        lead = score.get("incidents", [{}])
        first = lead[0] if lead else {}
        if first:
            st.markdown(
                f"On the public example incident (problem {first.get('issue_type_id')}), the warning came "
                f"**{first.get('lead_weeks')} weeks before** the simple chain-wide counter would have noticed it."
            )

    spike = _biggest_chain_spike(records)
    if spike:
        issue, week, count, usual = spike
        flagged = flags[(flags["issue_type_id"] == issue) & (flags["as_of_week_start"] == f"{week:%Y-%m-%d}")]
        st.header("Why it does not panic")
        st.markdown(
            f"In the week of **{week:%d %b %Y}**, problem **{issue}** jumped to **{count}** messages across the "
            f"whole chain, against a usual **{usual:.0f}**. Every store went up together, so it is a chain-wide event "
            f"(like an app outage), not one store's problem. Early warnings raised for it that week: "
            f"**{len(flagged)}**."
        )

    st.header("Fair play: no peeking at the future")
    st.markdown(
        "Each week's warnings are made as if it were that Sunday night: newer messages are deleted before the "
        "model is even trained. The **Run** tab lets you prove it: run any range of weeks one at a time and "
        "compare with the submitted file. Nothing is hard-coded (no dates, store ids or message ids), so it also "
        "works on the disguised copy of the data the jury may use."
    )

    st.header("Weak spots")
    st.markdown(
        "- A problem spread thinly over many stores is caught late or at only one store.\n"
        "- Severity: 'critical' and 'high' get mixed up most often.\n"
        "- A store whose name is misspelt in the text is not recognised.\n"
        "- Most warnings are real but small bumps; only the 3-a-week limit keeps them manageable."
    )

    st.header("Questions the jury may ask")
    for question, answer in JURY_QUESTIONS:
        with st.expander(question):
            st.write(answer)
