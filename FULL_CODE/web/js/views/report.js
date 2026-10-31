// Report a problem: a store manager writes it like a shift note; the model labels and routes it to head office.
import { api } from "../api.js";
import { casesChanged, ctx } from "../state.js";
import { button, card, el, errorBox } from "../ui.js";
import { openCase } from "./case-panel.js";
import { resultCard } from "./review.js";

const EXAMPLES = [
  "Dairy chiller not cooling since 7am, curd and paneer getting warm",
  "Billing counter 2 scanner down, queue up to the entrance in the evening",
  "Customer found expired bread on the bakery shelf, removed the batch",
];

export async function render(root, _params, { go }) {
  const page = el("div", null, "page report-page");
  const text = el("textarea", null, null, {
    rows: "6",
    maxlength: "2000",
    placeholder: "What happened, where in the store, since when. Any language is fine.",
    "aria-label": "Problem",
  });
  const chips = el("div", null, "chips");
  for (const example of EXAMPLES) {
    const chip = el("button", example, "chip", { type: "button" });
    chip.addEventListener("click", () => {
      text.value = example;
      text.focus();
    });
    chips.append(chip);
  }
  const submit = button("Send to head office", { kind: "primary", type: "submit", iconName: "report" });
  const form = el("form", null, "report-form");
  form.append(el("p", "Examples", "field-label"), chips, text, submit);
  const output = el("div", null, "result-slot", { "aria-live": "polite" });
  const { section, body } = card(`Report a problem at ${ctx.user.store.name}`, {
    subtitle: "Write it as you would in a shift note. It is labelled, given a deadline and sent to the right team.",
  });
  body.append(form, output);
  page.append(section);
  root.append(page);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = text.value.trim();
    if (message.length < 5) {
      output.replaceChildren(errorBox("Describe the problem in a few words."));
      return;
    }
    submit.disabled = true;
    try {
      const answer = await api("/api/reports", { method: "POST", body: { text: message } });
      const result = resultCard(answer.result);
      if (answer.raised) {
        const done = el("div", null, "success");
        done.append(el("strong", `Sent as case ${answer.case.ref}`), el("span", "Head office has it in their inbox."));
        const actions = el("div", null, "form-actions start");
        actions.append(
          button("Open case", { kind: "secondary", onClick: () => openCase(answer.case.ref) }),
          button("Back to my store", { kind: "ghost", onClick: () => go("store") }),
        );
        output.replaceChildren(done, result, actions);
        text.value = "";
        casesChanged();
      } else {
        output.replaceChildren(
          errorBox("Not sent: this doesn't read as a problem someone can act on. Add what, where and since when."),
          result,
        );
      }
    } catch (error) {
      output.replaceChildren(errorBox(error.message));
    } finally {
      submit.disabled = false;
    }
  });
  return null;
}
