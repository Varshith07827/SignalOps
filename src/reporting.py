"""Weekly regional action briefs (dict -> HTML / CSV).

A brief is computed entirely from processed data, cases and signals for one
region and one reporting week (the 7 days ending at ``as_of``). Exports are a
self-contained printable HTML page (use the browser's "Print to PDF" for a
PDF) and a CSV of the top issues. No PDF library is required.
"""
from __future__ import annotations

import html
import io
import json

import pandas as pd

import config
from src.taxonomy import SEVERITY_RANK, category_label

SEVERITY_COLOURS = {"Critical": "#C0392B", "High": "#D9822B", "Medium": "#C9A227", "Low": "#5B8DB8"}


def _week_bounds(as_of: pd.Timestamp):
    end = as_of.normalize() + pd.Timedelta(days=1)
    return end - pd.Timedelta(days=7), end, end - pd.Timedelta(days=14)


def _quote(text: str, limit: int = 220) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_regional_brief(processed: pd.DataFrame, cases: pd.DataFrame, signals: pd.DataFrame,
                         region: str, as_of=None, case_states: pd.DataFrame | None = None,
                         top_n: int = 5) -> dict:
    as_of = pd.Timestamp(as_of or processed["timestamp"].max()).normalize()
    lo, hi, prev_lo = _week_bounds(as_of)
    reg = processed[processed["region"] == region]
    this_week = reg[(reg["timestamp"] >= lo) & (reg["timestamp"] < hi)]
    prev_week = reg[(reg["timestamp"] >= prev_lo) & (reg["timestamp"] < lo)]

    def incidents(frame):
        return frame[frame["is_cluster_anchor"]].groupby("pred_category")["cluster_id"].nunique()

    cur_cat, prev_cat = incidents(this_week), incidents(prev_week)
    cat_trend = pd.DataFrame({"this_week": cur_cat, "previous_week": prev_cat}).fillna(0).astype(int)
    cat_trend = cat_trend.drop(index=[c for c in ("no_issue", "unclassified") if c in cat_trend.index])
    cat_trend["change"] = cat_trend["this_week"] - cat_trend["previous_week"]
    cat_trend["category"] = [category_label(c) for c in cat_trend.index]
    cat_trend = cat_trend.sort_values(["this_week", "change"], ascending=False)

    reg_cases = cases[cases["region"] == region].copy() if len(cases) else cases
    states = case_states.set_index("case_id") if case_states is not None and len(case_states) else None
    issues = []
    for c in reg_cases.head(top_n).itertuples():
        ids = json.loads(c.evidence_ids)
        ev = processed[processed["feedback_id"].isin(ids)].sort_values("timestamp")
        sc_this = this_week[(this_week["store_id"] == c.store_id) & (this_week["pred_category"] == c.category)]
        sc_prev = prev_week[(prev_week["store_id"] == c.store_id) & (prev_week["pred_category"] == c.category)]
        stores_hit = this_week[this_week["pred_category"] == c.category].groupby("store_name").size()
        status = owner = None
        if states is not None and c.case_id in states.index:
            status, owner = states.loc[c.case_id, "status"], states.loc[c.case_id, "owner"]
        issues.append({
            "case_id": c.case_id,
            "rank_tier": c.tier_label,
            "priority_score": float(c.priority_score),
            "category": c.category_label,
            "case_type": c.case_type,
            "store": f"{c.store_name} ({c.store_id})",
            "severity": c.severity,
            "escalation": c.escalation,
            "owner": owner or c.owner,
            "status": status or "New",
            "recommended_action": c.recommended_action,
            "store_incidents_this_week": int(sc_this["cluster_id"].nunique()),
            "store_incidents_previous_week": int(sc_prev["cluster_id"].nunique()),
            "region_incidents_this_week": int(cat_trend.loc[c.category, "this_week"]) if c.category in cat_trend.index else 0,
            "region_incidents_previous_week": int(cat_trend.loc[c.category, "previous_week"])
            if c.category in cat_trend.index else 0,
            "affected_stores": [f"{n} ({k})" for n, k in stores_hit.sort_values(ascending=False).items()][:6],
            "quotes": [{"id": r.feedback_id, "channel": config.CHANNEL_LABELS.get(r.channel, r.channel),
                        "time": str(r.timestamp)[:16], "text": _quote(r.original_text)}
                       for r in ev.head(3).itertuples()],
            "verification": "Allegation (unverified)" if states is None or c.case_id not in states.index
            else states.loc[c.case_id, "verification"],
        })
    reg_signals = signals[signals["region"] == region] if len(signals) else signals
    emerging = [{
        "signal": s.signal if hasattr(s, "signal") else ("Emerging" if s.flagged else "Watch"),
        "store": f"{s.store_name} ({s.store_id})",
        "category": s.category_label,
        "current_count": int(s.current_count),
        "baseline_weekly_mean": float(s.baseline_weekly_mean),
        "expected": float(s.expected_count),
        "window_days": int(s.evidence_window_days),
        "window_count": int(s.window_count),
        "p_value": float(s.p_value),
        "owner": s.owner,
    } for s in reg_signals.itertuples()]
    high = this_week[this_week["policy_severity"].map(SEVERITY_RANK) >= SEVERITY_RANK["High"]]
    return {
        "region": region,
        "as_of": str(as_of.date()),
        "week": f"{lo.date()} to {(hi - pd.Timedelta(days=1)).date()}",
        "kpis": {
            "feedback_records": int(len(this_week)),
            "feedback_previous_week": int(len(prev_week)),
            "estimated_unique_incidents": int(this_week["cluster_id"].nunique()),
            "high_or_critical_reports": int(len(high)),
            "open_cases": int(len(reg_cases)),
            "p1_cases": int((reg_cases["tier"] == 1).sum()) if len(reg_cases) else 0,
            "stores_reporting": int(this_week["store_id"].nunique()),
        },
        "top_issues": issues,
        "category_trend": cat_trend.reset_index(drop=True)[["category", "this_week", "previous_week", "change"]]
        .head(10).to_dict("records"),
        "emerging": emerging,
        "disclaimer": config.SYNTHETIC_DISCLAIMER,
    }


def brief_to_csv(brief: dict) -> str:
    rows = [{
        "region": brief["region"], "week": brief["week"], "rank": i + 1, "case_id": t["case_id"],
        "tier": t["rank_tier"], "priority_score": t["priority_score"], "category": t["category"],
        "store": t["store"], "severity": t["severity"], "owner": t["owner"], "status": t["status"],
        "verification": t["verification"],
        "store_incidents_this_week": t["store_incidents_this_week"],
        "store_incidents_previous_week": t["store_incidents_previous_week"],
        "recommended_action": t["recommended_action"],
        "evidence": " | ".join(q["text"] for q in t["quotes"]),
    } for i, t in enumerate(brief["top_issues"])]
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return "\ufeff" + buf.getvalue()  # BOM so Excel on Windows detects UTF-8


def render_brief_html(brief: dict) -> str:
    e = html.escape
    k = brief["kpis"]
    issue_html = []
    for i, t in enumerate(brief["top_issues"], 1):
        colour = SEVERITY_COLOURS.get(t["severity"], "#777")
        quotes = "".join(f"<li><span class='meta'>{e(q['channel'])} · {e(q['time'])} · {e(q['id'])}</span>"
                         f"<br>“{e(q['text'])}”</li>" for q in t["quotes"])
        delta = t["store_incidents_this_week"] - t["store_incidents_previous_week"]
        issue_html.append(f"""
        <div class="issue">
          <div class="issue-head"><span class="rank">{i}</span>
            <span class="badge" style="background:{colour}">{e(t['severity'])}</span>
            <strong>{e(t['category'])}</strong> — {e(t['store'])}
            <span class="right">{e(t['rank_tier'].split(' - ')[0])} · score {t['priority_score']:.0f}</span></div>
          <table class="kv">
            <tr><td>Owner</td><td>{e(t['owner'])} · status {e(t['status'])} · {e(t['verification'])}</td></tr>
            <tr><td>Trend vs previous week</td><td>store: {t['store_incidents_previous_week']} → {t['store_incidents_this_week']}
              ({'+' if delta >= 0 else ''}{delta}); region: {t['region_incidents_previous_week']} → {t['region_incidents_this_week']}</td></tr>
            <tr><td>Affected stores</td><td>{e(', '.join(t['affected_stores']) or '—')}</td></tr>
            <tr><td>Recommended action</td><td>{e(t['recommended_action'])}</td></tr>
          </table>
          <ul class="quotes">{quotes}</ul>
        </div>""")
    trend_rows = "".join(f"<tr><td>{e(r['category'])}</td><td>{r['previous_week']}</td><td>{r['this_week']}</td>"
                         f"<td>{'+' if r['change'] >= 0 else ''}{r['change']}</td></tr>" for r in brief["category_trend"])
    emerging_rows = "".join(
        f"<tr><td>{e(s['signal'])}</td><td>{e(s['store'])}</td><td>{e(s['category'])}</td>"
        f"<td>{s['baseline_weekly_mean']:.2f}/wk</td><td>{s['current_count']}</td>"
        f"<td>{s['window_count']} vs {s['expected']:.1f} exp. ({s['window_days']}d)</td><td>{s['p_value']:.1g}</td>"
        f"<td>{e(s['owner'])}</td></tr>" for s in brief["emerging"]) or "<tr><td colspan=8>No emerging signals this week.</td></tr>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>StorePulse regional brief — {e(brief['region'])}</title>
<style>
 body {{ font-family: 'Segoe UI', Arial, sans-serif; color:#1d2433; margin:28px; font-size:13px; }}
 h1 {{ font-size:20px; margin:0; }} h2 {{ font-size:15px; border-bottom:2px solid #1d2433; padding-bottom:3px; margin-top:22px; }}
 .sub {{ color:#5a6475; margin:4px 0 14px; }}
 .disclaimer {{ background:#fff4d6; border:1px solid #e8c766; padding:6px 10px; font-size:11.5px; }}
 .kpis {{ display:flex; gap:10px; margin:12px 0; }}
 .kpi {{ border:1px solid #d5dae3; border-radius:6px; padding:8px 12px; flex:1; }}
 .kpi b {{ display:block; font-size:18px; }}
 .issue {{ border:1px solid #d5dae3; border-radius:6px; padding:8px 12px; margin:10px 0; page-break-inside:avoid; }}
 .issue-head {{ font-size:13.5px; }} .rank {{ font-weight:700; margin-right:6px; }}
 .badge {{ color:#fff; border-radius:3px; padding:1px 6px; font-size:11px; margin-right:6px; }}
 .right {{ float:right; color:#5a6475; }}
 table {{ border-collapse:collapse; width:100%; }} td, th {{ border-bottom:1px solid #eceff4; padding:3px 6px; text-align:left; vertical-align:top; }}
 .kv td:first-child {{ width:170px; color:#5a6475; }}
 .quotes {{ margin:6px 0 0 18px; padding:0; }} .quotes li {{ margin-bottom:4px; }} .meta {{ color:#7a8496; font-size:11px; }}
 @media print {{ body {{ margin:10mm; }} }}
</style></head><body>
<h1>StorePulse · Weekly Regional Action Brief — {e(brief['region'])}</h1>
<div class="sub">Reporting week {e(brief['week'])} · generated from the synthetic-data pipeline</div>
<div class="disclaimer">{e(brief['disclaimer'])} Every case is an unverified allegation until investigated.</div>
<div class="kpis">
 <div class="kpi">Feedback this week<b>{k['feedback_records']:,}</b>prev. {k['feedback_previous_week']:,}</div>
 <div class="kpi">Est. unique incidents<b>{k['estimated_unique_incidents']:,}</b></div>
 <div class="kpi">High/Critical reports<b>{k['high_or_critical_reports']:,}</b></div>
 <div class="kpi">Open cases<b>{k['open_cases']}</b>P1: {k['p1_cases']}</div>
</div>
<h2>Top {len(brief['top_issues'])} priority issues</h2>
{''.join(issue_html) or '<p>No cases for this region this week.</p>'}
<h2>Emerging incidents</h2>
<table><tr><th>Signal</th><th>Store</th><th>Issue</th><th>Baseline</th><th>Last 7d</th><th>Evidence window</th><th>p</th><th>Owner</th></tr>{emerging_rows}</table>
<h2>Issue trend vs previous week (estimated unique incidents)</h2>
<table><tr><th>Issue</th><th>Previous week</th><th>This week</th><th>Change</th></tr>{trend_rows}</table>
</body></html>"""
