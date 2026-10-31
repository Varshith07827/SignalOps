// Starts the app: sign-in, the shell (menu, top bar), page routing and the inbox badge.
import { api, whenSignedOut } from "./api.js";
import { icon } from "./icons.js";
import { ctx, isAdmin, onCasesChanged, onChange, update } from "./state.js";
import { closeDrawer, dropdown, el, regionText, weekText } from "./ui.js";
import * as brief from "./views/brief.js";
import * as cases from "./views/cases.js";
import * as inbox from "./views/inbox.js";
import * as model from "./views/model.js";
import * as overview from "./views/overview.js";
import * as report from "./views/report.js";
import * as review from "./views/review.js";
import * as storeHome from "./views/store-home.js";

const $ = (id) => document.getElementById(id);
const INBOX_POLL_MS = 30000;

// Pages per role. "week" and "region" say which pickers the top bar shows.
const ROUTES = {
  overview: { title: "Overview", icon: "overview", role: "admin", view: overview, week: true },
  brief: { title: "Regional brief", icon: "brief", role: "admin", view: brief, week: true, region: true },
  store: { title: "My store", icon: "store", role: "store", view: storeHome, week: true },
  report: { title: "Report a problem", icon: "report", role: "store", view: report },
  cases: { title: "Cases", icon: "cases", view: cases, week: true },
  inbox: { title: "Inbox", icon: "inbox", view: inbox },
  review: { title: "Check a review", icon: "review", role: "admin", view: review },
  model: { title: "Model & data", icon: "model", role: "admin", view: model },
};

let current = { name: null, cleanup: null };
let pickers = {};
let inboxTimer = null;

function allowed(name) {
  const route = ROUTES[name];
  return route && (!route.role || route.role === ctx.user.role);
}

function home() {
  return isAdmin() ? "overview" : "store";
}

function parseHash() {
  const [path, search] = location.hash.replace(/^#\/?/, "").split("?");
  return { name: path || home(), params: Object.fromEntries(new URLSearchParams(search || "")) };
}

function go(name, params = {}) {
  const search = new URLSearchParams(params).toString();
  location.hash = `#/${name}${search ? `?${search}` : ""}`;
}

function buildNav() {
  const nav = $("nav");
  nav.replaceChildren(
    ...Object.entries(ROUTES)
      .filter(([name]) => allowed(name))
      .map(([name, route]) => {
        const link = el("a", null, "nav-link", { href: `#/${name}`, "data-route": name });
        link.append(icon(route.icon, 20), el("span", route.title));
        if (name === "inbox") link.append(el("span", "", "nav-badge", { id: "nav-badge", hidden: "" }));
        return link;
      }),
  );
  const user = ctx.user;
  $("user-name").textContent = user.name;
  $("user-role").textContent = user.store ? `${user.store.name}` : "All 60 stores";
  $("user-avatar").textContent = user.name
    .split(" ")
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function buildPickers() {
  const weeks = [...ctx.status.weeks].reverse();
  const week = dropdown({
    options: weeks.map((w) => ({ value: w, label: `Week of ${weekText(w)}` })),
    value: ctx.week,
    label: "Week",
    className: "top-select",
    onChange: (value) => update({ week: value }),
  });
  const region = dropdown({
    options: ctx.status.regions.map((r) => ({ value: r, label: regionText(r) })),
    value: ctx.region,
    label: "Region",
    className: "top-select",
    onChange: (value) => update({ region: value }),
  });
  pickers = { week, region };
  $("top-controls").replaceChildren(region.root, week.root);
}

async function renderRoute() {
  const { name, params } = parseHash();
  if (!allowed(name)) {
    go(home());
    return;
  }
  const route = ROUTES[name];
  closeDrawer();
  current.cleanup?.();
  current = { name, cleanup: null };
  document.querySelectorAll(".nav-link").forEach((link) => {
    link.toggleAttribute("aria-current", link.dataset.route === name);
  });
  $("page-title").textContent = route.title;
  pickers.week.root.hidden = !route.week;
  pickers.region.root.hidden = !route.region;
  document.body.classList.remove("nav-open");
  const view = $("view");
  view.replaceChildren();
  view.scrollTop = 0;
  refreshSubtitle();
  current.cleanup = (await route.view.render(view, params, { go, subtitle: refreshSubtitle })) || null;
}

function refreshSubtitle(text) {
  const route = ROUTES[current.name];
  if (!route) return;
  const parts = [];
  if (text) parts.push(text);
  else {
    if (route.week) parts.push(`Week of ${weekText(ctx.week)}`);
    if (route.region) parts.push(regionText(ctx.region));
    if (ctx.status.uploaded) parts.push(ctx.status.dataset);
  }
  $("page-sub").textContent = parts.join(" · ");
}

async function refreshInbox() {
  try {
    const data = await api("/api/inbox");
    update({ unread: data.unread });
  } catch {
    // The badge is a convenience; a failed refresh is retried on the next poll.
  }
}

function paintBadge() {
  const badge = $("nav-badge");
  const bell = $("bell-count");
  const count = ctx.unread;
  for (const node of [badge, bell]) {
    if (!node) continue;
    node.hidden = !count;
    node.textContent = count > 99 ? "99+" : String(count);
  }
  $("bell").setAttribute("aria-label", count ? `Inbox, ${count} unread` : "Inbox");
}

async function waitForData() {
  $("splash-text").textContent = "Loading the R5 dataset and training the model…";
  for (;;) {
    const status = await api("/api/status");
    if (status.status === "ready") return status;
    if (status.status === "error") throw new Error(status.message);
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}

async function signedIn(user) {
  update({ user });
  $("login").hidden = true;
  $("splash").hidden = false;
  try {
    const status = await waitForData();
    const weeks = status.weeks;
    update({ status, week: weeks[weeks.length - 1], region: status.regions[0] });
  } catch (error) {
    $("splash-text").textContent = error.message;
    return;
  }
  buildNav();
  buildPickers();
  $("splash").hidden = true;
  $("app").hidden = false;
  if (!location.hash) location.hash = `#/${home()}`;
  await renderRoute();
  refreshInbox();
  clearInterval(inboxTimer);
  inboxTimer = setInterval(refreshInbox, INBOX_POLL_MS);
}

async function showLogin(message) {
  clearInterval(inboxTimer);
  closeDrawer();
  $("app").hidden = true;
  $("splash").hidden = true;
  $("login").hidden = false;
  $("login-error").hidden = !message;
  $("login-error").textContent = message || "";
  try {
    const setup = await api("/api/setup");
    $("login-setup").hidden = setup.accounts;
  } catch {
    $("login-setup").hidden = true;
  }
  $("username").focus();
}

async function login(event) {
  event.preventDefault();
  const submit = $("login-submit");
  submit.disabled = true;
  $("login-error").hidden = true;
  try {
    const user = await api("/api/login", {
      method: "POST",
      body: { username: $("username").value.trim().toLowerCase(), password: $("password").value },
    });
    $("password").value = "";
    await signedIn(user);
  } catch (error) {
    $("login-error").textContent = error.message;
    $("login-error").hidden = false;
  } finally {
    submit.disabled = false;
  }
}

async function logout() {
  await api("/api/logout", { method: "POST" }).catch(() => {});
  location.hash = "";
  update({ user: null });
  showLogin();
}

function wire() {
  $("login-form").addEventListener("submit", login);
  $("logout").addEventListener("click", logout);
  $("bell").addEventListener("click", () => go("inbox"));
  $("menu-toggle").addEventListener("click", () => document.body.classList.toggle("nav-open"));
  $("nav-scrim").addEventListener("click", () => document.body.classList.remove("nav-open"));
  window.addEventListener("hashchange", () => {
    if (ctx.user && ctx.status) renderRoute();
  });
  whenSignedOut(() => {
    if (ctx.user) {
      update({ user: null });
      showLogin("Your session ended. Please sign in again.");
    }
  });
  onCasesChanged(refreshInbox);
  onChange((patch) => {
    if ("unread" in patch) paintBadge();
    if ("status" in patch && current.name) buildPickers();
    if (("week" in patch || "region" in patch) && current.name) {
      pickers.week?.set(ctx.week);
      pickers.region?.set(ctx.region);
      renderRoute();
    }
  });
}

wire();
api("/api/me")
  .then((user) => (user ? signedIn(user) : showLogin()))
  .catch((error) => showLogin(error.message));
