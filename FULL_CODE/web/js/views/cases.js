// Cases: the week's cases from customer feedback, and problems reported by stores, with filters.
import { api, query } from "../api.js";
import { icon } from "../icons.js";
import { ctx, isAdmin, onCasesChanged } from "../state.js";
import {
  dropdown,
  el,
  emptyState,
  errorBox,
  pill,
  segmented,
  SEVERITY_NAME,
  severityPill,
  skeleton,
  statusPill,
  timeText,
} from "../ui.js";
import { openCase } from "./case-panel.js";

const STATUS_OPTIONS = [
  { value: "active", label: "Not closed" },
  { value: "all", label: "Any status" },
  { value: "open", label: "Open" },
  { value: "in_progress", label: "In progress" },
  { value: "awaiting_confirmation", label: "Waiting for store" },
  { value: "reopened", label: "Reopened" },
  { value: "closed", label: "Closed" },
];

function table(cases, showStore) {
  const wrap = el("div", null, "table-wrap");
  const grid = el("table", null, "data-table");
  const head = el("tr");
  for (const h of ["Case", "Problem", ...(showStore ? ["Store"] : []), "Team", "Severity", "Status", "Deadline"]) {
    head.append(el("th", h, null, { scope: "col" }));
  }
  const thead = el("thead");
  thead.append(head);
  const tbody = el("tbody");
  for (const c of cases) {
    const row = el("tr", null, null, { tabindex: "0" });
    const problem = el("td", null, "cell-problem");
    const title = el("div", null, "cell-title");
    title.append(el("strong", c.problem));
    if (c.early_warning) title.append(pill("Early warning", "warning"));
    problem.append(title, el("div", c.quote, "cell-quote"));
    const severity = el("td");
    severity.append(severityPill(c.severity));
    const status = el("td");
    status.append(statusPill(c.status, c.status_text));
    row.append(el("td", c.ref, "cell-ref"), problem);
    if (showStore) row.append(el("td", c.store, "cell-store"));
    row.append(el("td", c.team), severity, status, el("td", c.due ? timeText(c.due) : "–", "cell-due"));
    row.addEventListener("click", () => openCase(c.ref));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter") openCase(c.ref);
    });
    tbody.append(row);
  }
  grid.append(thead, tbody);
  wrap.append(grid);
  return wrap;
}

export async function render(root, params, { subtitle }) {
  const admin = isAdmin();
  const page = el("div", null, "page cases-page");
  root.append(page);
  const state = {
    tab: params.tab === "reports" ? "reports" : "feedback",
    team: params.team || "all",
    status: "active",
    severity: "all",
    store: "all",
    search: "",
  };
  let rows = [];

  const tabs = segmented(
    [
      { value: "feedback", label: "From customer feedback", icon: "message" },
      { value: "reports", label: "Store reports", icon: "report" },
    ],
    state.tab,
    (next) => {
      state.tab = next;
      load();
    },
    "Case source",
  );
  const team = dropdown({ options: [{ value: "all", label: "All teams" }], value: "all", label: "Team", onChange: (v) => set("team", v) });
  const status = dropdown({ options: STATUS_OPTIONS, value: state.status, label: "Status", onChange: (v) => set("status", v) });
  const store = dropdown({ options: [{ value: "all", label: "All stores" }], value: "all", label: "Store", searchable: true, onChange: (v) => set("store", v) });
  const severity = segmented(
    [{ value: "all", label: "All" }, ...Object.entries(SEVERITY_NAME).map(([value, label]) => ({ value, label }))],
    "all",
    (v) => set("severity", v),
    "Severity",
  );
  const search = el("input", null, "search-input", { type: "search", placeholder: "Search problem, store or message", "aria-label": "Search cases" });
  search.addEventListener("input", () => set("search", search.value.trim().toLowerCase()));
  const searchBox = el("div", null, "search-box");
  searchBox.append(icon("review", 16), search);

  const toolbar = el("div", null, "toolbar");
  const filters = el("div", null, "filters");
  filters.append(team.root, status.root);
  if (admin) filters.append(store.root);
  filters.append(severity.root);
  toolbar.append(tabs.root, searchBox);
  const count = el("p", null, "result-count", { role: "status" });
  const results = el("div", null, "card table-card");
  page.append(toolbar, filters, count, results);

  if (admin) {
    api("/api/stores")
      .then((stores) =>
        store.setOptions(
          [{ value: "all", label: "All stores" }, ...stores.map((s) => ({ value: s.store_id, label: s.name, hint: s.city, group: `${s.region} region` }))],
          "all",
        ),
      )
      .catch(() => {});
  }

  function set(key, value) {
    state[key] = value;
    paint();
  }

  function paint() {
    const shown = rows.filter(
      (c) =>
        (state.team === "all" || c.team === state.team) &&
        (state.store === "all" || c.store_id === state.store) &&
        (state.severity === "all" || c.severity === state.severity) &&
        (state.status === "all" || (state.status === "active" ? c.status !== "closed" : c.status === state.status)) &&
        (!state.search || `${c.problem} ${c.store} ${c.quote} ${c.ref}`.toLowerCase().includes(state.search)),
    );
    count.textContent = `${shown.length.toLocaleString()} of ${rows.length.toLocaleString()} cases`;
    if (!shown.length) {
      results.replaceChildren(emptyState("No cases match", rows.length ? "Try clearing a filter." : "Nothing here yet.", "cases"));
      return;
    }
    results.replaceChildren(table(shown, admin));
  }

  async function load() {
    results.replaceChildren(skeleton(8));
    subtitle(state.tab === "reports" ? "Reported by store managers in the app" : undefined);
    try {
      rows = state.tab === "reports" ? await api("/api/reports") : (await api(`/api/cases?${query({ week: ctx.week })}`)).cases;
    } catch (error) {
      results.replaceChildren(errorBox(error.message));
      return;
    }
    const teams = [...new Set(rows.map((c) => c.team))].sort();
    team.setOptions([{ value: "all", label: "All teams" }, ...teams.map((t) => ({ value: t, label: t }))], state.team);
    state.team = team.value;
    paint();
  }

  await load();
  return onCasesChanged(load);
}
