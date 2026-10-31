// Building blocks shared by every screen. Data text is always set with textContent, never innerHTML.
import { icon } from "./icons.js";

export const SEVERITY_NAME = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };
export const SEVERITIES = ["critical", "high", "medium", "low"];

export function el(tag, text, className, attributes) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  if (attributes) for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

export function button(label, { kind = "secondary", iconName, onClick, type = "button", small } = {}) {
  const node = el("button", null, `btn ${kind}${small ? " small" : ""}`, { type });
  if (iconName) node.append(icon(iconName, 16));
  if (label) node.append(el("span", label));
  if (onClick) node.addEventListener("click", onClick);
  return node;
}

export function pill(text, kind) {
  return el("span", text, `pill ${kind || ""}`);
}

export function severityPill(severity) {
  return pill(SEVERITY_NAME[severity] || severity, severity);
}

export function statusPill(status, text) {
  return pill(text, `status-${status}`);
}

// Dates
const asDate = (value) => new Date(value.length <= 10 ? `${value}T00:00:00` : value);
export const dayText = (value) => asDate(value).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
export const weekText = (value) =>
  asDate(value).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
export const timeText = (value) =>
  asDate(value).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export function relativeText(value) {
  const minutes = Math.round((Date.now() - asDate(value).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} h ago`;
  return dayText(value);
}

export const plural = (n, word) => `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`;
export const locality = (storeName) => storeName.split(" ").slice(2).join(" ") || storeName;
export const regionText = (region) => (region.startsWith("National") ? "Online & app" : `${region} region`);

export function emptyState(title, text, iconName = "check") {
  const box = el("div", null, "empty-state");
  const badge = el("div", null, "empty-icon");
  badge.append(icon(iconName, 22));
  box.append(badge, el("p", title, "empty-title"));
  if (text) box.append(el("p", text, "empty-text"));
  return box;
}

export function skeleton(lines = 3) {
  const box = el("div", null, "skeleton-group", { "aria-hidden": "true" });
  for (let i = 0; i < lines; i += 1) box.append(el("div", null, "skeleton"));
  return box;
}

export function errorBox(message) {
  const box = el("div", null, "error-box", { role: "alert" });
  box.append(icon("alert", 18), el("span", message));
  return box;
}

export function card(title, { actions, className, subtitle } = {}) {
  const section = el("section", null, `card ${className || ""}`);
  const head = el("header", null, "card-head");
  const titles = el("div");
  titles.append(el("h2", title));
  if (subtitle) titles.append(el("p", subtitle, "card-sub"));
  head.append(titles);
  if (actions) {
    const box = el("div", null, "card-actions");
    box.append(...actions);
    head.append(box);
  }
  const body = el("div", null, "card-body");
  section.append(head, body);
  return { section, body, head };
}

// Toasts: short confirmations at the bottom of the screen.
export function toast(message, kind = "ok") {
  let stack = document.querySelector(".toasts");
  if (!stack) {
    stack = el("div", null, "toasts", { role: "status", "aria-live": "polite" });
    document.body.append(stack);
  }
  const item = el("div", null, `toast ${kind}`);
  item.append(icon(kind === "error" ? "alert" : "check", 18), el("span", message));
  stack.append(item);
  setTimeout(() => item.classList.add("leaving"), 3600);
  setTimeout(() => item.remove(), 4000);
}

// Side panel. Panels stack: opening one from another shows a Back button instead of losing your place.
const drawer = { stack: [], root: null, lastFocus: null };

function drawerRoot() {
  if (drawer.root) return drawer.root;
  const backdrop = el("div", null, "drawer-backdrop");
  const panel = el("aside", null, "drawer", { role: "dialog", "aria-modal": "true", "aria-labelledby": "drawer-title" });
  backdrop.addEventListener("click", closeDrawer);
  panel.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeDrawer();
    if (event.key === "Tab") trapFocus(event, panel);
  });
  document.body.append(backdrop, panel);
  drawer.root = { backdrop, panel };
  return drawer.root;
}

function trapFocus(event, panel) {
  const items = [...panel.querySelectorAll("button, a[href], input, textarea, select, [tabindex='0']")].filter(
    (node) => !node.disabled && node.offsetParent !== null,
  );
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    last.focus();
    event.preventDefault();
  } else if (!event.shiftKey && document.activeElement === last) {
    first.focus();
    event.preventDefault();
  }
}

function showTop() {
  const { panel } = drawerRoot();
  const top = drawer.stack[drawer.stack.length - 1];
  const head = el("header", null, "drawer-head");
  if (drawer.stack.length > 1) {
    const back = button("Back", { kind: "ghost", iconName: "back", small: true, onClick: popDrawer });
    head.append(back);
  }
  const titles = el("div", null, "drawer-titles");
  if (top.eyebrow) titles.append(el("p", top.eyebrow, "eyebrow"));
  titles.append(el("h2", top.title, null, { id: "drawer-title" }));
  const close = button(null, { kind: "ghost icon-only", iconName: "x", onClick: closeDrawer });
  close.setAttribute("aria-label", "Close");
  head.append(titles, close);
  const body = el("div", null, "drawer-body");
  body.append(top.body);
  panel.replaceChildren(head, body);
  if (top.footer) {
    const footer = el("footer", null, "drawer-foot");
    footer.append(top.footer);
    panel.append(footer);
  }
  close.focus({ preventScroll: true });
}

export function openDrawer({ title, eyebrow, body, footer }) {
  const { backdrop, panel } = drawerRoot();
  if (!drawer.stack.length) drawer.lastFocus = document.activeElement;
  drawer.stack.push({ title, eyebrow, body, footer });
  showTop();
  backdrop.classList.add("open");
  panel.classList.add("open");
  document.body.classList.add("drawer-open");
  const entry = drawer.stack[drawer.stack.length - 1];
  return {
    update(next) {
      Object.assign(entry, next);
      if (drawer.stack[drawer.stack.length - 1] === entry) showTop();
    },
  };
}

function popDrawer() {
  drawer.stack.pop();
  if (drawer.stack.length) showTop();
  else closeDrawer();
}

export function closeDrawer() {
  if (!drawer.root) return;
  drawer.stack = [];
  drawer.root.backdrop.classList.remove("open");
  drawer.root.panel.classList.remove("open");
  document.body.classList.remove("drawer-open");
  drawer.lastFocus?.focus?.({ preventScroll: true });
}

// Dropdown that matches the brand. Works with the keyboard like a native select, and can be searchable.
let openSelect = null;
document.addEventListener("click", (event) => {
  if (openSelect && !openSelect.root.contains(event.target)) openSelect.close();
});

export function dropdown({ options, value, onChange, label, searchable = false, className = "" }) {
  const root = el("div", null, `select ${className}`);
  const trigger = el("button", null, "select-trigger", { type: "button", "aria-haspopup": "listbox", "aria-expanded": "false" });
  if (label) trigger.setAttribute("aria-label", label);
  const current = el("span", null, "select-value");
  trigger.append(current, icon("chevron", 16));
  const popover = el("div", null, "select-popover");
  const search = searchable ? el("input", null, "select-search", { type: "search", placeholder: "Search", "aria-label": "Search" }) : null;
  const list = el("ul", null, "select-list", { role: "listbox", tabindex: "-1" });
  if (search) popover.append(search);
  popover.append(list);
  root.append(trigger, popover);

  let items = options;
  let selected = value;
  let active = 0;
  let typed = "";
  let typedAt = 0;

  const visible = () => {
    const needle = search?.value.trim().toLowerCase() || "";
    return items.filter((o) => !needle || o.label.toLowerCase().includes(needle) || (o.hint || "").toLowerCase().includes(needle));
  };

  function paint() {
    const shown = visible();
    active = Math.min(active, Math.max(shown.length - 1, 0));
    let group = null;
    const nodes = [];
    shown.forEach((option, index) => {
      if (option.group && option.group !== group) {
        group = option.group;
        nodes.push(el("li", group, "select-group", { role: "presentation" }));
      }
      const item = el("li", null, `select-option${index === active ? " active" : ""}`, {
        role: "option",
        "aria-selected": String(option.value === selected),
      });
      item.append(el("span", option.label));
      if (option.hint) item.append(el("span", option.hint, "select-hint"));
      if (option.value === selected) item.append(icon("check", 16));
      item.addEventListener("mousedown", (event) => event.preventDefault());
      item.addEventListener("click", () => choose(option));
      nodes.push(item);
    });
    if (!shown.length) nodes.push(el("li", "No matches", "select-none"));
    list.replaceChildren(...nodes);
    list.querySelector(".active")?.scrollIntoView({ block: "nearest" });
  }

  function setLabel() {
    const option = items.find((o) => o.value === selected);
    current.textContent = option ? option.label : "Choose";
  }

  function open() {
    if (openSelect && openSelect !== api) openSelect.close();
    openSelect = api;
    root.classList.add("open");
    trigger.setAttribute("aria-expanded", "true");
    if (search) search.value = "";
    active = Math.max(visible().findIndex((o) => o.value === selected), 0);
    paint();
    (search || list).focus({ preventScroll: true });
  }

  function close() {
    root.classList.remove("open");
    trigger.setAttribute("aria-expanded", "false");
    if (openSelect === api) openSelect = null;
  }

  function choose(option) {
    const changed = option.value !== selected;
    selected = option.value;
    setLabel();
    close();
    trigger.focus({ preventScroll: true });
    if (changed && onChange) onChange(option.value);
  }

  function onKey(event) {
    const shown = visible();
    if (event.key === "ArrowDown") active = Math.min(active + 1, shown.length - 1);
    else if (event.key === "ArrowUp") active = Math.max(active - 1, 0);
    else if (event.key === "Home") active = 0;
    else if (event.key === "End") active = shown.length - 1;
    else if (event.key === "Enter" || (event.key === " " && !search)) {
      if (shown[active]) choose(shown[active]);
    } else if (event.key === "Escape" || event.key === "Tab") {
      close();
      if (event.key === "Escape") trigger.focus();
      return;
    } else if (!search && event.key.length === 1) {
      typed = Date.now() - typedAt > 700 ? event.key : typed + event.key;
      typedAt = Date.now();
      const hit = shown.findIndex((o) => o.label.toLowerCase().startsWith(typed.toLowerCase()));
      if (hit >= 0) active = hit;
    } else return;
    event.preventDefault();
    paint();
  }

  trigger.addEventListener("click", () => (root.classList.contains("open") ? close() : open()));
  trigger.addEventListener("keydown", (event) => {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
      event.preventDefault();
      open();
    }
  });
  list.addEventListener("keydown", onKey);
  search?.addEventListener("keydown", onKey);
  search?.addEventListener("input", () => {
    active = 0;
    paint();
  });

  const api = {
    root,
    close,
    get value() {
      return selected;
    },
    set(nextValue) {
      selected = nextValue;
      setLabel();
    },
    setOptions(nextOptions, nextValue = selected) {
      items = nextOptions;
      selected = items.some((o) => o.value === nextValue) ? nextValue : items[0]?.value;
      setLabel();
    },
  };
  setLabel();
  return api;
}

// Segmented control: a small set of mutually exclusive views, e.g. Bubbles / Map.
export function segmented(options, value, onChange, label) {
  const root = el("div", null, "segmented", { role: "radiogroup", "aria-label": label });
  const buttons = options.map((option) => {
    const node = el("button", null, "segment", { type: "button", role: "radio" });
    if (option.icon) node.append(icon(option.icon, 16));
    node.append(el("span", option.label));
    node.addEventListener("click", () => select(option.value, true));
    root.append(node);
    return [option.value, node];
  });
  function select(next, notify) {
    buttons.forEach(([v, node]) => node.setAttribute("aria-checked", String(v === next)));
    if (notify && onChange) onChange(next);
  }
  select(value, false);
  return { root, select };
}

export function field(labelText, control, hint) {
  const wrap = el("label", null, "field");
  wrap.append(el("span", labelText, "field-label"), control);
  if (hint) wrap.append(el("span", hint, "field-hint"));
  return wrap;
}
