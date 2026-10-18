"""Provisional issue taxonomy, ownership mapping and severity policy.

IMPORTANT: no official taxonomy, store master or organisational routing rules
were supplied with the problem statement. Everything in this module is a
*provisional* configuration authored for the synthetic demonstration and must
be replaced once official definitions are available.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TAXONOMY_VERSION = "provisional-0.1"

OWNERS = ["Store Ops", "Supply Chain", "Merchandising", "Digital", "HR"]

SEVERITY_LEVELS = ["Critical", "High", "Medium", "Low"]
SEVERITY_RANK = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}

UNCLASSIFIED = "unclassified"
NO_ISSUE = "no_issue"
OUT_OF_TAXONOMY = "other"  # synthetic ground truth only; never a prediction target

# Channel propensity profiles used by the synthetic generator.
CHANNEL_PROFILES = {
    "in_store": {"online_review": 0.40, "in_app": 0.20, "staff_note": 0.25, "call_centre": 0.15},
    "digital": {"online_review": 0.20, "in_app": 0.50, "staff_note": 0.0, "call_centre": 0.30},
    "payment": {"online_review": 0.30, "in_app": 0.30, "staff_note": 0.15, "call_centre": 0.25},
    "transaction": {"online_review": 0.35, "in_app": 0.25, "staff_note": 0.10, "call_centre": 0.30},
    "conduct": {"online_review": 0.40, "in_app": 0.15, "staff_note": 0.10, "call_centre": 0.35},
    "safety": {"online_review": 0.35, "in_app": 0.15, "staff_note": 0.05, "call_centre": 0.45},
    "support": {"online_review": 0.30, "in_app": 0.20, "staff_note": 0.0, "call_centre": 0.50},
    "praise": {"online_review": 0.55, "in_app": 0.40, "staff_note": 0.02, "call_centre": 0.03},
}


@dataclass(frozen=True)
class Category:
    code: str
    label: str
    owner: str
    base_severity: str
    base_rate: float  # relative background frequency (synthetic generator only)
    channel_profile: str
    keywords: tuple[str, ...]  # rule-engine evidence terms (matched on normalised text)
    action: str
    description: str
    policy_rule: str | None = None
    actionable: bool = True
    secondary_owner: str | None = None


CATEGORIES: list[Category] = [
    Category(
        "refrigeration_failure", "Refrigeration failure", "Store Ops", "High", 2.5, "in_store",
        ("fridge", "freezer", "chiller", "not cooling", "not cold", "melted", "melting",
         "refrigerator", "compressor", "cooling issue", "warm milk", "temperature display"),
        "Dispatch refrigeration technician, review chiller temperature logs and quarantine "
        "temperature-sensitive stock until cold chain is confirmed.",
        "Chillers, freezers or cold-chain display units not holding temperature.",
    ),
    Category(
        "allergen_labelling", "Allergen labelling concern", "Merchandising", "Critical", 0.22, "safety",
        ("allergen", "allergy", "allergic", "nut free", "nut-free", "peanut", "gluten", "sesame",
         "lactose", "contains milk", "egg free", "ingredients", "allergy warning", "not declared",
         "allergen information", "allergen info"),
        "Treat as potential safety risk: withdraw the batch from sale pending verification, "
        "verify label against supplier specification, and contact the customer.",
        "Missing, incorrect or misleading allergen information on products or labels.",
        policy_rule="POL-ALLERGEN", secondary_owner="Store Ops",
    ),
    Category(
        "food_safety", "Food safety / contamination", "Store Ops", "Critical", 0.45, "safety",
        ("food poisoning", "foreign object", "plastic piece", "vomiting", "fell sick", "contaminated",
         "undercooked", "mould", "mold", "hair in", "metal wire", "sick after"),
        "Preserve product sample, withdraw the affected batch, open a food-safety "
        "investigation and contact the customer within 24 hours.",
        "Illness, contamination or foreign objects associated with food sold.",
        policy_rule="POL-FOODSAFETY", secondary_owner="Supply Chain",
    ),
    Category(
        "hygiene_cleanliness", "Hygiene and cleanliness", "Store Ops", "High", 3.0, "in_store",
        ("dirty", "filthy", "unhygienic", "hygiene", "smell", "stink", "garbage", "without gloves",
         "washroom", "sticky floor", "not cleaned", "overflowing"),
        "Schedule an immediate hygiene inspection and deep clean; review cleaning rota "
        "and food-handling practice.",
        "Unclean premises, poor food-handling hygiene or sanitation failures.",
        policy_rule="POL-HYGIENE",
    ),
    Category(
        "pest_sighting", "Pest sighting", "Store Ops", "High", 0.7, "in_store",
        ("rat", "rats", "mouse", "mice", "cockroach", "cockroaches", "lizard", "flies", "ants",
         "pest", "droppings", "rodent"),
        "Call pest-control contractor, inspect affected area and remove exposed stock.",
        "Rodents, insects or other pests observed in the store.",
        policy_rule="POL-HYGIENE",
    ),
    Category(
        "physical_safety_hazard", "Physical safety hazard", "Store Ops", "High", 0.7, "in_store",
        ("wet floor", "slipped", "slip", "broken glass", "exposed wire", "wires", "emergency exit",
         "fell on", "injured", "hazard", "dangerous", "loose shelf", "spilled oil", "hurt"),
        "Make the area safe immediately, record the hazard, and complete an incident "
        "report if anyone was hurt.",
        "Conditions that could cause injury to customers or staff.",
        policy_rule="POL-SAFETY",
    ),
    Category(
        "staff_misconduct", "Staff misconduct", "HR", "High", 1.6, "conduct",
        ("rude", "abusive", "shouted", "insulted", "harassing", "harassment", "misbehaved",
         "misbehaviour", "inappropriate", "disrespectful", "arrogant", "accused me", "abusive language"),
        "Refer to HR / employee relations; collect statements and CCTV where available. "
        "Do not treat the allegation as established until reviewed.",
        "Allegations of rude, abusive, discriminatory or inappropriate behaviour by staff.",
        policy_rule="POL-CONDUCT",
    ),
    Category(
        "product_quality", "Product quality", "Merchandising", "Medium", 7.0, "in_store",
        ("stale", "rotten", "poor quality", "quality", "wilted", "soggy", "smelled off", "tasted bad",
         "bad quality"),
        "Check supplier batch quality, review shelf rotation and raise a supplier quality claim.",
        "Freshness, taste or physical quality of products below expectation.",
        secondary_owner="Supply Chain",
    ),
    Category(
        "stock_shortage", "Stock shortage", "Supply Chain", "Medium", 8.0, "in_store",
        ("out of stock", "empty shelf", "empty shelves", "sold out", "restock", "no stock",
         "shelf was empty", "oos", "not available today"),
        "Check replenishment orders and DC fulfilment for the affected lines; adjust "
        "forecast and shelf capacity.",
        "Regularly ranged products unavailable on shelf.",
    ),
    Category(
        "product_availability", "Product range / availability", "Merchandising", "Low", 4.0, "in_store",
        ("stopped stocking", "doesn't carry", "does not carry", "bring it back", "range", "variety",
         "discontinued", "start selling", "limited range", "choice"),
        "Review local range and assortment requests with category management.",
        "Requests for products or ranges the store does not carry.",
    ),
    Category(
        "incorrect_price_label", "Incorrect price or label", "Merchandising", "Medium", 4.5, "in_store",
        ("price tag", "shelf price", "wrong price", "price label", "mrp", "old price", "label shows",
         "rang up", "tag missing"),
        "Audit shelf-edge labels against the price file and correct mismatches.",
        "Shelf-edge price or product labels that are missing or inconsistent.",
        secondary_owner="Store Ops",
    ),
    Category(
        "billing_error", "Billing error", "Store Ops", "Medium", 5.0, "transaction",
        ("charged twice", "overcharged", "bill", "receipt", "scanned", "double charged",
         "wrong bill", "never bought", "extra charge"),
        "Reconcile the transaction, refund any overcharge and retrain till staff if a pattern emerges.",
        "Incorrect charges or receipts at the till.",
    ),
    Category(
        "payment_failure", "Payment failure", "Digital", "Medium", 4.0, "payment",
        ("payment failed", "upi", "card declined", "declined", "transaction failed", "pos",
         "card machine", "debited", "money deducted", "qr", "payment"),
        "Check POS/payment-gateway health for the store, reconcile failed-but-debited "
        "transactions and communicate refunds.",
        "Card, UPI or POS payment failures, including failed-but-debited transactions.",
        secondary_owner="Store Ops",
    ),
    Category(
        "app_failure", "App failure", "Digital", "Medium", 5.0, "digital",
        ("app", "crash", "crashing", "login", "otp", "update", "freezing", "blank screen", "error"),
        "Raise an incident with the app engineering team with device/version details.",
        "Mobile app crashes, login problems or functional errors.",
    ),
    Category(
        "delivery_delay", "Delivery delay", "Supply Chain", "Medium", 6.0, "digital",
        ("delivery", "delayed", "late", "slot", "out for delivery", "not arrived", "hours late"),
        "Review last-mile capacity and slot allocation for the fulfilling store.",
        "Home-delivery orders arriving late or missing their slot.",
    ),
    Category(
        "wrong_or_missing_items", "Wrong or missing order items", "Supply Chain", "Medium", 3.5, "digital",
        ("missing from my", "wrong item", "someone else's order", "substitute", "items missing",
         "wrong size", "missing items"),
        "Audit picking accuracy at the fulfilling store and refund missing items.",
        "Online orders delivered with wrong, missing or unapproved substitute items.",
    ),
    Category(
        "queue_management", "Queue management", "Store Ops", "Low", 6.0, "in_store",
        ("queue", "long line", "waited", "counters closed", "one counter", "billing counter",
         "express lane", "long queue"),
        "Review till staffing against footfall peaks and open additional counters at peak times.",
        "Long checkout queues and insufficient open tills.",
    ),
    Category(
        "equipment_failure", "Equipment failure", "Store Ops", "Medium", 3.0, "in_store",
        ("self checkout", "weighing scale", "escalator", "lift", "trolley", "lights", "out of order",
         "machine broken", "weighing machine"),
        "Log a maintenance ticket and track repair against the facilities SLA.",
        "Non-refrigeration store equipment out of order (self-checkouts, scales, lifts, trolleys).",
    ),
    Category(
        "staff_availability", "Staff availability", "Store Ops", "Low", 3.0, "in_store",
        ("no staff", "understaffed", "nobody to help", "no one came", "help desk", "couldn't find",
         "employee"),
        "Review floor-staff deployment and rostering at peak times.",
        "Customers unable to find staff to help.",
    ),
    Category(
        "refund_return", "Refund or return", "Store Ops", "Medium", 2.5, "transaction",
        ("refund", "return", "returned", "store credit", "not credited"),
        "Trace the refund, confirm policy application and communicate status to the customer.",
        "Delayed refunds or disputed returns.",
    ),
    Category(
        "loyalty_rewards", "Loyalty and rewards", "Digital", "Low", 2.5, "digital",
        ("points", "loyalty", "reward", "membership", "redeem"),
        "Check loyalty ledger for the member and credit missing points.",
        "Loyalty points or member benefits not applied.",
    ),
    Category(
        "promotion_mismatch", "Promotion not applied", "Merchandising", "Medium", 3.5, "transaction",
        ("offer", "discount", "buy one get one", "bogo", "coupon", "promotion", "% off"),
        "Verify promotion set-up in the POS against marketing materials.",
        "Advertised offers or coupons not honoured at the till.",
    ),
    Category(
        "packaging_damage", "Packaging damage", "Supply Chain", "Low", 2.0, "in_store",
        ("torn", "leaking", "crushed", "dented", "damaged", "seal", "packet was torn"),
        "Inspect inbound handling and remove damaged stock from sale.",
        "Damaged, dented or leaking product packaging.",
    ),
    Category(
        "expired_product", "Expired product on sale", "Store Ops", "High", 1.8, "in_store",
        ("expired", "expiry", "best before", "past expiry", "use by", "date was"),
        "Run an immediate date-check sweep of the category and remove expired stock.",
        "Products sold or displayed beyond their expiry date.",
        policy_rule="POL-FOODSAFETY-EXPIRY",
    ),
    Category(
        "parking_access", "Parking and access", "Store Ops", "Low", 1.5, "in_store",
        ("parking", "two-wheeler", "attendant", "parking charges"),
        "Review parking management and signage with the landlord / facilities.",
        "Parking availability, charges and vehicle access.",
    ),
    Category(
        "store_temperature_ac", "Store temperature / AC", "Store Ops", "Low", 1.8, "in_store",
        ("ac", "air conditioning", "too hot", "stuffy", "humid", "ventilation", "uncomfortable",
         "unbearably hot"),
        "Check HVAC operation and set-points; log facilities ticket if faulty.",
        "Ambient store temperature or air-conditioning complaints (not refrigeration).",
    ),
    Category(
        "customer_support", "Customer support / helpline", "Digital", "Low", 3.0, "support",
        ("customer care", "helpline", "on hold", "ticket", "chat support", "no response", "emails"),
        "Review the support ticket history and close the loop with the customer.",
        "Unresolved contacts with the helpline, chat or email support.",
    ),
    Category(
        "accessibility", "Accessibility", "Store Ops", "Medium", 1.0, "in_store",
        ("wheelchair", "ramp", "pram", "elderly", "disabled", "seating"),
        "Assess accessibility barriers and agree remediation with facilities.",
        "Barriers for customers with disabilities, elderly customers or parents with prams.",
    ),
    Category(
        "account_security", "Account security / privacy", "Digital", "High", 0.8, "support",
        ("my account", "without my permission", "fraud", "wallet", "personal details", "hacked",
         "unauthorised", "otp i didn't"),
        "Lock the affected account, review access logs and involve information security.",
        "Unauthorised account activity, privacy exposure or fraud using customer data.",
    ),
    Category(
        "store_hours_closure", "Store hours / closure", "Store Ops", "Low", 1.0, "in_store",
        ("closed", "shutter", "opening hours", "timing", "closing time", "opened late"),
        "Confirm trading hours compliance and update store-hours listings.",
        "Store closed or closing early relative to published hours.",
    ),
    Category(
        NO_ISSUE, "No issue / positive", "Store Ops", "Low", 12.0, "praise",
        ("great", "thank you", "thanks", "love", "excellent", "good experience", "helpful",
         "perfect", "polite", "nice"),
        "No action required; positive feedback can be shared with the store team.",
        "Praise, thanks or neutral comments with no operational issue.",
        actionable=False,
    ),
]

CATEGORY_BY_CODE: dict[str, Category] = {c.code: c for c in CATEGORIES}
CATEGORY_CODES: list[str] = [c.code for c in CATEGORIES]
OPERATIONAL_CODES: list[str] = [c.code for c in CATEGORIES if c.actionable]


def category_label(code: str) -> str:
    if code == UNCLASSIFIED:
        return "Unclassified (review required)"
    if code == OUT_OF_TAXONOMY:
        return "Outside taxonomy"
    cat = CATEGORY_BY_CODE.get(code)
    return cat.label if cat else code


def owner_for(code: str) -> str:
    cat = CATEGORY_BY_CODE.get(code)
    return cat.owner if cat else "Triage (unassigned)"


# --------------------------------------------------------------------------- #
# Severity policy
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PolicyRule:
    rule_id: str
    name: str
    categories: tuple[str, ...]
    min_severity: str  # severity floor whenever the rule applies
    trigger_terms: tuple[str, ...] = ()  # text evidence that applies the rule even if
    # the classifier chose another category
    critical_terms: tuple[str, ...] = ()  # aggravating evidence that lifts to Critical
    escalation: str = "Mandatory review (72h)"
    rationale: str = ""


POLICY_RULES: list[PolicyRule] = [
    PolicyRule(
        "POL-ALLERGEN", "Potential allergen risk", ("allergen_labelling",), "Critical",
        trigger_terms=("allergic reaction", "allergen", "nut free", "nut-free", "contains peanut",
                       "peanut traces", "allergy warning", "allergen information", "gluten allergy",
                       "not declared"),
        escalation="Mandatory escalation (24h)",
        rationale="Undeclared allergens can cause severe harm from a single exposure, so any "
                  "credible allegation is escalated for verification regardless of volume.",
    ),
    PolicyRule(
        "POL-FOODSAFETY", "Potential food-safety risk", ("food_safety",), "Critical",
        trigger_terms=("food poisoning", "vomiting", "fell sick", "foreign object", "contaminated",
                       "plastic piece", "metal wire", "sick after"),
        escalation="Mandatory escalation (24h)",
        rationale="Illness or contamination allegations require product retention and rapid verification.",
    ),
    PolicyRule(
        "POL-FOODSAFETY-EXPIRY", "Expired food on sale", ("expired_product",), "High",
        trigger_terms=("expired", "past expiry", "expiry date"),
        critical_terms=("fell sick", "vomiting", "food poisoning"),
        rationale="Expired stock is a food-safety control failure even without reported harm.",
    ),
    PolicyRule(
        "POL-HYGIENE", "Hygiene or pest concern", ("hygiene_cleanliness", "pest_sighting"), "High",
        trigger_terms=("cockroach", "rat", "rats", "mice", "rodent", "unhygienic", "filthy", "droppings"),
        critical_terms=("in the food", "on the food", "inside the packet", "fell sick"),
        rationale="Hygiene and pest allegations are high severity under policy irrespective of volume.",
    ),
    PolicyRule(
        "POL-SAFETY", "Physical safety hazard", ("physical_safety_hazard",), "High",
        trigger_terms=("slipped", "broken glass", "exposed wire", "emergency exit", "injured"),
        critical_terms=("injured", "hurt my", "bleeding", "fracture", "ambulance", "fell on my",
                        "first aid given", "customer slipped"),
        rationale="Hazards are high severity; any reported injury is critical.",
    ),
    PolicyRule(
        "POL-CONDUCT", "Staff misconduct allegation", ("staff_misconduct",), "High",
        trigger_terms=("harass", "harassing", "harassment", "abusive language", "inappropriate comments"),
        critical_terms=("harass", "harassing", "harassment", "inappropriate comments", "touched",
                        "assault", "slapped", "hit me", "threatened", "accused me of stealing",
                        "chor bola", "discriminat"),
        rationale="Misconduct allegations are high severity; harassment, assault, threats or "
                  "public accusations are critical and routed to HR.",
    ),
]

POLICY_RULE_BY_ID = {r.rule_id: r for r in POLICY_RULES}

# Trend escalation: a confirmed emerging trend raises case severity by one level
# (capped at High) because an accelerating problem affects more customers.
TREND_ESCALATION = {"max_q_value": 0.01, "cap": "High"}

ESCALATION_POLICY = {
    "Critical": "Mandatory escalation (24h)",
    "High-policy": "Mandatory review (72h)",
    "Trend": "Trend escalation (72h)",
    "None": "Monitor",
}

SEVERITY_DEFINITIONS = {
    "Critical": "Potential for serious harm to people (allergen, illness, injury, harassment). "
                "Mandatory escalation within 24h for verification, regardless of report volume.",
    "High": "Safety, hygiene, conduct or cold-chain concerns, or account security. "
            "Mandatory review within 72h when policy-mandated.",
    "Medium": "Commercial or service failures with customer financial or experience impact.",
    "Low": "Convenience and comfort issues; monitored and handled through normal routines.",
}
