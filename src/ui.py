"""Shared Streamlit presentation helpers (no business logic lives here)."""
from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from src import storage

# Categorical series colours (validated for CVD separation on the navy surface).
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"]
# Status colours are reserved for severity and always shown with an icon + label.
SEVERITY_STYLE = {
    "Critical": ("#d03b3b", "▲"),
    "High": ("#ec835a", "◆"),
    "Medium": ("#fab219", "●"),
    "Low": ("#8a94a6", "○"),
}
SEQUENTIAL = [[0.0, "#16233a"], [0.25, "#184f95"], [0.5, "#2a78d6"], [0.75, "#6da7ec"], [1.0, "#cde2fb"]]
TEXT = "#E3E8F0"
MUTED = "#8C97AB"
GRID = "#24314A"

CSS = """
<style>
.block-container {padding-top: 2.2rem; padding-bottom: 2rem; max-width: 1400px;}
h1, h2, h3 {letter-spacing: -0.01em;}
.sp-header {display:flex; align-items:baseline; gap:14px; margin-bottom:2px;}
.sp-header .title {font-size:1.65rem; font-weight:650; color:#E3E8F0;}
.sp-header .kicker {font-size:0.82rem; color:#8C97AB; text-transform:uppercase; letter-spacing:0.08em;}
.sp-sub {color:#8C97AB; font-size:0.92rem; margin-bottom:0.8rem;}
.sp-banner {background:#1A2338; border:1px solid #2B3A57; border-left:3px solid #c98500; color:#C9D2E0;
  padding:7px 12px; border-radius:6px; font-size:0.82rem; margin-bottom:14px;}
.sp-card {background:#131C2E; border:1px solid #22304A; border-radius:8px; padding:12px 14px; height:100%;}
.sp-card .label {color:#8C97AB; font-size:0.78rem; text-transform:uppercase; letter-spacing:0.06em;}
.sp-card .value {color:#E3E8F0; font-size:1.6rem; font-weight:650; line-height:1.25; margin-top:2px;}
.sp-card .note {color:#8C97AB; font-size:0.78rem; margin-top:2px;}
.sp-badge {display:inline-block; padding:1px 8px; border-radius:4px; font-size:0.78rem; font-weight:600;
  border:1px solid; margin-right:6px; white-space:nowrap;}
.sp-chip {display:inline-block; padding:2px 9px; border-radius:12px; font-size:0.78rem; background:#1A2338;
  border:1px solid #2B3A57; color:#C9D2E0; margin:0 4px 4px 0;}
.sp-flow {display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin:6px 0 10px;}
.sp-flow .step {background:#131C2E; border:1px solid #2B3A57; border-radius:6px; padding:5px 10px; font-size:0.85rem;}
.sp-flow .arrow {color:#4FB3BF;}
.sp-quote {border-left:3px solid #2B3A57; padding:4px 10px; margin:6px 0; color:#D5DCE7; font-size:0.9rem;}
.sp-quote .meta {color:#8C97AB; font-size:0.75rem;}
.sp-state {display:flex; gap:6px; margin:6px 0 4px;}
.sp-state div {flex:1; text-align:center; padding:6px 4px; border-radius:6px; font-size:0.8rem; border:1px solid #2B3A57;
  color:#8C97AB; background:#0F1626;}
.sp-state div.on {color:#0B1220; background:#4FB3BF; border-color:#4FB3BF; font-weight:650;}
.sp-kv {font-size:0.88rem; color:#C9D2E0;}
.sp-kv b {color:#E3E8F0;}
.sp-empty {border:1px dashed #2B3A57; border-radius:8px; padding:18px; color:#8C97AB; text-align:center;}
div[data-testid="stMetricValue"] {font-size:1.4rem;}
</style>
"""


def apply_style() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str = "", kicker: str = "StorePulse") -> None:
    st.markdown(f"<div class='sp-header'><span class='title'>{html.escape(title)}</span>"
                f"<span class='kicker'>{html.escape(kicker)}</span></div>", unsafe_allow_html=True)
    if subtitle:
        st.markdown(f"<div class='sp-sub'>{html.escape(subtitle)}</div>", unsafe_allow_html=True)


def synthetic_banner(extra: str = "") -> None:
    st.markdown(f"<div class='sp-banner'><b>Synthetic demonstration data.</b> {html.escape(config.SYNTHETIC_DISCLAIMER)}"
                f" {html.escape(extra)}</div>", unsafe_allow_html=True)


def metric_card(label: str, value, note: str = "", help_text: str = "") -> str:
    title = f" title='{html.escape(help_text)}'" if help_text else ""
    return (f"<div class='sp-card'{title}><div class='label'>{html.escape(label)}</div>"
            f"<div class='value'>{html.escape(str(value))}</div><div class='note'>{html.escape(note)}</div></div>")


def metric_row(cards: list[tuple]) -> None:
    cols = st.columns(len(cards))
    for col, card in zip(cols, cards):
        col.markdown(metric_card(*card), unsafe_allow_html=True)


def severity_badge(sev: str) -> str:
    colour, icon = SEVERITY_STYLE.get(sev, ("#8a94a6", "○"))
    return (f"<span class='sp-badge' style='color:{colour}; border-color:{colour}'>{icon} "
            f"{html.escape(sev)}</span>")


def badge(text: str, colour: str = "#4FB3BF") -> str:
    return f"<span class='sp-badge' style='color:{colour}; border-color:{colour}'>{html.escape(text)}</span>"


def severity_text(sev: str) -> str:
    return f"{SEVERITY_STYLE.get(sev, ('', '○'))[1]} {sev}"


def quote(text: str, meta: str = "") -> str:
    return (f"<div class='sp-quote'>“{html.escape(str(text))}”<div class='meta'>{html.escape(meta)}</div></div>")


def empty_state(message: str) -> None:
    st.markdown(f"<div class='sp-empty'>{html.escape(message)}</div>", unsafe_allow_html=True)


def style_fig(fig: go.Figure, height: int = 340, legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=30, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, size=12), showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color=MUTED, size=11)),
        hoverlabel=dict(bgcolor="#131C2E", bordercolor="#2B3A57", font=dict(color=TEXT)),
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont=dict(color=MUTED))
    return fig


# --------------------------------------------------------------------------- #
# Data access (cached on the pipeline run timestamp)
# --------------------------------------------------------------------------- #
def data_ready() -> bool:
    return storage.table_exists("feedback") and storage.table_exists("cases")


def run_version() -> str:
    return str(storage.read_meta().get("processed_at", "none"))


@st.cache_data(show_spinner="Loading processed feedback ...")
def _load(version: str) -> dict:
    feedback = storage.read_table("feedback")
    cases = storage.read_table("cases")
    signals = storage.read_table("signals") if storage.table_exists("signals") else pd.DataFrame()
    stores = storage.read_table("stores")
    return {"feedback": feedback, "cases": cases, "signals": signals, "stores": stores,
            "meta": storage.read_meta()}


def load() -> dict:
    return _load(run_version())


def cases_with_state(cases: pd.DataFrame) -> pd.DataFrame:
    """Overlay locally persisted workflow state onto computed cases."""
    states = storage.get_case_states()
    out = cases.copy()
    out["status"] = "New"
    out["assigned_owner"] = out["owner"]
    out["verification"] = out["default_verification"]
    out["note"] = ""
    if len(states):
        st_idx = states.set_index("case_id")
        known = out["case_id"].isin(st_idx.index)
        out.loc[known, "status"] = out.loc[known, "case_id"].map(st_idx["status"])
        owners = out.loc[known, "case_id"].map(st_idx["owner"])
        out.loc[known, "assigned_owner"] = owners.where(owners.notna(), out.loc[known, "owner"])
        out.loc[known, "verification"] = out.loc[known, "case_id"].map(st_idx["verification"])
        out.loc[known, "note"] = out.loc[known, "case_id"].map(st_idx["note"]).fillna("")
    return out


def require_data() -> dict | None:
    if not data_ready():
        empty_state("No processed data yet. Open the Overview page and click 'Run pipeline', or run "
                    "`python -m src.pipeline` in a terminal.")
        return None
    return load()


@st.cache_resource(show_spinner="Loading classifier ...")
def classifier():
    from src.classifier import HybridClassifier
    return HybridClassifier.load()
