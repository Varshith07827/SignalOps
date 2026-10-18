"""Deterministic severity and escalation policy engine.

Keeps five concepts separate for every record:

1. ``pred_category``          - what the classifier thinks the issue is;
2. ``policy_severity``        - severity under the configured policy rules;
3. ``evidence_confidence``    - how confident the classifier is (not severity!);
4. ``verification_status``    - every report starts as an unverified allegation;
5. ``requires_action``        - whether someone needs to do something.

Policy rules (see ``taxonomy.POLICY_RULES``) fire either because the predicted
category is a policy category, or because explicit safety terms appear in the
text (so a misclassified allergen report is still escalated). Severity is
assessed per report: report volume is never an input, so a single report can
- and must - trigger a mandatory escalation.
"""
from __future__ import annotations

import pandas as pd

from src.preprocessing import TermMatcher
from src.taxonomy import (CATEGORY_BY_CODE, ESCALATION_POLICY, NO_ISSUE, POLICY_RULES, SEVERITY_RANK,
                          UNCLASSIFIED, PolicyRule)

ABSENCE_SENSITIVE_POLICY = {"allergen information", "allergy warning", "not declared"}
UNVERIFIED = "Allegation (unverified)"


def max_severity(*levels: str) -> str:
    return max(levels, key=lambda s: SEVERITY_RANK[s])


class PolicyEngine:
    def __init__(self, rules: list[PolicyRule] = POLICY_RULES):
        self.rules = rules
        self.triggers = {r.rule_id: TermMatcher(r.trigger_terms, ABSENCE_SENSITIVE_POLICY) for r in rules}
        self.criticals = {r.rule_id: TermMatcher(r.critical_terms) for r in rules}

    def assess(self, enriched_text: str, pred_category: str, decision: str = "auto") -> dict:
        category_known = decision in ("auto", "review") and pred_category not in (UNCLASSIFIED, None)
        cat = CATEGORY_BY_CODE.get(pred_category) if category_known else None
        base = cat.base_severity if cat else "Low"
        severity = base
        applied, reasons = [], []
        for rule in self.rules:
            by_category = cat is not None and cat.code in rule.categories
            term_hits = self.triggers[rule.rule_id].matches(enriched_text)
            if not (by_category or term_hits):
                continue
            applied.append(rule.rule_id)
            severity = max_severity(severity, rule.min_severity)
            basis = []
            if by_category:
                basis.append(f"category '{cat.label}'")
            if term_hits:
                basis.append("terms " + ", ".join(f"'{t}'" for t in term_hits))
            reasons.append(f"{rule.rule_id} ({rule.name}) via {' and '.join(basis)} -> at least {rule.min_severity}")
            crit_hits = self.criticals[rule.rule_id].matches(enriched_text)
            if crit_hits and severity != "Critical":
                severity = "Critical"
                reasons.append(f"{rule.rule_id} aggravating terms {', '.join(repr(t) for t in crit_hits)} -> Critical")
            elif crit_hits:
                reasons.append(f"{rule.rule_id} aggravating terms {', '.join(repr(t) for t in crit_hits)}")

        if applied and severity == "Critical":
            escalation = ESCALATION_POLICY["Critical"]
        elif applied:
            escalation = ESCALATION_POLICY["High-policy"]
        else:
            escalation = ESCALATION_POLICY["None"]
        if not reasons:
            reasons.append(f"Base severity of category ({base}); no policy rule applies"
                           if cat else "Category unknown - default Low pending human triage")

        is_no_issue = cat is not None and cat.code == NO_ISSUE and not applied
        return {
            "base_severity": base,
            "policy_severity": severity,
            "policy_rules": ",".join(applied),
            "policy_escalation": escalation,
            "mandatory_escalation": bool(applied),
            "severity_reason": " | ".join(reasons),
            "requires_action": not is_no_issue,
            "verification_status": "Not applicable" if is_no_issue else UNVERIFIED,
        }

    def assess_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        """Assess every row of a frame with enriched_text, pred_category and decision columns."""
        rows = [self.assess(t, c, d) for t, c, d in zip(df["enriched_text"], df["pred_category"], df["decision"])]
        out = pd.DataFrame(rows, index=df.index)
        out["evidence_confidence"] = df["confidence"].values
        return out
