"use strict";

// Store map. Uses el(), api(), SEVERITY_NAME and regionText() from app.js.
// Zoomed out, stores group by region. Zoomed in, stores closer than CLUSTER_PX on screen group together,
// and they split up as you zoom further in.
const REGION_ZOOM = 5;
const CLUSTER_PX = 56;
const INDIA = [[9.0, 71.5], [31.0, 92.5]];
const SEVERITY_ORDER = ["critical", "high", "medium", "low"];
const PROBLEMS_SHOWN = 5;

let storeMap = null;
let storeLayer = null;
let storePins = [];
let pickedStore = null;

function worstOf(pins) {
  const levels = pins.map((p) => p.worst).filter(Boolean);
  return SEVERITY_ORDER.find((s) => levels.includes(s)) || "none";
}

function setupMap() {
  if (storeMap) return true;
  if (!window.L) {
    $("map").replaceChildren(el("p", "The map needs an internet connection to load.", "hint map-offline"));
    return false;
  }
  storeMap = L.map("map", { minZoom: 4, maxZoom: 14, zoomSnap: 0.5, scrollWheelZoom: true });
  // Esri's grey basemap keeps the severity colours readable. Base and city labels are separate layers.
  const shade = window.matchMedia("(prefers-color-scheme: dark)").matches ? "Dark" : "Light";
  const tiles = (layer) => `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/${layer}/MapServer/tile/{z}/{y}/{x}`;
  L.tileLayer(tiles(`World_${shade}_Gray_Base`), { attribution: "Tiles &copy; Esri", maxZoom: 16 }).addTo(storeMap);
  L.tileLayer(tiles(`World_${shade}_Gray_Reference`), { maxZoom: 16 }).addTo(storeMap);
  storeLayer = L.layerGroup().addTo(storeMap);
  storeMap.fitBounds(INDIA);
  storeMap.on("zoomend", drawPins);
  return true;
}

// Greedy grouping: the busiest store starts a group and nearby stores join it.
function groupPins() {
  if (storeMap.getZoom() <= REGION_ZOOM) {
    const byRegion = new Map();
    storePins.forEach((p) => {
      if (!byRegion.has(p.region)) byRegion.set(p.region, []);
      byRegion.get(p.region).push(p);
    });
    return [...byRegion.entries()].map(([region, pins]) => ({ label: regionText(region), pins }));
  }
  const groups = [];
  [...storePins].sort((a, b) => b.cases - a.cases).forEach((pin) => {
    const point = storeMap.latLngToLayerPoint([pin.lat, pin.lon]);
    const near = groups.find((g) => g.point.distanceTo(point) < CLUSTER_PX);
    if (near) near.pins.push(pin);
    else groups.push({ point, pins: [pin] });
  });
  return groups.map((g) => ({ label: `${g.pins.length} stores`, pins: g.pins }));
}

function centreOf(pins) {
  const lat = pins.reduce((sum, p) => sum + p.lat, 0) / pins.length;
  const lon = pins.reduce((sum, p) => sum + p.lon, 0) / pins.length;
  return [lat, lon];
}

function groupMarker(group) {
  const cases = group.pins.reduce((sum, p) => sum + p.cases, 0);
  const warned = group.pins.some((p) => p.warnings.length);
  const size = Math.round(Math.min(78, 40 + Math.sqrt(cases) * 2));
  const node = el("div", null, `cluster sev-${worstOf(group.pins)}${warned ? " warned" : ""}`);
  node.style.width = node.style.height = `${size}px`;
  node.append(el("b", cases.toLocaleString()), el("span", group.label));
  const icon = L.divIcon({ html: node, className: "pin-icon", iconSize: [size, size] });
  const marker = L.marker(centreOf(group.pins), { icon, keyboard: true, title: `${group.label}: ${cases} cases` });
  marker.on("click", () => {
    const bounds = L.latLngBounds(group.pins.map((p) => [p.lat, p.lon]));
    storeMap.fitBounds(bounds.pad(0.4), { maxZoom: storeMap.getZoom() + 3 });
  });
  return marker;
}

function storeMarker(pin) {
  const node = el("div", null, `pin sev-${pin.worst || "none"}${pin.warnings.length ? " warned" : ""}`);
  if (pin.store_id === pickedStore) node.classList.add("picked");
  node.append(el("b", String(pin.cases)));
  const icon = L.divIcon({ html: node, className: "pin-icon", iconSize: [34, 34] });
  const marker = L.marker([pin.lat, pin.lon], { icon, keyboard: true, title: pin.name });
  const tip = el("div");
  tip.append(el("b", pin.name), el("div", pin.problems.length ? pin.problems[0].problem : "No problems this week"));
  marker.bindTooltip(tip, { direction: "top", offset: [0, -16] });
  marker.on("click", () => {
    pickedStore = pin.store_id;
    showStore(pin);
    drawPins();
  });
  return marker;
}

function drawPins() {
  storeLayer.clearLayers();
  groupPins().forEach((group) => {
    storeLayer.addLayer(group.pins.length === 1 ? storeMarker(group.pins[0]) : groupMarker(group));
  });
}

function linkButton(text, onClick) {
  const button = el("button", text, "link-btn");
  button.type = "button";
  button.addEventListener("click", onClick);
  return button;
}

// The store's problems this week, each opening its cases. Only the first few show until "Show more".
function problemList(pin) {
  if (!pin.problems.length) return [el("p", "Nothing to act on this week.", "hint")];
  const list = el("ul", null, "store-problems");
  pin.problems.forEach((p, index) => {
    const item = el("li");
    item.hidden = index >= PROBLEMS_SHOWN;
    const row = el("button", null, "problem-row");
    row.type = "button";
    row.title = `${SEVERITY_NAME[p.severity]}: ${p.cases} case${p.cases === 1 ? "" : "s"}. Click to see them.`;
    row.append(el("i", null, `sw ${p.severity}`), el("span", p.problem), el("b", String(p.cases)));
    row.addEventListener("click", () => openCases(p.problem, pin.name, { store: pin.store_id, issue: p.issue_type_id }));
    item.append(row);
    list.append(item);
  });
  const links = el("div", null, "store-links");
  const hidden = pin.problems.length - PROBLEMS_SHOWN;
  if (hidden > 0) {
    const more = linkButton(`Show ${hidden} more problems`, () => {
      list.querySelectorAll("li[hidden]").forEach((li) => {
        li.hidden = false;
      });
      more.remove();
    });
    links.append(more);
  }
  links.append(
    linkButton(`See all ${pin.cases} cases`, () => openCases(pin.name, `${pin.city} · all problems`, { store: pin.store_id })),
  );
  return [list, links];
}

function lastSolved(solved) {
  if (!solved) return el("p", "No problem has gone quiet yet.", "hint");
  const since = new Date(`${solved.last_report}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  const box = el("p", null, "store-solved");
  box.append(el("strong", solved.problem), el("span", `${solved.reports} complaints up to ${since}, none since.`, "meta"));
  return box;
}

function showStore(pin) {
  const head = el("div", null, "store-head");
  head.append(el("h3", pin.name), el("p", `${pin.city} · ${pin.region} region · ${pin.format}`, "meta"));

  const numbers = el("dl", null, "store-numbers");
  [["Cases this week", pin.cases, ""], ["Urgent", pin.urgent, pin.urgent ? "hot" : ""]].forEach(([label, value, hot]) => {
    const cell = el("div");
    cell.append(el("dt", label), el("dd", String(value), hot));
    numbers.append(cell);
  });

  const warnings = pin.warnings.map((w) => {
    const line = el("p", null, "store-warning");
    line.append(el("span", "Early warning", "pill warning"), ` ${w}`);
    return line;
  });

  $("store-card").replaceChildren(
    head,
    numbers,
    ...warnings,
    el("h4", "Problems this week"),
    ...problemList(pin),
    el("h4", "Last solved"),
    lastSolved(pin.last_solved),
  );
}

async function renderMap(week) {
  if (!setupMap()) return;
  storePins = await api(`/api/map?week=${encodeURIComponent(week)}`);
  drawPins();
  const picked = storePins.find((p) => p.store_id === pickedStore);
  if (picked) showStore(picked);
}

function focusRegion(region) {
  if (!storeMap) return;
  const pins = storePins.filter((p) => p.region === region);
  if (pins.length) storeMap.fitBounds(L.latLngBounds(pins.map((p) => [p.lat, p.lon])).pad(0.2));
  else storeMap.fitBounds(INDIA);
}
