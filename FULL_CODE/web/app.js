"use strict";

// Data text is always set with textContent, never innerHTML.
const $ = (id) => document.getElementById(id);
const SEVERITY_NAME = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };
const TREND_CLASS = { Rising: "up", Falling: "down", Steady: "steady", "New this week": "new" };
const TREND_ARROW = { Rising: "↑", Falling: "↓", Steady: "→", "New this week": "●" };
let allWarnings = [];

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `The server answered ${response.status}. Try again.`);
  return body;
}

function notice(message, isError) {
  const box = $("notice");
  box.hidden = !message;
  box.textContent = message || "";
  box.classList.toggle("error", Boolean(isError));
}

function mondayText(week) {
  return new Date(`${week}T00:00:00`).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function weekText(week) {
  return new Date(`${week}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function fillSelect(select, values, label) {
  const previous = select.value;
  select.replaceChildren(...values.map((v) => {
    const option = el("option", label ? label(v) : v);
    option.value = v;
    return option;
  }));
  if (values.includes(previous)) select.value = previous;
}

function regionText(region) {
  return region.startsWith("National") ? "Online & app" : `${region} region`;
}

function showStatus(status) {
  $("dataset").textContent = `${status.rows.toLocaleString()} messages from ${status.dataset}`;
  $("show-dataset").hidden = !status.uploaded;
  fillSelect($("week"), [...status.weeks].reverse(), weekText);
  fillSelect($("drawer-week"), [...status.weeks].reverse(), mondayText);
  fillSelect($("region"), status.regions, regionText);
  $("content").hidden = false;
}

async function loadStatus() {
  const status = await api("/api/status");
  if (status.status === "loading") {
    $("dataset").textContent = status.message;
    setTimeout(loadStatus, 2000);
    return;
  }
  if (status.status === "error") {
    notice(status.message, true);
    return;
  }
  notice("");
  showStatus(status);
  if ($("review-store").options.length === 1) await loadStores();
  await refresh();
}

function renderWeek(data) {
  $("n-messages").textContent = data.messages.toLocaleString();
  $("n-action").textContent = data.need_action.toLocaleString();
  $("n-urgent").textContent = data.urgent.toLocaleString();
  $("n-warnings").textContent = data.warnings;
  renderTeams(data.teams);
}

function renderTeams(teams) {
  if (!teams.length) {
    $("teams").replaceChildren(el("li", "Nothing to act on this week.", "empty"));
    return;
  }
  const widest = Math.max(...teams.map((t) => t.total));
  $("teams").replaceChildren(...teams.map((t) => {
    const item = el("li");
    const row = el("button", null, "team-row");
    row.type = "button";
    row.addEventListener("click", () => {
      const region = $("region").value;
      openCases(t.team, regionText(region), { team: t.team, region });
    });
    const label = el("div", null, "label");
    const urgent = t.critical + t.high;
    label.append(el("b", t.team), el("span", `${t.total} to fix${urgent ? `, ${urgent} urgent` : ""}`));
    const track = el("div", null, "bar-track");
    track.style.width = `${Math.max(8, (t.total / widest) * 100)}%`;
    ["critical", "high", "medium", "low"].forEach((s) => {
      if (!t[s]) return;
      const seg = el("span", null, `seg ${s}`);
      seg.style.width = `${(t[s] / t.total) * 100}%`;
      seg.title = `${SEVERITY_NAME[s]}: ${t[s]}`;
      track.append(seg);
    });
    row.append(label, track);
    item.append(row);
    return item;
  }));
}

function timeText(stamp) {
  return new Date(stamp).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

let drawerCases = [];
let drawerQuery = null;
let drawerRequest = 0;

function caseItem(c) {
  const item = el("li", null, `case sev-${c.severity}`);
  const title = el("div", null, "issue-title");
  title.append(el("h3", c.problem), el("span", SEVERITY_NAME[c.severity], `pill ${c.severity}`));
  if (c.early_warning) title.append(el("span", "Early warning", "pill warning"));
  const action = el("p", null, "action");
  const team = drawerQuery.filters.team ? "" : ` · ${c.team}`;
  action.append(el("strong", c.store), el("span", ` · ${c.action}${team}`, "team"));
  const facts = el("div", null, "facts");
  const reports = c.reports === 1 ? "1 report" : `${c.reports} reports`;
  facts.append(
    el("span", `Reported ${timeText(c.opened)}`),
    el("span", c.due ? `Due ${timeText(c.due)}` : "No deadline", c.due ? "due" : ""),
    el("span", `${reports} · ${c.channels.join(", ")}`),
  );
  item.append(title, action, facts, el("blockquote", c.quote, "quote"));
  return item;
}

function showCases(severity) {
  const shown = severity ? drawerCases.filter((c) => c.severity === severity) : drawerCases;
  const empty = drawerCases.length ? "No cases at this level." : "No cases in this week.";
  $("drawer-cases").replaceChildren(...(shown.length ? shown.map(caseItem) : [el("li", empty, "empty")]));
  $("drawer-filters").querySelectorAll("button").forEach((b) => {
    b.setAttribute("aria-pressed", String(b.dataset.severity === (severity || "")));
  });
}

function filterChip(label, count, severity) {
  const chip = el("button", `${label} ${count}`, "chip");
  chip.type = "button";
  chip.dataset.severity = severity;
  chip.disabled = count === 0;
  chip.addEventListener("click", () => showCases(severity));
  return chip;
}

// Opens the case list for a team (from "Who must act") or a store's problem (from the map).
// It starts on the week picked on the page; the drawer's own week picker then moves it to any other week.
function openCases(title, scope, filters) {
  drawerQuery = { filters };
  $("drawer-title").textContent = title;
  $("drawer-scope").textContent = scope;
  $("drawer-week").value = $("week").value;
  if (!$("cases-dialog").open) $("cases-dialog").showModal();
  loadCases();
}

async function loadCases() {
  const request = ++drawerRequest;
  $("drawer-filters").replaceChildren();
  $("drawer-cases").replaceChildren(el("li", "Loading cases...", "empty"));
  try {
    const query = new URLSearchParams({ week: $("drawer-week").value, ...drawerQuery.filters });
    const data = await api(`/api/cases?${query}`);
    // Ignore an older answer if the week was changed again while it loaded.
    if (request !== drawerRequest) return;
    drawerCases = data.cases;
    const chips = [filterChip("All", drawerCases.length, "")];
    ["critical", "high", "medium", "low"].forEach((s) => chips.push(filterChip(SEVERITY_NAME[s], data.counts[s], s)));
    $("drawer-filters").replaceChildren(...chips);
    showCases("");
  } catch (error) {
    if (request === drawerRequest) $("drawer-cases").replaceChildren(el("li", error.message, "error-text"));
  }
}

function renderIssues(items) {
  $("top-title").textContent = items.length ? `Top ${items.length} issues to act on` : "Top issues to act on";
  if (!items.length) {
    $("top-issues").replaceChildren(el("li", "No problems need action in this region this week.", "empty"));
    return;
  }
  $("top-issues").replaceChildren(...items.map((item) => {
    const row = el("li", null, `issue sev-${item.severity}`);
    const body = el("div");

    const title = el("div", null, "issue-title");
    title.append(el("h3", item.problem), el("span", SEVERITY_NAME[item.severity], `pill ${item.severity}`));
    if (item.early_warning) title.append(el("span", "Early warning", "pill warning"));

    const action = el("p", null, "action");
    action.append(el("strong", item.action), el("span", ` · ${item.team}`, "team"));

    const facts = el("div", null, "facts");
    const cases = item.incidents === 1 ? "1 case" : `${item.incidents} cases`;
    facts.append(el("span", `${cases} from ${item.reports} messages`));
    const trend = el("span", `${TREND_ARROW[item.trend] || ""} ${item.trend}`, `trend ${TREND_CLASS[item.trend] || ""}`);
    facts.append(trend, el("span", `Last week: ${item.last_week}`));

    const stores = el("p", item.stores.length ? item.stores.join(", ") : "Online orders and app", "stores");
    body.append(title, action, facts, stores);

    if (item.quotes.length) body.append(el("blockquote", item.quotes[0], "quote"));
    if (item.quotes.length > 1) {
      const more = el("details", null, "more-quotes");
      more.append(el("summary", `${item.quotes.length - 1} more message`));
      item.quotes.slice(1).forEach((q) => more.append(el("blockquote", q, "quote")));
      body.append(more);
    }
    row.append(body);
    return row;
  }));
}

function warningItem(w, region) {
  const item = el("li", null, `warning-item${w.region === region ? " in-region" : ""}`);
  item.append(
    el("div", w.store, "where"),
    el("div", w.problem, "what"),
    el("div", `${w.reports} reports this week · ${w.team}`, "meta"),
  );
  return item;
}

function renderWarnings() {
  const week = $("week").value;
  const region = $("region").value;
  const now = allWarnings.filter((w) => w.week === week);
  const earlier = allWarnings.filter((w) => w.week < week);
  now.sort((a, b) => Number(b.region === region) - Number(a.region === region) || b.reports - a.reports);
  $("warnings-now").replaceChildren(
    ...(now.length ? now.map((w) => warningItem(w, region)) : [el("li", "No unusual rises at any store this week.", "empty")]),
  );
  $("earlier-summary").textContent = `Earlier warnings (${earlier.length})`;
  $("warnings-earlier").replaceChildren(...earlier.map((w) => {
    const item = warningItem(w, region);
    item.querySelector(".meta").textContent = `${weekText(w.week)} · ${w.reports} reports · ${w.team}`;
    return item;
  }));
}

async function refresh() {
  const week = encodeURIComponent($("week").value);
  const region = encodeURIComponent($("region").value);
  try {
    const [weekData, issues, warnings] = await Promise.all([
      api(`/api/week?week=${week}&region=${region}`),
      api(`/api/top-issues?region=${region}&week=${week}`),
      api("/api/warnings"),
    ]);
    allWarnings = warnings;
    renderWeek(weekData);
    renderIssues(issues);
    renderWarnings();
    await renderMap($("week").value, $("region").value);
  } catch (error) {
    notice(error.message, true);
  }
}

async function loadRule() {
  const rule = await api("/api/escalation-rule");
  $("rule").replaceChildren(...rule.map((r) => {
    const item = el("li");
    item.append(el("span", r.when), el("span", r.who, "who"), el("span", r.within === "-" ? "No deadline" : r.within, "within"));
    return item;
  }));
}

function percent(value) {
  return `${Math.round(value * 100)}%`;
}

function scoreCell(label, value) {
  const cell = el("div");
  cell.append(el("dt", label), el("dd", value));
  return cell;
}

async function checkAccuracy() {
  const box = $("accuracy");
  const button = $("check-accuracy");
  button.disabled = true;
  box.replaceChildren(el("p", "Checking... about 15 seconds.", "hint"));
  try {
    const a = await api("/api/accuracy");
    const scores = el("dl", null, "scores");
    scores.append(
      scoreCell("Overall score (0 to 1)", a.classification_score.toFixed(2)),
      scoreCell("Problem type ", percent(a.issue_type_macro_f1)),
      scoreCell("Severity ", percent(a.severity_weighted_f1)),
      scoreCell("Needs action ", percent(a.actionable_f1)),
    );
    const statement = el("p", null, "statement");
    statement.append(
      "Of every 100 messages we mark as needing action, ",
      el("strong", `${Math.round(a.precision_actionable * 100)} really do`),
      ". Of every 100 we mark as urgent, ",
      el("strong", `${Math.round(a.precision_escalated_high_critical * 100)} really need action`),
      ".",
    );
    box.replaceChildren(scores, statement);
  } catch (error) {
    box.replaceChildren(el("p", error.message, "empty"));
  } finally {
    button.disabled = false;
  }
}

function renderEvaluation(result) {
  const s = result.summary;
  const head = el("div", null, "primary-score");
  head.append(
    el("span", s.primary.toFixed(4), "value"),
    el("span", `Primary score, from evaluate.py on ${result.finished_at} (${result.seconds} s)`, "label"),
  );

  const scores = el("dl", null, "scores five");
  scores.append(
    scoreCell("Classification", s.classification.toFixed(3)),
    scoreCell("Early-warning lead", s.lead_score === null ? "-" : s.lead_score.toFixed(3)),
    scoreCell("Problem type F1", s.issue_type_f1.toFixed(3)),
    scoreCell("Severity F1", s.severity_f1.toFixed(3)),
    scoreCell("Needs action F1", s.actionable_f1.toFixed(3)),
  );

  const table = el("table");
  const headRow = el("tr");
  ["Incident", "Problem", "Started", "Simple counter caught it", "We flagged it", "Weeks earlier"].forEach((h) =>
    headRow.append(el("th", h)));
  const thead = el("thead");
  thead.append(headRow);
  const tbody = el("tbody");
  s.incidents.forEach((i) => {
    const tr = el("tr");
    const lead = i.lead_weeks > 0 ? `+${i.lead_weeks}` : String(i.lead_weeks);
    tr.append(
      el("td", i.incident),
      el("td", i.problem || i.issue_type_id),
      el("td", weekText(i.onset)),
      el("td", weekText(i.naive)),
      el("td", i.ours === "Not flagged" ? i.ours : weekText(i.ours)),
      el("td", lead, i.lead_weeks > 0 ? "lead-good" : i.lead_weeks < 0 ? "lead-bad" : ""),
    );
    tbody.append(tr);
  });
  table.append(thead, tbody);
  const incidents = el("div", null, "incidents-table");
  incidents.append(table);

  const statement = el("p", null, "statement");
  statement.append(
    `Of ${s.marked_actionable.toLocaleString()} messages marked as needing action, `,
    el("strong", `${(s.actionable_correct * 100).toFixed(1)}% truly did`),
    `. Of ${s.marked_urgent.toLocaleString()} marked urgent, `,
    el("strong", `${(s.urgent_correct * 100).toFixed(1)}% truly needed action`),
    ".",
  );

  const flags = el(
    "p",
    `${s.flags_scored} early-warning flags in the scored weeks (${Number(s.flags_per_week).toFixed(2)} per week, limit 3): ` +
      `${s.flags_valid} valid, ${s.flags_rejected} rejected.`,
    "eval-note",
  );
  const note = el(
    "p",
    "The labelled weeks were also used to train the model, so the classification part is higher here than it " +
      "will be on new data. The accuracy check below tests on messages the model has not seen.",
    "eval-note",
  );

  const raw = el("details", null, "raw-output");
  raw.append(el("summary", "Full evaluate.py output"), el("pre", result.output));

  $("evaluation").replaceChildren(head, scores, incidents, statement, flags, note, raw);
  $("download-report").hidden = false;
}

async function runEvaluate() {
  const button = $("run-evaluate");
  button.disabled = true;
  $("evaluation").replaceChildren(el("p", "Running evaluate.py...", "hint"));
  try {
    renderEvaluation(await api("/api/evaluate", { method: "POST" }));
  } catch (error) {
    $("evaluation").replaceChildren(el("p", error.message, "error-text"));
  } finally {
    button.disabled = false;
  }
}

async function loadLastEvaluation() {
  const last = await api("/api/evaluate");
  if (last) renderEvaluation(last);
}

async function loadStores() {
  const stores = await api("/api/stores");
  const select = $("review-store");
  const byRegion = new Map();
  stores.forEach((s) => {
    if (!byRegion.has(s.region)) byRegion.set(s.region, []);
    byRegion.get(s.region).push(s);
  });
  byRegion.forEach((list, region) => {
    const group = document.createElement("optgroup");
    group.label = `${region} region`;
    list.forEach((s) => {
      const option = el("option", s.name);
      option.value = s.store_id;
      group.append(option);
    });
    select.append(group);
  });
}

function clarity(confidence) {
  if (confidence >= 0.75) return "clear";
  if (confidence >= 0.55) return "fairly clear";
  return "unclear, worth a human look";
}

function renderReview(r) {
  const title = el("div", null, "result-title");
  title.append(el("h3", r.problem), el("span", SEVERITY_NAME[r.severity], `pill ${r.severity}`));
  title.append(el("span", r.needs_action ? "Needs action" : "No action", `pill ${r.needs_action ? "yes" : "no"}`));
  const parts = [title];
  if (r.needs_action) {
    const action = el("p", null, "action");
    action.append(el("strong", r.action), el("span", ` · ${r.team} · deadline ${r.deadline}`, "team"));
    parts.push(action);
  } else {
    parts.push(el("p", r.reason, "reason"));
  }
  parts.push(el("p", `${r.store} · ${r.language} · the call is ${clarity(r.confidence)}`, "meta facts"));
  $("review-result").replaceChildren(...parts);
}

async function checkReview(event) {
  event.preventDefault();
  const text = $("review-text").value.trim();
  if (text.length < 3) return;
  const button = $("review-submit");
  button.disabled = true;
  const rating = $("review-rating").value;
  try {
    const result = await api("/api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        channel: $("review-channel").value,
        store_id: $("review-store").value || null,
        rating: rating ? Number(rating) : null,
      }),
    });
    renderReview(result);
    const item = el("li");
    item.append(el("b", result.problem), ` (${result.severity}): ${text.length > 90 ? `${text.slice(0, 87)}...` : text}`);
    $("review-history").prepend(item);
  } catch (error) {
    $("review-result").replaceChildren(el("p", error.message, "error-text"));
  } finally {
    button.disabled = false;
  }
}

async function uploadFile(event) {
  event.preventDefault();
  const file = $("file").files[0];
  if (!file) return;
  const buttons = document.querySelectorAll("button");
  buttons.forEach((b) => { b.disabled = true; });
  notice(`Reading ${file.name}. Large files can take up to a minute.`);
  try {
    const form = new FormData();
    form.append("file", file);
    const status = await api("/api/upload", { method: "POST", body: form });
    notice("");
    showStatus(status);
    await refresh();
  } catch (error) {
    notice(error.message, true);
  } finally {
    buttons.forEach((b) => { b.disabled = false; });
  }
}

async function showDataset() {
  try {
    showStatus(await api("/api/dataset", { method: "POST" }));
    notice("");
    await refresh();
  } catch (error) {
    notice(error.message, true);
  }
}

$("file").addEventListener("change", () => {
  $("file-name").textContent = $("file").files[0]?.name || "Choose a CSV";
});
$("upload-form").addEventListener("submit", uploadFile);
$("show-dataset").addEventListener("click", showDataset);
$("week").addEventListener("change", refresh);
$("region").addEventListener("change", async () => {
  await refresh();
  focusRegion($("region").value);
});
$("drawer-week").addEventListener("change", loadCases);
$("drawer-close").addEventListener("click", () => $("cases-dialog").close());
$("cases-dialog").addEventListener("click", (event) => {
  // A click on the dimmed backdrop lands on the dialog itself.
  if (event.target === $("cases-dialog")) $("cases-dialog").close();
});
$("check-accuracy").addEventListener("click", checkAccuracy);
$("run-evaluate").addEventListener("click", runEvaluate);
$("review-form").addEventListener("submit", checkReview);

loadRule().catch((error) => notice(error.message, true));
loadLastEvaluation().catch((error) => notice(error.message, true));
loadStatus().catch((error) => notice(error.message, true));
