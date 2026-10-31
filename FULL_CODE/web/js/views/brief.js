// The weekly one-page brief for a region: top 5 issues with owner, severity, trend, stores and quotes.
import { api, query } from "../api.js";
import { icon } from "../icons.js";
import { ctx } from "../state.js";
import { button, card, el, emptyState, errorBox, pill, plural, regionText, severityPill, skeleton, weekText } from "../ui.js";
import { openCaseList } from "./case-panel.js";

const TREND = {
  Rising: ["trendUp", "up"],
  Falling: ["trendDown", "down"],
  Steady: ["clock", "steady"],
  "New this week": ["alert", "new"],
};

function issueCard(item, rank) {
  const box = el("article", null, `brief-item sev-${item.severity}`);
  const head = el("div", null, "brief-head");
  head.append(el("span", String(rank), "brief-rank"));
  const titles = el("div", null, "brief-titles");
  const tags = el("div", null, "tag-row");
  tags.append(severityPill(item.severity));
  if (item.early_warning) tags.append(pill("Early warning", "warning"));
  titles.append(el("h3", item.problem), tags);
  head.append(titles);

  const todo = el("p", null, "todo");
  todo.append(icon("team", 18), el("span", `${item.action} · ${item.team}`));

  const [trendIcon, trendClass] = TREND[item.trend] || ["clock", "steady"];
  const trend = el("span", null, `trend ${trendClass}`);
  trend.append(icon(trendIcon, 16), el("span", item.trend));
  const numbers = el("div", null, "brief-numbers");
  numbers.append(
    el("span", `${plural(item.incidents, "case")} from ${plural(item.reports, "message")}`),
    trend,
    el("span", `Last week ${item.last_week}`, "muted"),
  );
  const stores = el("p", item.stores.length ? item.stores.join(", ") : "Online orders and app", "brief-stores");
  box.append(head, todo, numbers, stores);
  if (item.quotes[0]) box.append(el("blockquote", item.quotes[0], "quote"));
  const evidence = button("See the cases", { kind: "ghost", small: true });
  evidence.addEventListener("click", () =>
    openCaseList({ region: ctx.region, issue: item.issue_type_id }, item.problem, regionText(ctx.region)),
  );
  box.append(evidence);
  return box;
}

function ruleCard(rule) {
  const { section, body } = card("Escalation rule", { subtitle: "Who is told, and how fast" });
  const list = el("ol", null, "rule-list");
  for (const r of rule) {
    const item = el("li");
    const text = el("div");
    text.append(el("strong", r.when), el("span", r.who, "muted"));
    item.append(text, el("span", r.within === "-" ? "No deadline" : r.within, "rule-time"));
    list.append(item);
  }
  body.append(list);
  return section;
}

export async function render(root) {
  const page = el("div", null, "page brief");
  page.append(skeleton(5));
  root.append(page);
  try {
    const [items, rule] = await Promise.all([
      api(`/api/top-issues?${query({ region: ctx.region, week: ctx.week })}`),
      api("/api/escalation-rule"),
    ]);
    const print = button("Print or save as PDF", { kind: "secondary", iconName: "print", onClick: () => window.print() });
    const { section, body } = card(`Top ${items.length || 5} issues · ${regionText(ctx.region)}`, {
      subtitle: `Week of ${weekText(ctx.week)}. Ranked by severity, cases and trend.`,
      actions: [print],
      className: "brief-card",
    });
    if (!items.length) body.append(emptyState("Nothing to act on", "No problems needing action in this region this week."));
    const list = el("div", null, "brief-list");
    items.forEach((item, i) => list.append(issueCard(item, i + 1)));
    body.append(list);
    const grid = el("div", null, "grid brief-grid");
    grid.append(section, ruleCard(rule));
    page.replaceChildren(grid);
  } catch (error) {
    page.replaceChildren(errorBox(error.message));
  }
  return null;
}
