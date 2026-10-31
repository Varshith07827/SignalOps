// Model & data: which feedback is loaded (upload another file), the official evaluate.py score and accuracy.
import { api } from "../api.js";
import { ctx, update } from "../state.js";
import { button, card, el, errorBox, skeleton, toast, weekText } from "../ui.js";

function scoreGrid(cells) {
  const grid = el("dl", null, "score-grid");
  for (const [label, value] of cells) {
    const cell = el("div");
    cell.append(el("dt", label), el("dd", value));
    grid.append(cell);
  }
  return grid;
}

function dataCard() {
  const status = ctx.status;
  const input = el("input", null, "visually-hidden", { type: "file", accept: ".csv", id: "upload-file" });
  const pick = el("label", "Choose a CSV", "btn secondary", { for: "upload-file" });
  const upload = button("Upload and analyse", { kind: "primary", iconName: "upload" });
  upload.disabled = true;
  const reset = button("Back to the R5 dataset", { kind: "ghost" });
  reset.hidden = !status.uploaded;
  input.addEventListener("change", () => {
    pick.textContent = input.files[0]?.name || "Choose a CSV";
    upload.disabled = !input.files[0];
  });
  const switched = (next, message) => {
    update({ status: next, week: next.weeks[next.weeks.length - 1], region: next.regions[0] });
    toast(message);
  };
  upload.addEventListener("click", async () => {
    const form = new FormData();
    form.append("file", input.files[0]);
    upload.disabled = true;
    upload.textContent = "Analysing…";
    try {
      switched(await api("/api/upload", { method: "POST", form }), "Uploaded file analysed");
    } catch (error) {
      toast(error.message, "error");
      upload.disabled = false;
      upload.textContent = "Upload and analyse";
    }
  });
  reset.addEventListener("click", async () => {
    try {
      switched(await api("/api/dataset", { method: "POST" }), "Showing the R5 dataset");
    } catch (error) {
      toast(error.message, "error");
    }
  });
  const { section, body } = card("Data", { subtitle: "Upload a CSV with the same columns as feedback.csv, e.g. a newer week." });
  body.append(
    scoreGrid([
      ["Showing", status.dataset],
      ["Messages", status.rows.toLocaleString()],
      ["Weeks", `${weekText(status.weeks[0])} to ${weekText(status.weeks[status.weeks.length - 1])}`],
    ]),
  );
  const row = el("div", null, "form-actions start");
  row.append(input, pick, upload, reset);
  body.append(row);
  return section;
}

function renderScore(slot, link, result) {
  const s = result.summary;
  const head = el("div", null, "primary-score");
  head.append(el("span", s.primary.toFixed(4), "primary-value"), el("span", `Primary score · ${result.finished_at} · ${result.seconds} s`, "muted"));
  const table = el("table", null, "data-table compact");
  const headRow = el("tr");
  ["Incident", "Problem", "Simple counter", "We flagged", "Weeks earlier"].forEach((h) => headRow.append(el("th", h)));
  const thead = el("thead");
  thead.append(headRow);
  const tbody = el("tbody");
  for (const i of s.incidents) {
    const tr = el("tr");
    const lead = i.lead_weeks > 0 ? `+${i.lead_weeks}` : String(i.lead_weeks);
    tr.append(
      el("td", i.incident),
      el("td", i.problem || i.issue_type_id),
      el("td", weekText(i.naive)),
      el("td", i.ours === "Not flagged" ? i.ours : weekText(i.ours)),
      el("td", lead, i.lead_weeks > 0 ? "good" : i.lead_weeks < 0 ? "bad" : ""),
    );
    tbody.append(tr);
  }
  table.append(thead, tbody);
  const wrap = el("div", null, "table-wrap");
  wrap.append(table);
  const statement = el(
    "p",
    `Of ${s.marked_actionable.toLocaleString()} messages marked as needing action, ${(s.actionable_correct * 100).toFixed(1)}% truly did. ` +
      `Of ${s.marked_urgent.toLocaleString()} marked urgent, ${(s.urgent_correct * 100).toFixed(1)}% truly needed action.`,
    "statement",
  );
  const flags = el(
    "p",
    `${s.flags_scored} early-warning flags in the scored weeks (${Number(s.flags_per_week).toFixed(2)} a week, limit 3): ${s.flags_valid} valid, ${s.flags_rejected} rejected. ` +
      "The labelled weeks were also used for training, so classification is higher here than on new data.",
    "muted small",
  );
  const raw = el("details", null, "raw");
  raw.append(el("summary", "Full evaluate.py output"), el("pre", result.output));
  slot.replaceChildren(
    head,
    scoreGrid([
      ["Classification", s.classification.toFixed(3)],
      ["Early-warning lead", s.lead_score === null ? "–" : s.lead_score.toFixed(3)],
      ["Problem type F1", s.issue_type_f1.toFixed(3)],
      ["Severity F1", s.severity_f1.toFixed(3)],
      ["Needs action F1", s.actionable_f1.toFixed(3)],
    ]),
    wrap,
    statement,
    flags,
    raw,
  );
  link.hidden = false;
}

function scoreCard() {
  const link = el("a", "Download report", "btn secondary", { href: "/api/report", download: "" });
  link.hidden = true;
  const run = button("Run evaluate.py", { kind: "primary" });
  const { section, body } = card("Official score", {
    subtitle: "The organisers' evaluate.py on the files in submission/, against the labelled weeks.",
    actions: [link, run],
  });
  const slot = el("div");
  slot.append(el("p", "Takes a few seconds.", "muted"));
  body.append(slot);
  run.addEventListener("click", async () => {
    run.disabled = true;
    slot.replaceChildren(skeleton(4));
    try {
      renderScore(slot, link, await api("/api/evaluate", { method: "POST" }));
    } catch (error) {
      slot.replaceChildren(errorBox(error.message));
    } finally {
      run.disabled = false;
    }
  });
  api("/api/evaluate")
    .then((last) => last && renderScore(slot, link, last))
    .catch(() => {});
  return section;
}

function accuracyCard() {
  const check = button("Check accuracy", { kind: "secondary" });
  const { section, body } = card("How accurate is it", {
    subtitle: "5-fold cross-validation: tested on labelled messages the model has not seen.",
    actions: [check],
  });
  const slot = el("div");
  slot.append(el("p", "Takes about 15 seconds.", "muted"));
  body.append(slot);
  check.addEventListener("click", async () => {
    check.disabled = true;
    slot.replaceChildren(skeleton(3));
    try {
      const a = await api("/api/accuracy");
      const pct = (v) => `${Math.round(v * 100)}%`;
      slot.replaceChildren(
        scoreGrid([
          ["Overall (0 to 1)", a.classification_score.toFixed(3)],
          ["Problem type", pct(a.issue_type_macro_f1)],
          ["Severity", pct(a.severity_weighted_f1)],
          ["Needs action", pct(a.actionable_f1)],
        ]),
        el(
          "p",
          `Of every 100 messages marked as needing action, ${Math.round(a.precision_actionable * 100)} really do. ` +
            `Of every 100 marked urgent, ${Math.round(a.precision_escalated_high_critical * 100)} really need action.`,
          "statement",
        ),
      );
    } catch (error) {
      slot.replaceChildren(errorBox(error.message));
    } finally {
      check.disabled = false;
    }
  });
  return section;
}

export async function render(root) {
  const page = el("div", null, "page model-page");
  page.append(dataCard(), scoreCard(), accuracyCard());
  root.append(page);
  return null;
}
