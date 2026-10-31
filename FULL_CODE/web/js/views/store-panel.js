// A store's week in a side panel (head office) or on the store's home page: problems, warnings,
// reputation and the last problem solved.
import { api, query } from "../api.js";
import { icon } from "../icons.js";
import { ctx } from "../state.js";
import { button, dayText, el, emptyState, errorBox, openDrawer, pill, plural, skeleton } from "../ui.js";
import { openCaseList } from "./case-panel.js";

export function statTiles(items) {
  const grid = el("dl", null, "stat-tiles");
  for (const { label, value, tone } of items) {
    const tile = el("div", null, `stat-tile ${tone || ""}`);
    tile.append(el("dt", label), el("dd", value));
    grid.append(tile);
  }
  return grid;
}

export function problemList(store) {
  if (!store.problems.length) return emptyState("Nothing to act on", "No problems needing action this week.");
  const list = el("ul", null, "problem-list");
  for (const p of store.problems) {
    const item = el("li");
    const row = el("button", null, "problem-row", { type: "button" });
    row.append(el("i", null, `dot ${p.severity}`), el("span", p.problem, "problem-name"), el("b", plural(p.cases, "case")));
    row.addEventListener("click", () => openCaseList({ store: store.store_id, issue: p.issue_type_id }, p.problem, store.name));
    item.append(row);
    list.append(item);
  }
  return list;
}

export function lastSolved(solved) {
  if (!solved) return emptyState("Nothing solved yet", "Once a problem is fixed and confirmed, it shows here.", "clock");
  const box = el("div", null, `solved-box${solved.confirmed ? " confirmed" : ""}`);
  box.append(icon("check", 18));
  const text = el("div");
  text.append(el("strong", solved.problem));
  text.append(
    el(
      "span",
      solved.confirmed
        ? `Fix confirmed by the store on ${dayText(solved.last_report)}`
        : `${solved.reports} complaints up to ${dayText(solved.last_report)}, none since`,
    ),
  );
  box.append(text);
  return box;
}

export function reputationLine(reputation) {
  if (!reputation) return null;
  const line = el("div", null, "reputation-line");
  line.append(icon("star", 16), el("strong", `#${reputation.rank} of ${reputation.of}`), el("span", "for customer reputation this week"));
  return line;
}

export function quoteBlock(text) {
  return text ? el("blockquote", text, "quote") : null;
}

function storeBody(data) {
  const store = data.store;
  const rep = data.reputation;
  const body = el("div", null, "store-detail");
  const meta = el("p", `${store.format} · ${store.city} · ${store.region} region`, "muted");
  body.append(meta);
  const line = reputationLine(rep);
  if (line) body.append(line);
  body.append(
    statTiles([
      { label: "Cases this week", value: String(store.cases) },
      { label: "Urgent", value: String(store.urgent), tone: store.urgent ? "danger" : "" },
      { label: "Avg rating", value: rep?.rating ? `${rep.rating}★` : "–" },
      { label: "Compliments", value: String(rep?.compliments ?? 0), tone: "good" },
    ]),
  );
  for (const warning of store.warnings) {
    const row = el("p", null, "warning-row");
    row.append(pill("Early warning", "warning"), el("span", warning));
    body.append(row);
  }
  const problems = el("section", null, "drawer-section");
  problems.append(el("h3", "Problems this week"), problemList(store));
  const solved = el("section", null, "drawer-section");
  solved.append(el("h3", "Last solved"), lastSolved(store.last_solved));
  body.append(problems, solved);
  if (rep?.quote) {
    const liked = el("section", null, "drawer-section");
    liked.append(el("h3", "What customers liked"), quoteBlock(rep.quote));
    body.append(liked);
  }
  return body;
}

export async function storeOverview(storeId) {
  return api(`/api/stores/${encodeURIComponent(storeId)}/overview?${query({ week: ctx.week })}`);
}

export async function openStore(storeId, name) {
  const panel = openDrawer({ title: name || "Store", eyebrow: "Store", body: skeleton(6) });
  try {
    const data = await storeOverview(storeId);
    const all = button(`See all ${plural(data.store.cases, "case")}`, {
      kind: "primary",
      onClick: () => openCaseList({ store: storeId }, "All cases this week", data.store.name),
    });
    panel.update({ title: data.store.name, eyebrow: `${data.store.region} region`, body: storeBody(data), footer: all });
  } catch (error) {
    panel.update({ body: errorBox(error.message) });
  }
}
