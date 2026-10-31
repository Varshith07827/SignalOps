// A store manager's home: this week's actions for their store, confirmations head office is waiting for,
// their own reports, early warnings, reputation and the last problem solved.
import { api, query } from "../api.js";
import { icon } from "../icons.js";
import { casesChanged, ctx, onCasesChanged } from "../state.js";
import {
  button,
  card,
  dayText,
  el,
  emptyState,
  errorBox,
  pill,
  plural,
  SEVERITIES,
  severityPill,
  skeleton,
  statusPill,
  timeText,
  toast,
} from "../ui.js";
import { openCase, openCaseList } from "./case-panel.js";
import { lastSolved, quoteBlock, reputationLine, statTiles, storeOverview } from "./store-panel.js";

function hero(store, reputation) {
  const box = el("section", null, "hero");
  const text = el("div", null, "hero-text");
  text.append(el("p", `${store.format} · ${store.city} · ${store.region} region`, "eyebrow"), el("h2", store.name));
  const line = reputationLine(reputation);
  if (line) text.append(line);
  box.append(text);
  return box;
}

function confirmations(messages) {
  const waiting = messages.filter((m) => m.kind === "confirm_request" && !m.answered && m.status === "awaiting_confirmation");
  const box = el("div", null, "stack");
  for (const m of waiting) {
    const banner = el("div", null, "banner");
    banner.append(icon("message", 20));
    const text = el("div", null, "banner-text");
    text.append(el("strong", "Head office is waiting for your answer"), el("span", m.body));
    const actions = el("div", null, "banner-actions");
    const no = button("No, still a problem", { kind: "secondary", small: true, onClick: () => openCase(m.ref) });
    const yes = button("Yes, it's fixed", { kind: "primary", small: true, iconName: "check" });
    yes.addEventListener("click", async () => {
      yes.disabled = true;
      try {
        await api(`/api/cases/${encodeURIComponent(m.ref)}/confirm`, { method: "POST", body: { fixed: true, comment: "" } });
        toast("Thanks, the case is closed");
        casesChanged();
      } catch (error) {
        toast(error.message, "error");
        yes.disabled = false;
      }
    });
    actions.append(no, yes);
    banner.append(text, actions);
    box.append(banner);
  }
  return box;
}

// Group the week's cases by problem so the manager sees a short list of things to do.
function todoCard(cases, storeName) {
  const groups = new Map();
  for (const c of cases.filter((x) => x.status !== "closed")) {
    if (!groups.has(c.issue_type_id)) groups.set(c.issue_type_id, []);
    groups.get(c.issue_type_id).push(c);
  }
  const rank = (list) => Math.min(...list.map((c) => SEVERITIES.indexOf(c.severity)));
  const ordered = [...groups.values()].sort((a, b) => rank(a) - rank(b) || b.length - a.length);
  const { section, body } = card("To do this week", { subtitle: "Open problems at your store, most urgent first" });
  if (!ordered.length) {
    body.append(emptyState("All clear", "No open problems at your store this week."));
    return section;
  }
  const list = el("div", null, "todo-list");
  for (const group of ordered) {
    const worst = SEVERITIES[rank(group)];
    const first = group.find((c) => c.severity === worst);
    const due = group.map((c) => c.due).filter(Boolean).sort()[0];
    const row = el("button", null, `todo-item sev-${worst}`, { type: "button" });
    const main = el("span", null, "todo-main");
    const title = el("span", null, "case-row-title");
    title.append(el("strong", first.problem));
    if (group.some((c) => c.early_warning)) title.append(pill("Early warning", "warning"));
    main.append(title, el("span", `${first.action} · ${first.team}`, "muted"));
    const side = el("span", null, "todo-side");
    side.append(severityPill(worst), el("span", plural(group.length, "case"), "muted"));
    if (due) side.append(el("span", `Due ${timeText(due)}`, "due"));
    row.append(main, side);
    row.addEventListener("click", () =>
      group.length === 1 ? openCase(first.ref) : openCaseList({ issue: first.issue_type_id }, first.problem, storeName),
    );
    list.append(row);
  }
  body.append(list);
  return section;
}

function reportsCard(reports, go) {
  const add = button("Report a problem", { kind: "primary", small: true, iconName: "report", onClick: () => go("report") });
  const { section, body } = card("My reports", { subtitle: "Problems you raised and where they stand", actions: [add] });
  if (!reports.length) {
    body.append(emptyState("No reports yet", "Report a problem from a staff note and head office will see it.", "report"));
    return section;
  }
  const list = el("div", null, "report-list");
  for (const r of reports.slice(0, 6)) {
    const row = el("button", null, "report-row", { type: "button" });
    const text = el("span", null, "report-text");
    text.append(el("strong", r.problem), el("span", `${r.ref} · ${dayText(r.opened)}`, "muted"));
    const tags = el("span", null, "tag-row");
    tags.append(statusPill(r.status, r.status_text));
    row.append(text, tags);
    row.addEventListener("click", () => openCase(r.ref));
    list.append(row);
  }
  body.append(list);
  return section;
}

function sideCard(title, content) {
  const { section, body } = card(title);
  body.append(content);
  return section;
}

export async function render(root, _params, { go }) {
  const page = el("div", null, "page store-home");
  page.append(skeleton(6));
  root.append(page);
  const storeId = ctx.user.store.store_id;

  async function load() {
    try {
      const [overview, cases, reports, inbox] = await Promise.all([
        storeOverview(storeId),
        api(`/api/cases?${query({ week: ctx.week })}`),
        api("/api/reports"),
        api("/api/inbox"),
      ]);
      const store = overview.store;
      const rep = overview.reputation;
      const warnings = el("div", null, "warning-list");
      if (!store.warnings.length) warnings.append(emptyState("No early warnings", "Nothing is rising unusually at your store.", "check"));
      store.warnings.forEach((w) => {
        const row = el("p", null, "warning-row");
        row.append(pill("Early warning", "warning"), el("span", w));
        warnings.append(row);
      });
      const grid = el("div", null, "grid store-grid");
      const main = el("div", null, "stack");
      main.append(todoCard(cases.cases, store.name), reportsCard(reports, go));
      const side = el("div", null, "stack");
      side.append(sideCard("Early warnings", warnings), sideCard("Last solved", lastSolved(store.last_solved)));
      if (rep?.quote) side.append(sideCard("What customers liked", quoteBlock(rep.quote)));
      grid.append(main, side);
      page.replaceChildren(
        hero(store, rep),
        confirmations(inbox.messages),
        statTiles([
          { label: "Cases this week", value: String(store.cases) },
          { label: "Urgent", value: String(store.urgent), tone: store.urgent ? "danger" : "" },
          { label: "Early warnings", value: String(store.warnings.length), tone: store.warnings.length ? "warning" : "" },
          { label: "Avg rating", value: rep?.rating ? `${rep.rating}★` : "–" },
          { label: "Compliments", value: String(rep?.compliments ?? 0), tone: "good" },
        ]),
        grid,
      );
    } catch (error) {
      page.replaceChildren(errorBox(error.message));
    }
  }
  await load();
  return onCasesChanged(load);
}
