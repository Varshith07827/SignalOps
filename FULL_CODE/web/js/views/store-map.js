// The store map. Zoomed out, stores group by region; zooming in splits them into nearby groups, then stores.
import { el, plural, regionText } from "../ui.js";

const REGION_ZOOM = 5;
const CLUSTER_PX = 56;
const INDIA = [[9.0, 71.5], [31.0, 92.5]];
const ORDER = ["critical", "high", "medium", "low"];

function worstOf(pins) {
  const levels = pins.map((p) => p.worst).filter(Boolean);
  return ORDER.find((s) => levels.includes(s)) || "clear";
}

export function storeMap({ onPick }) {
  const root = el("div", null, "map");
  if (!window.L) {
    root.append(el("p", "The map needs an internet connection to load. The bubble view works offline.", "muted map-offline"));
    return { root, update() {}, filter() {}, resize() {} };
  }
  const L = window.L;
  let map = null;
  let layer = null;
  let pins = [];
  let filter = "all";

  function groups() {
    const shown = pins.filter((p) => filter === "all" || (filter === "urgent" ? p.urgent : p.warnings.length));
    if (map.getZoom() <= REGION_ZOOM) {
      const byRegion = new Map();
      shown.forEach((p) => byRegion.set(p.region, [...(byRegion.get(p.region) || []), p]));
      return [...byRegion.entries()].map(([region, list]) => ({ label: regionText(region), pins: list }));
    }
    const found = [];
    [...shown]
      .sort((a, b) => b.cases - a.cases)
      .forEach((pin) => {
        const point = map.latLngToLayerPoint([pin.lat, pin.lon]);
        const near = found.find((g) => g.point.distanceTo(point) < CLUSTER_PX);
        if (near) near.pins.push(pin);
        else found.push({ point, pins: [pin] });
      });
    return found.map((g) => ({ label: plural(g.pins.length, "store"), pins: g.pins }));
  }

  function marker(group) {
    const cases = group.pins.reduce((sum, p) => sum + p.cases, 0);
    const single = group.pins.length === 1 ? group.pins[0] : null;
    const size = single ? 36 : Math.round(Math.min(80, 42 + Math.sqrt(cases) * 2));
    const warned = group.pins.some((p) => p.warnings.length);
    const node = el("div", null, `map-pin sev-${worstOf(group.pins)}${warned ? " warned" : ""}`);
    node.style.width = node.style.height = `${size}px`;
    node.append(el("b", String(cases)));
    if (!single) node.append(el("span", group.label));
    const lat = group.pins.reduce((s, p) => s + p.lat, 0) / group.pins.length;
    const lon = group.pins.reduce((s, p) => s + p.lon, 0) / group.pins.length;
    const icon = L.divIcon({ html: node, className: "map-icon", iconSize: [size, size] });
    const m = L.marker([lat, lon], { icon, keyboard: true, title: single ? single.name : `${group.label}: ${cases} cases` });
    if (single) {
      const tip = el("div");
      tip.append(el("strong", single.name), el("div", single.problems[0]?.problem || "No problems this week"));
      m.bindTooltip(tip, { direction: "top", offset: [0, -18] });
      m.on("click", () => onPick(single));
    } else {
      m.on("click", () => {
        const bounds = L.latLngBounds(group.pins.map((p) => [p.lat, p.lon]));
        map.fitBounds(bounds.pad(0.4), { maxZoom: map.getZoom() + 3 });
      });
    }
    return m;
  }

  function draw() {
    if (!map) return;
    layer.clearLayers();
    groups().forEach((g) => layer.addLayer(marker(g)));
  }

  function ensure() {
    if (map) return;
    map = L.map(root, { minZoom: 4, maxZoom: 14, zoomSnap: 0.5 });
    // Esri's grey basemap keeps the severity colours readable. Base and city labels are separate layers.
    const shade = window.matchMedia("(prefers-color-scheme: dark)").matches ? "Dark" : "Light";
    const tiles = (name) => `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/${name}/MapServer/tile/{z}/{y}/{x}`;
    L.tileLayer(tiles(`World_${shade}_Gray_Base`), { attribution: "Tiles &copy; Esri", maxZoom: 16 }).addTo(map);
    L.tileLayer(tiles(`World_${shade}_Gray_Reference`), { maxZoom: 16 }).addTo(map);
    layer = L.layerGroup().addTo(map);
    map.fitBounds(INDIA);
    map.on("zoomend", draw);
  }

  return {
    root,
    update(next) {
      pins = next.filter((p) => p.lat !== null && p.lon !== null);
      ensure();
      draw();
    },
    filter(next) {
      filter = next;
      draw();
    },
    resize() {
      if (map) {
        map.invalidateSize();
        map.fitBounds(INDIA);
      }
    },
  };
}
