// The store board: one bubble per store, sized by this week's cases and coloured by its worst severity.
// Bubbles cluster by region, placed roughly where the region sits on a map of India.
import { el, locality, plural, regionText, SEVERITY_NAME } from "../ui.js";

const NS = "http://www.w3.org/2000/svg";
// Where each region's cluster sits, as a share of the board's width and height.
const REGION_AT = { North: [0.5, 0.19], West: [0.16, 0.5], Central: [0.47, 0.5], East: [0.81, 0.45], South: [0.5, 0.82] };
const MIN_R = 11;
const MAX_R = 64;
const FILL = 0.46; // share of the board the bubbles cover, so regions stay apart
const GAP = 3;
const REGION_GAP = 22; // extra space between bubbles of different regions
const STEPS = 320;

function svg(tag, attributes = {}) {
  const node = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

// Pull each bubble toward its region, push overlapping bubbles apart. Same input, same picture.
function layout(pins, width, height) {
  // Area is proportional to cases, scaled so all bubbles together cover FILL of the board.
  const total = pins.reduce((sum, p) => sum + p.cases, 0) || 1;
  const scale = Math.sqrt((FILL * width * height) / (Math.PI * total));
  const nodes = pins.map((pin) => ({ pin, r: Math.min(MAX_R, Math.max(MIN_R, scale * Math.sqrt(pin.cases))) }));
  const byRegion = new Map();
  nodes.forEach((n) => {
    if (!byRegion.has(n.pin.region)) byRegion.set(n.pin.region, []);
    byRegion.get(n.pin.region).push(n);
  });
  byRegion.forEach((group, region) => {
    const [fx, fy] = REGION_AT[region] || [0.5, 0.5];
    const [cx, cy] = [fx * width, fy * height];
    group.sort((a, b) => b.r - a.r || a.pin.store_id.localeCompare(b.pin.store_id));
    group.forEach((n, i) => {
      const angle = i * 2.39996;
      const distance = 26 * Math.sqrt(i);
      Object.assign(n, { x: cx + Math.cos(angle) * distance, y: cy + Math.sin(angle) * distance, cx, cy });
    });
  });
  for (let step = 0; step < STEPS; step += 1) {
    const pull = 0.04 * (1 - step / STEPS) + 0.01;
    for (const n of nodes) {
      n.x += (n.cx - n.x) * pull;
      n.y += (n.cy - n.y) * pull;
    }
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i];
        const b = nodes[j];
        const dx = b.x - a.x || 0.01;
        const dy = b.y - a.y || 0.01;
        const distance = Math.hypot(dx, dy);
        const needed = a.r + b.r + (a.pin.region === b.pin.region ? GAP : REGION_GAP);
        if (distance < needed) {
          const push = (needed - distance) / distance / 2;
          a.x -= dx * push;
          a.y -= dy * push;
          b.x += dx * push;
          b.y += dy * push;
        }
      }
    }
    for (const n of nodes) {
      n.x = Math.min(width - n.r - 4, Math.max(n.r + 4, n.x));
      n.y = Math.min(height - n.r - 4, Math.max(n.r + 22, n.y));
    }
  }
  return { nodes, byRegion };
}

// Split text into lines that fit a width, at most maxLines, with an ellipsis if cut.
function wrap(text, maxChars, maxLines) {
  const words = text.split(/\s+/).map((w) => (w.length > maxChars ? `${w.slice(0, Math.max(maxChars - 1, 1))}…` : w));
  const lines = [];
  let line = "";
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (next.length <= maxChars) line = next;
    else {
      if (line) lines.push(line);
      line = word;
    }
  }
  if (line) lines.push(line);
  if (lines.length > maxLines) {
    lines.length = maxLines;
    lines[maxLines - 1] = `${lines[maxLines - 1].slice(0, maxChars - 1)}…`;
  }
  return lines;
}

function label(n) {
  const group = svg("g", { class: "bubble-text" });
  const name = locality(n.pin.name);
  const biggest = n.pin.problems[0]?.short;
  const lines = [];
  if (n.r >= 38 && biggest) {
    lines.push({ text: wrap(name, Math.floor(n.r / 4.2), 1)[0], cls: "b-name" });
    wrap(biggest, Math.floor(n.r / 3), 2).forEach((t) => lines.push({ text: t, cls: "b-problem" }));
    lines.push({ text: plural(n.pin.cases, "case"), cls: "b-count" });
  } else if (n.r >= 26) {
    lines.push({ text: wrap(name, Math.floor(n.r / 4.4), 1)[0], cls: "b-name" });
    lines.push({ text: String(n.pin.cases), cls: "b-count" });
  } else if (n.r >= 15) {
    lines.push({ text: String(n.pin.cases), cls: "b-count" });
  }
  const step = 14;
  const top = -((lines.length - 1) * step) / 2;
  lines.forEach((line, i) => {
    const t = svg("text", { class: line.cls, x: 0, y: top + i * step, "text-anchor": "middle", "dominant-baseline": "middle" });
    t.textContent = line.text;
    group.append(t);
  });
  return group;
}

function matches(pin, filter) {
  if (filter === "urgent") return pin.urgent > 0;
  if (filter === "warnings") return pin.warnings.length > 0;
  return true;
}

export function bubbleBoard({ onPick }) {
  const root = el("div", null, "bubble-board");
  const canvas = svg("svg", { role: "group", "aria-label": "Stores by cases this week" });
  const labels = svg("g", { class: "region-labels", "aria-hidden": "true" });
  const tip = el("div", null, "bubble-tip", { role: "tooltip", hidden: "" });
  root.append(canvas, tip);
  const shown = new Map(); // store id -> group, so bubbles glide to new places when the week changes
  let filter = "all";

  function showTip(n, group) {
    const pin = n.pin;
    tip.replaceChildren(
      el("strong", pin.name),
      el("span", `${pin.city} · ${plural(pin.cases, "case")}${pin.urgent ? `, ${pin.urgent} urgent` : ""}`),
      el("span", pin.problems[0] ? `Biggest: ${pin.problems[0].problem}` : "No problems this week", "tip-problem"),
    );
    if (pin.warnings.length) tip.append(el("span", `Early warning: ${pin.warnings.join(", ")}`, "tip-warning"));
    tip.hidden = false;
    const box = group.getBoundingClientRect();
    const host = root.getBoundingClientRect();
    const left = Math.min(Math.max(box.left - host.left + box.width / 2, 120), host.width - 120);
    tip.style.left = `${left}px`;
    tip.style.top = `${box.top - host.top}px`;
  }

  // Lay out at the board's real size so text is drawn at its true pixel size, not scaled down.
  function draw(pins) {
    const width = Math.max(root.clientWidth, 320);
    const height = Math.max(root.clientHeight, 300);
    canvas.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const { nodes, byRegion } = layout(pins, width, height);
    labels.replaceChildren();
    byRegion.forEach((group, region) => {
      const top = Math.min(...group.map((n) => n.y - n.r));
      const centre = group.reduce((sum, n) => sum + n.x, 0) / group.length;
      const cases = group.reduce((sum, n) => sum + n.pin.cases, 0);
      const text = svg("text", { class: "region-label", x: centre, y: Math.max(top - 10, 14), "text-anchor": "middle" });
      text.textContent = `${regionText(region).toUpperCase()} · ${cases}`;
      labels.append(text);
    });
    const seen = new Set();
    for (const n of nodes) {
      const id = n.pin.store_id;
      seen.add(id);
      let group = shown.get(id);
      if (!group) {
        group = svg("g", { class: "bubble", tabindex: "0", role: "button" });
        group.style.transform = `translate(${n.x}px, ${n.y}px) scale(0.2)`;
        canvas.append(group);
        shown.set(id, group);
      }
      const severity = n.pin.worst || "clear";
      group.setAttribute("class", `bubble sev-${severity}${n.pin.warnings.length ? " warned" : ""}`);
      group.setAttribute(
        "aria-label",
        `${n.pin.name}: ${plural(n.pin.cases, "case")}, worst ${SEVERITY_NAME[n.pin.worst] || "none"}` +
          (n.pin.problems[0] ? `, biggest problem ${n.pin.problems[0].problem}` : ""),
      );
      const ring = n.pin.warnings.length ? [svg("circle", { class: "b-ring", r: n.r + 5 })] : [];
      group.replaceChildren(...ring, svg("circle", { class: "b-fill", r: n.r }), label(n));
      group.classList.toggle("dimmed", !matches(n.pin, filter));
      group.onclick = () => onPick(n.pin);
      group.onkeydown = (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onPick(n.pin);
        }
      };
      group.onmouseenter = group.onfocus = () => showTip(n, group);
      group.onmouseleave = group.onblur = () => {
        tip.hidden = true;
      };
      requestAnimationFrame(() => {
        group.style.transform = `translate(${n.x}px, ${n.y}px)`;
      });
    }
    for (const [id, group] of shown) {
      if (!seen.has(id)) {
        group.remove();
        shown.delete(id);
      }
    }
    canvas.append(labels); // region names stay on top of the bubbles
  }

  let lastPins = [];
  let pending = 0;
  new ResizeObserver(() => {
    clearTimeout(pending);
    pending = setTimeout(() => lastPins.length && root.offsetParent && draw(lastPins), 150);
  }).observe(root);
  return {
    root,
    update(pins) {
      lastPins = pins;
      draw(pins);
    },
    filter(next) {
      filter = next;
      for (const pin of lastPins) shown.get(pin.store_id)?.classList.toggle("dimmed", !matches(pin, filter));
    },
  };
}
