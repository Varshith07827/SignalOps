// Inbox: new store reports and confirmations (head office), "is it fixed?" requests (stores).
import { api } from "../api.js";
import { icon } from "../icons.js";
import { casesChanged, isAdmin, onCasesChanged, update } from "../state.js";
import { button, card, el, emptyState, errorBox, relativeText, skeleton, statusPill, toast } from "../ui.js";
import { openCase } from "./case-panel.js";

const KIND = {
  new_report: ["report", "New report"],
  confirm_request: ["message", "Please confirm"],
  confirmed: ["check", "Confirmed fixed"],
  not_fixed: ["alert", "Not fixed"],
};

async function markRead(id) {
  const data = await api("/api/inbox/read", { method: "POST", body: id ? { id } : {} });
  update({ unread: data.unread });
}

function messageRow(m, reload) {
  const [iconName, kindText] = KIND[m.kind];
  const row = el("li", null, `inbox-item kind-${m.kind}${m.read ? "" : " unread"}`);
  const badge = el("span", null, "inbox-icon");
  badge.append(icon(iconName, 18));
  const body = el("div", null, "inbox-body");
  const head = el("p", null, "inbox-head");
  head.append(el("strong", kindText), el("span", `${m.ref} · ${relativeText(m.at)}`, "muted"));
  body.append(head, el("p", m.body, "inbox-text"));
  const foot = el("div", null, "inbox-foot");
  foot.append(statusPill(m.status, m.status_text));
  const open = button("Open case", { kind: "ghost", small: true });
  open.addEventListener("click", async () => {
    if (!m.read) await markRead(m.id).catch(() => {});
    openCase(m.ref);
  });
  foot.append(open);
  if (m.kind === "confirm_request" && !m.answered && m.status === "awaiting_confirmation" && !isAdmin()) {
    const yes = button("Yes, it's fixed", { kind: "primary", small: true, iconName: "check" });
    yes.addEventListener("click", async () => {
      yes.disabled = true;
      try {
        await api(`/api/cases/${encodeURIComponent(m.ref)}/confirm`, { method: "POST", body: { fixed: true, comment: "" } });
        toast("Thanks, the case is closed");
        casesChanged();
        reload();
      } catch (error) {
        toast(error.message, "error");
        yes.disabled = false;
      }
    });
    const no = button("No, still a problem", { kind: "secondary", small: true, onClick: () => openCase(m.ref) });
    foot.append(no, yes);
  }
  body.append(foot);
  row.append(badge, body);
  return row;
}

export async function render(root) {
  const page = el("div", null, "page inbox-page");
  const readAll = button("Mark all as read", { kind: "ghost", iconName: "check" });
  const { section, body } = card("Messages", {
    subtitle: isAdmin() ? "New store reports and stores' answers" : "Head office asks here whether a problem is fixed",
    actions: [readAll],
  });
  page.append(section);
  root.append(page);

  async function load() {
    body.replaceChildren(skeleton(5));
    try {
      const data = await api("/api/inbox");
      update({ unread: data.unread });
      readAll.disabled = !data.unread;
      if (!data.messages.length) {
        body.replaceChildren(emptyState("No messages yet", "You'll see updates on cases here.", "inbox"));
        return;
      }
      const list = el("ul", null, "inbox-list");
      data.messages.forEach((m) => list.append(messageRow(m, load)));
      body.replaceChildren(list);
    } catch (error) {
      body.replaceChildren(errorBox(error.message));
    }
  }
  readAll.addEventListener("click", async () => {
    await markRead(null).catch((error) => toast(error.message, "error"));
    load();
  });
  await load();
  return onCasesChanged(load);
}
