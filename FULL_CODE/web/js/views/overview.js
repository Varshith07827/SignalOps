// Head office overview: the week in numbers, the store board, stores doing well, early warnings and teams.
import { api, query } from "../api.js";
import { icon } from "../icons.js";
import { ctx, onCasesChanged } from "../state.js";
import {
  card,
  dayText,
  el,
  emptyState,
  errorBox,
  openDrawer,
  plural,
  segmented,
  severityPill,
  skeleton,
  statusPill,
} from "../ui.js";
import { bubbleBoard } from "./bubbles.js";
import { openCase, openCaseList } from "./case-panel.js";
import { openStore } from "./store-panel.js";
import { storeMap } from "./store-map.js";

function kpis(week, openReports) {
  const row = el("div", null, "kpis");
  const tile = (label, value, foot, tone, iconName) => {
    const box = el("div", null, `kpi ${tone || ""}`);
    const head = el("div", null, "kpi-head");
    head.append(icon(iconName, 18), el("span", label));
    box.append(head, el("p", value.toLocaleString(), "kpi-value"), el("p", foot, "kpi-foot"));
    return box;
  };
  const critical = week.teams.reduce((sum, t) => sum + t.critical, 0);
  row.append(
    tile("Messages", week.messages, "Reviews, app, staff notes, calls", "", "message"),
    tile("Need action", week.need_action, `${Math.round((week.need_action / Math.max(week.messages, 1)) * 100)}% of messages`, "", "cases"),
    tile("Urgent", week.urgent, `${critical} critical`, "danger", "alert"),
    tile("Early warnings", week.warnings, "Rising at one store", "warning", "trendUp"),
    tile("Open store reports", openReports, "Reported by store managers", "", "report"),
  );
  return row;
}

function boardCard() {
  const views = {};
  const legend = el("div", null, "legend");
  for (const [cls, text] of [["critical", "Critical"], ["high", "High"], ["medium", "Medium"], ["low", "Low"], ["clear", "No cases"]]) {
    const item = el("span");
    item.append(el("i", null, `dot ${cls}`), text);
    legend.append(item);
  }
  const ring = el("span");
  ring.append(el("i", null, "dot ring"), "Early warning");
  legend.append(ring, el("span", "Size = cases this week", "legend-note"));

  const pick = (pin) => openStore(pin.store_id, pin.name);
  views.bubbles = bubbleBoard({ onPick: pick });
  views.map = storeMap({ onPick: pick });
  let mode = "bubbles";
  let pins = [];
  const stage = el("div", null, "board-stage");
  stage.append(views.bubbles.root, views.map.root);
  views.map.root.hidden = true;

  const switcher = segmented(
    [
      { value: "bubbles", label: "Bubbles", icon: "bubbles" },
      { value: "map", label: "Map", icon: "map" },
    ],
    mode,
    (next) => {
      mode = next;
      views.bubbles.root.hidden = mode !== "bubbles";
      views.map.root.hidden = mode !== "map";
      if (mode === "map") {
        views.map.update(pins);
        views.map.resize();
      }
    },
    "Board view",
  );
  const filters = segmented(
    [
      { value: "all", label: "All" },
      { value: "urgent", label: "Urgent" },
      { value: "warnings", label: "Early warnings" },
    ],
    "all",
    (next) => {
      views.bubbles.filter(next);
      views.map.filter(next);
    },
    "Show stores",
  );
  const { section, body } = card("Store board", {
    subtitle: "Every store this week. Click one for its problems.",
    actions: [filters.root, switcher.root],
    className: "board-card",
  });
  body.append(stage, legend);
  return {
    section,
    update(next) {
      pins = next;
      views.bubbles.update(pins);
      if (mode === "map") views.map.update(pins);
    },
  };
}

function doingWell(stores) {
  const { section, body } = card("Doing well this week", { subtitle: "Ratings, compliments and few complaints" });
  if (!stores.length) {
    body.append(emptyState("No data this week", null, "star"));
    return section;
  }
  const list = el("ol", null, "rank-list");
  stores.forEach((store, i) => {
    const item = el("li");
    const row = el("button", null, "rank-row", { type: "button" });
    const rank = el("span", String(i + 1), "rank-badge");
    const text = el("span", null, "rank-text");
    text.append(el("strong", store.name), el("span", `${store.city} · ${store.reasons[0]}`, "muted"));
    const score = el("span", null, "rank-score");
    score.append(el("b", String(store.score)), el("span", "score"));
    row.append(rank, text, score);
    row.addEventListener("click", () => openStore(store.store_id, store.name));
    item.append(row);
    if (i === 0 && store.quote) item.append(el("blockquote", store.quote, "quote small"));
    list.append(item);
  });
  body.append(list);
  return section;
}

function warningItem(w) {
  const row = el("button", null, "warning-item", { type: "button" });
  row.append(el("strong", w.store), el("span", w.problem), el("span", `${plural(w.reports, "report")} · ${w.team}`, "muted"));
  row.addEventListener("click", () => openCaseList({ store: w.store_id, issue: w.issue_type_id }, w.problem, w.store));
  return row;
}

function warningsCard(all) {
  const now = all.filter((w) => w.week === ctx.week);
  const earlier = all.filter((w) => w.week < ctx.week);
  const more = el("button", `Earlier (${earlier.length})`, "link-btn", { type: "button" });
  more.addEventListener("click", () => {
    const list = el("div", null, "warning-list");
    earlier.forEach((w) => {
      const item = warningItem(w);
      item.prepend(el("span", `Week of ${dayText(w.week)}`, "eyebrow"));
      list.append(item);
    });
    openDrawer({ title: "Earlier early warnings", eyebrow: `${earlier.length} before this week`, body: list });
  });
  const { section, body } = card("Early warnings", { subtitle: "Small but rising at one store", actions: [more] });
  const list = el("div", null, "warning-list scroll");
  if (!now.length) list.append(emptyState("No warnings this week", "No store has an unusual rise.", "check"));
  now.forEach((w) => list.append(warningItem(w)));
  body.append(list);
  return section;
}

function teamsCard(teams, go) {
  const { section, body } = card("Who must act", { subtitle: "Cases by team and severity. Click a team for its list." });
  if (!teams.length) {
    body.append(emptyState("Nothing to act on", null));
    return section;
  }
  const widest = Math.max(...teams.map((t) => t.total));
  const list = el("div", null, "team-bars");
  for (const t of teams) {
    const row = el("button", null, "team-bar", { type: "button" });
    const head = el("span", null, "team-bar-head");
    const urgent = t.critical + t.high;
    head.append(el("strong", t.team), el("span", `${t.total} cases${urgent ? ` · ${urgent} urgent` : ""}`, "muted"));
    const track = el("span", null, "bar-track");
    track.style.width = `${Math.max(6, (t.total / widest) * 100)}%`;
    for (const s of ["critical", "high", "medium", "low"]) {
      if (!t[s]) continue;
      const seg = el("span", null, `seg ${s}`, { title: `${s}: ${t[s]}` });
      seg.style.flexGrow = String(t[s]);
      track.append(seg);
    }
    row.append(head, track);
    row.addEventListener("click", () => go("cases", { team: t.team }));
    list.append(row);
  }
  body.append(list);
  return section;
}

function reportsCard(go) {
  const all = el("button", "View all", "link-btn", { type: "button" });
  all.addEventListener("click", () => go("cases", { tab: "reports" }));
  const { section, body } = card("Latest store reports", { subtitle: "Raised by store managers in the app", actions: [all] });
  async function load() {
    body.replaceChildren(skeleton(3));
    try {
      const reports = await api("/api/reports");
      const list = el("div", null, "report-list");
      if (!reports.length) list.append(emptyState("No reports yet", "Store managers' reports appear here.", "report"));
      reports.slice(0, 6).forEach((r) => {
        const row = el("button", null, "report-row", { type: "button" });
        const text = el("span", null, "report-text");
        text.append(el("strong", r.problem), el("span", `${r.store} · ${dayText(r.opened)}`, "muted"));
        const tags = el("span", null, "tag-row");
        tags.append(severityPill(r.severity), statusPill(r.status, r.status_text));
        row.append(text, tags);
        row.addEventListener("click", () => openCase(r.ref));
        list.append(row);
      });
      body.replaceChildren(list);
      return reports;
    } catch (error) {
      body.replaceChildren(errorBox(error.message));
      return [];
    }
  }
  return { section, load };
}

export async function render(root, _params, { go }) {
  const page = el("div", null, "page overview");
  page.append(skeleton(4));
  root.append(page);
  const week = query({ week: ctx.week });
  let data;
  try {
    data = await Promise.all([
      api(`/api/week?${week}`),
      api(`/api/map?${week}`),
      api(`/api/reputation?${week}`),
      api("/api/warnings"),
    ]);
  } catch (error) {
    page.replaceChildren(errorBox(error.message));
    return null;
  }
  const [weekData, pins, reputation, warnings] = data;
  const board = boardCard();
  const reports = reportsCard(go);
  const kpiSlot = el("div");
  const grid = el("div", null, "grid overview-grid");
  const side = el("div", null, "stack");
  side.append(doingWell(reputation), warningsCard(warnings));
  grid.append(board.section, side);
  const lower = el("div", null, "grid two");
  lower.append(teamsCard(weekData.teams, go), reports.section);
  page.replaceChildren(kpiSlot, grid, lower);
  board.update(pins);

  async function refreshReports() {
    const list = await reports.load();
    kpiSlot.replaceChildren(kpis(weekData, list.filter((r) => r.status !== "closed").length));
  }
  await refreshReports();
  const stop = onCasesChanged(async () => {
    refreshReports();
    board.update(await api(`/api/map?${week}`).catch(() => pins));
  });
  return stop;
}

