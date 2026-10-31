// Check a review: label one new message (problem, severity, needs action, team, deadline) without saving it.
import { api } from "../api.js";
import { icon } from "../icons.js";
import { button, card, dropdown, el, errorBox, field, pill, severityPill } from "../ui.js";

const CHANNELS = [
  { value: "online_review", label: "Online review" },
  { value: "in_app", label: "App comment" },
  { value: "staff_shift_note", label: "Staff shift note" },
  { value: "call_centre_ticket", label: "Call-centre call" },
];
const RATINGS = [{ value: "", label: "No rating" }, ...[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: `${n} star${n > 1 ? "s" : ""}` }))];
const EXAMPLES = [
  "freezer not cold since morning, ice cream melting",
  "Bill mein double scan hua, refund kab milega?",
  "Staff romba helpful, fresh veggies today, thank you!",
];

export function resultCard(r) {
  const box = el("div", null, "result");
  const head = el("div", null, "result-head");
  head.append(el("h3", r.problem));
  const tags = el("div", null, "tag-row");
  tags.append(severityPill(r.severity), pill(r.needs_action ? "Needs action" : "No action", r.needs_action ? "yes" : "no"));
  head.append(tags);
  box.append(head);
  if (r.needs_action) {
    const todo = el("p", null, "todo");
    todo.append(icon("team", 18), el("span", `${r.action} · ${r.team} · deadline ${r.deadline}`));
    box.append(todo);
  } else {
    box.append(el("p", r.reason, "muted"));
  }
  const clarity = r.confidence >= 0.75 ? "clear" : r.confidence >= 0.55 ? "fairly clear" : "unclear, worth a human look";
  box.append(el("p", `${r.store} · ${r.language} · the call is ${clarity}`, "muted small"));
  return box;
}

export async function render(root) {
  const page = el("div", null, "page review-page");
  const store = dropdown({ options: [{ value: "", label: "No store (online or app)" }], value: "", label: "Store", searchable: true });
  const channel = dropdown({ options: CHANNELS, value: "online_review", label: "Channel" });
  const rating = dropdown({ options: RATINGS, value: "", label: "Rating" });
  const text = el("textarea", null, null, { rows: "4", maxlength: "2000", placeholder: "Paste or type a customer message, in any of the four languages" });
  const examples = el("div", null, "chips");
  for (const example of EXAMPLES) {
    const chip = el("button", example, "chip", { type: "button" });
    chip.addEventListener("click", () => {
      text.value = example;
      text.focus();
    });
    examples.append(chip);
  }
  const submit = button("Check message", { kind: "primary", type: "submit", iconName: "review" });
  const form = el("form", null, "form-grid");
  form.append(field("Store", store.root), field("Channel", channel.root), field("Rating", rating.root));
  const wide = field("Message", text);
  wide.classList.add("wide");
  form.append(wide, examples, submit);
  const output = el("div", null, "result-slot", { "aria-live": "polite" });
  const history = el("ul", null, "history");

  const { section, body } = card("Check a review", { subtitle: "See how the model reads a new message. Nothing is saved." });
  body.append(form, output);
  const past = card("Checked this session");
  past.body.append(history);
  page.append(section, past.section);
  root.append(page);

  api("/api/stores")
    .then((stores) =>
      store.setOptions(
        [{ value: "", label: "No store (online or app)" }, ...stores.map((s) => ({ value: s.store_id, label: s.name, hint: s.city, group: `${s.region} region` }))],
        "",
      ),
    )
    .catch(() => {});

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = text.value.trim();
    if (message.length < 3) {
      output.replaceChildren(errorBox("Type at least a few words."));
      return;
    }
    submit.disabled = true;
    try {
      const result = await api("/api/review", {
        method: "POST",
        body: { text: message, channel: channel.value, store_id: store.value || null, rating: rating.value ? Number(rating.value) : null },
      });
      output.replaceChildren(resultCard(result));
      const item = el("li");
      item.append(el("strong", result.problem), el("span", message.length > 90 ? `${message.slice(0, 87)}…` : message, "muted"));
      history.prepend(item);
    } catch (error) {
      output.replaceChildren(errorBox(error.message));
    } finally {
      submit.disabled = false;
    }
  });
  return null;
}
