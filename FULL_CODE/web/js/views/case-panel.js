// The case side panel: what happened, what to do, every message, the timeline and the workflow actions.
import { api, query } from "../api.js";
import { icon } from "../icons.js";
import { casesChanged, ctx } from "../state.js";
import {
  button,
  el,
  emptyState,
  errorBox,
  openDrawer,
  pill,
  plural,
  severityPill,
  skeleton,
  statusPill,
  timeText,
  toast,
} from "../ui.js";

const EVENT_ICON = { reported: "report", started: "clock", note: "message", resolved: "check", confirmed: "check", not_fixed: "alert" };

// One row in any list of cases. Clicking opens the case.
export function caseRow(c) {
  const row = el("button", null, `case-row sev-${c.severity}`, { type: "button" });
  const main = el("span", null, "case-row-main");
  const title = el("span", null, "case-row-title");
  title.append(el("strong", c.problem));
  if (c.early_warning) title.append(pill("Early warning", "warning"));
  main.append(title, el("span", c.quote, "case-row-quote"));
  const meta = el("span", null, "case-row-meta");
  meta.append(
    el("span", c.store),
    el("span", c.due ? `Due ${timeText(c.due)}` : "No deadline"),
    el("span", c.reports > 1 ? plural(c.reports, "report") : c.channels.join(", ") || "1 report"),
  );
  main.append(meta);
  const side = el("span", null, "case-row-side");
  side.append(severityPill(c.severity), statusPill(c.status, c.status_text));
  row.append(main, side);
  row.addEventListener("click", () => openCase(c.ref));
  return row;
}

function facts(c) {
  const grid = el("dl", null, "facts-grid");
  const add = (label, value) => {
    const cell = el("div");
    cell.append(el("dt", label), el("dd", value));
    grid.append(cell);
  };
  add("Store", c.store);
  add("Team", c.team);
  add("Reported", timeText(c.opened));
  add("Deadline", c.due ? timeText(c.due) : "None (weekly brief)");
  return grid;
}

function messages(c) {
  const list = el("ol", null, "message-list");
  for (const m of c.messages || []) {
    const item = el("li");
    const head = el("p", null, "message-head");
    head.append(el("strong", m.channel), el("span", timeText(m.at)));
    if (m.language) head.append(el("span", m.language));
    item.append(head, el("p", m.text, "message-text"));
    list.append(item);
  }
  return list;
}

function timeline(c) {
  if (!c.timeline.length) return emptyState("No actions yet", "Start work or mark it solved below.", "clock");
  const list = el("ol", null, "timeline");
  for (const event of c.timeline) {
    const item = el("li", null, `tl-${event.kind}`);
    const dot = el("span", null, "tl-dot");
    dot.append(icon(EVENT_ICON[event.kind] || "message", 14));
    const body = el("div", null, "tl-body");
    const head = el("p", null, "tl-head");
    head.append(el("strong", event.what), el("span", `${event.by} · ${timeText(event.at)}`));
    body.append(head);
    if (event.note) body.append(el("p", event.note, "tl-note"));
    item.append(dot, body);
    list.append(item);
  }
  return list;
}

function section(title, content) {
  const box = el("section", null, "drawer-section");
  box.append(el("h3", title), content);
  return box;
}

function noteForm({ label, placeholder, submitLabel, required, onSubmit, onCancel }) {
  const form = el("form", null, "inline-form");
  const area = el("textarea", null, null, { rows: "3", maxlength: "1000", placeholder, "aria-label": label });
  const error = el("p", null, "form-error", { role: "alert", hidden: "" });
  const row = el("div", null, "form-actions");
  const submit = button(submitLabel, { kind: "primary", type: "submit" });
  row.append(button("Cancel", { kind: "ghost", onClick: onCancel }), submit);
  form.append(el("p", label, "field-label"), area, error, row);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = area.value.trim();
    if (required && text.length < 3) {
      error.textContent = "Add a short note first.";
      error.hidden = false;
      area.focus();
      return;
    }
    submit.disabled = true;
    try {
      await onSubmit(text);
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
      submit.disabled = false;
    }
  });
  setTimeout(() => area.focus(), 0);
  return form;
}

function actions(panel, c) {
  const bar = el("div", null, "drawer-actions");
  const run = async (path, body, message) => {
    const updated = await api(`/api/cases/${encodeURIComponent(c.ref)}/${path}`, { method: "POST", body });
    toast(message);
    casesChanged();
    paint(panel, updated);
  };
  const showForm = (options) => panel.update({ footer: noteForm({ ...options, onCancel: () => paint(panel, c) }) });

  if (c.can.confirm) {
    const ask = el("div", null, "confirm-ask");
    ask.append(icon("message", 18), el("span", "Head office marked this solved. Is it fixed at your store?"));
    bar.append(ask);
    bar.append(
      button("No, still a problem", {
        kind: "secondary",
        onClick: () =>
          showForm({
            label: "What is still wrong?",
            placeholder: "For example: freezer is cold again but the door seal still leaks",
            submitLabel: "Send to head office",
            required: true,
            onSubmit: (comment) => run("confirm", { fixed: false, comment }, "Sent back to head office"),
          }),
      }),
      button("Yes, it's fixed", {
        kind: "primary",
        iconName: "check",
        onClick: () => run("confirm", { fixed: true, comment: "" }, "Thanks, the case is closed").catch((e) => toast(e.message, "error")),
      }),
    );
    return bar;
  }
  if (c.can.note) {
    bar.append(
      button("Add note", {
        kind: "ghost",
        iconName: "message",
        onClick: () =>
          showForm({
            label: "Note",
            placeholder: "What happened, who you spoke to, what's next",
            submitLabel: "Add note",
            required: true,
            onSubmit: (note) => run("note", { note }, "Note added"),
          }),
      }),
    );
  }
  if (c.can.start) {
    bar.append(
      button("Start work", {
        kind: "secondary",
        iconName: "clock",
        onClick: () => run("start", { note: "" }, "Marked in progress").catch((e) => toast(e.message, "error")),
      }),
    );
  }
  if (c.can.resolve) {
    bar.append(
      button("Mark solved", {
        kind: "primary",
        iconName: "check",
        onClick: () =>
          showForm({
            label: c.store_id ? "What was done? The store will be asked to confirm." : "What was done?",
            placeholder: "For example: compressor replaced by the AMC technician on Friday",
            submitLabel: c.store_id ? "Mark solved and ask the store" : "Mark solved",
            required: true,
            onSubmit: (note) =>
              run("resolve", { note }, c.store_id ? `Sent to ${c.store} for confirmation` : "Case closed"),
          }),
      }),
    );
  }
  return bar;
}

function paint(panel, c) {
  const body = el("div", null, "case-detail");
  const tags = el("div", null, "tag-row");
  tags.append(severityPill(c.severity), statusPill(c.status, c.status_text));
  if (c.early_warning) tags.append(pill("Early warning", "warning"));
  const todo = el("div", null, "todo");
  todo.append(icon("team", 18), el("span", `${c.action} · ${c.team}`));
  body.append(tags, todo, facts(c));
  if (c.messages?.length) body.append(section(`Messages (${c.messages.length})`, messages(c)));
  body.append(section("Timeline", timeline(c)));
  const origin = c.source === "store_report" ? "Store report" : "From customer feedback";
  panel.update({ title: c.problem, eyebrow: `${c.ref} · ${origin}`, body, footer: actions(panel, c) });
}

export async function openCase(ref) {
  const panel = openDrawer({ title: "Loading case…", eyebrow: ref, body: skeleton(6) });
  try {
    paint(panel, await api(`/api/cases/${encodeURIComponent(ref)}`));
  } catch (error) {
    panel.update({ title: "Case", body: errorBox(error.message) });
  }
}

// A list of cases in a side panel, e.g. one store's problem this week.
export async function openCaseList(filters, title, eyebrow) {
  const panel = openDrawer({ title, eyebrow, body: skeleton(5) });
  try {
    const data = await api(`/api/cases?${query({ week: ctx.week, ...filters })}`);
    const list = el("div", null, "case-list");
    if (!data.cases.length) list.append(emptyState("No cases", "Nothing to act on here this week."));
    data.cases.forEach((c) => list.append(caseRow(c)));
    panel.update({ body: list });
  } catch (error) {
    panel.update({ body: errorBox(error.message) });
  }
}
