"""Run tab: run the weekly detector over a chosen range of weeks, rebuild everything, or score the submission."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from voice_of_store.commands import (
    CommandResult,
    build_command,
    compare_with_submission,
    detector_command,
    display,
    evaluate_command,
    new_run_folder,
    project_path,
    run_command,
    weeks_between,
)
from voice_of_store.config import Settings
from voice_of_store.detector import FLAG_COLUMNS

OUTPUT_TAIL_CHARS = 6000


def _show_result(result: CommandResult) -> None:
    status = st.success if result.ok else st.error
    status(f"{'Finished' if result.ok else 'Failed'} in {result.seconds} s (exit code {result.returncode})")
    st.code(display(result.command), language="bash")
    if result.output.strip():
        st.code(result.output[-OUTPUT_TAIL_CHARS:], language="text")


def _run_detector_range(settings: Settings, weeks: list[pd.Timestamp]) -> None:
    folder = new_run_folder(settings.paths.outputs_dir)
    progress = st.progress(0.0, text="Starting...")
    week_flags: dict[pd.Timestamp, pd.DataFrame] = {}
    failures: list[CommandResult] = []
    commands: list[str] = []
    for done, monday in enumerate(weeks, start=1):
        progress.progress((done - 1) / len(weeks), text=f"Week of {monday:%d %b %Y} ({done}/{len(weeks)})")
        out = folder / f"{monday:%Y-%m-%d}.csv"
        command = detector_command(settings, monday, out)
        commands.append(display(command))
        result = run_command(command, settings.runner.detect_timeout_seconds)
        if result.ok and out.exists():
            week_flags[monday] = pd.read_csv(out)
        else:
            failures.append(result)
    progress.progress(1.0, text="Done")
    st.session_state["detector_run"] = {
        "folder": project_path(folder),
        "flags": week_flags,
        "failures": failures,
        "commands": commands,
    }


def _show_detector_run(settings: Settings) -> None:
    run = st.session_state.get("detector_run")
    if not run:
        return
    for failure in run["failures"]:
        _show_result(failure)
    if not run["flags"]:
        return
    flags = [f for f in run["flags"].values() if not f.empty]
    combined = pd.concat(flags, ignore_index=True) if flags else pd.DataFrame(columns=FLAG_COLUMNS)
    st.subheader(f"{len(combined)} flags in {len(run['flags'])} weeks")
    st.dataframe(combined, hide_index=True, width="stretch")
    submitted_path = settings.paths.submission_dir / "R5_emerging_flags.csv"
    if submitted_path.exists():
        comparison = compare_with_submission(run["flags"], pd.read_csv(submitted_path))
        if comparison["identical"].all():
            st.success("Every week matches the submitted R5_emerging_flags.csv exactly.")
        else:
            st.warning("Some weeks differ from the submitted file (re-run the full build to refresh it).")
        st.dataframe(comparison, hide_index=True, width="stretch")
    st.caption(f"Files written to {run['folder']}")
    with st.expander("Commands that were run"):
        st.code("\n".join(run["commands"]), language="bash")


def show_runner(settings: Settings, calendar_weeks: list[pd.Timestamp]) -> None:
    st.header("1. Weekly early-warning detector")
    st.markdown(
        "This is the command in `submission/detector_cmd.txt`, the one the jury may ask you to run live. "
        "Each week runs separately and only sees messages up to that week's Sunday. About 10 seconds per week."
    )
    labels = {w: f"{w:%d %b %Y}" for w in calendar_weeks}
    first, last = st.select_slider(
        "Weeks to run",
        options=calendar_weeks,
        value=(calendar_weeks[max(0, len(calendar_weeks) - 13)], calendar_weeks[-1]),
        format_func=labels.get,
    )
    try:
        weeks = weeks_between(calendar_weeks, first, last)
    except ValueError as error:
        st.error(str(error))
        return
    example = detector_command(settings, weeks[0], settings.paths.outputs_dir / "runs" / "<run>" / "week.csv")
    st.code(display(example), language="bash")
    if st.button(f"Run detector for {len(weeks)} week(s)", type="primary"):
        _run_detector_range(settings, weeks)
    _show_detector_run(settings)

    st.divider()
    st.header("2. Rebuild everything")
    st.markdown(
        "Re-labels all messages, re-runs the detector for every week, and rewrites `submission/` and the dashboard "
        "data. Takes about 2 minutes (about 3 with the fairness check)."
    )
    with_cv = st.checkbox("Also measure accuracy fairly (5-fold cross-validation)", value=True)
    st.code(display(build_command(with_cv)), language="bash")
    if st.button("Rebuild"):
        with st.spinner("Rebuilding... keep this tab open."):
            st.session_state["build_run"] = run_command(build_command(with_cv), settings.runner.build_timeout_seconds)
        st.cache_data.clear()
    if "build_run" in st.session_state:
        _show_result(st.session_state["build_run"])

    st.divider()
    st.header("3. Score with the organisers' evaluate.py")
    if not settings.runner.evaluator_path.exists():
        st.info(
            f"evaluate.py not found at {project_path(settings.runner.evaluator_path)}. Set `evaluator_path` in "
            "FULL_CODE/config.toml to your copy of the problem pack's evaluate.py."
        )
        return
    st.markdown("Scores `submission/` against the public labels (weeks 1-13) and the public example incident.")
    st.code(display(evaluate_command(settings)), language="bash")
    if st.button("Score submission"):
        with st.spinner("Scoring..."):
            st.session_state["score_run"] = run_command(
                evaluate_command(settings), settings.runner.evaluate_timeout_seconds
            )
        st.cache_data.clear()
    if "score_run" in st.session_state:
        _show_result(st.session_state["score_run"])
