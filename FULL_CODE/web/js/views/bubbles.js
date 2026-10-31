// The store board: one bubble per store, sized by this week's cases and coloured by its worst severity.
// Bubbles cluster by region, placed roughly where the region sits on a map of India. A small physics loop
// moves them: they grow out of their region, settle, and glide to new sizes when the week changes.
import { el, locality, plural, regionText, SEVERITY_NAME } from "../ui.js";

const NS = "http://www.w3.org/2000/svg";
// Where each region's cluster sits, as a share of the board's width and height.
const REGION_AT = { North: [0.5, 0.19], West: [0.16, 0.5], Central: [0.48, 0.5], East: [0.83, 0.46], South: [0.5, 0.84] };
const SEVERITY_FILLS = ["critical", "high", "medium", "low", "clear"];
const MIN_R = 12;
const MAX_R = 66;
const FILL = 0.4; // share of the board the bubbles cover, so regions stay apart
const GAP = 4;
const REGION_GAP = 40; // extra space between bubbles of different regions
const HALO_PAD = 16;
// Physics: how hard bubbles are pulled home, how quickly motion dies down, how fast sizes ease.
const GRAVITY = 0.012;
const DAMPING = 0.78;
const GROW = 0.14;
const COOLING = 0.982;
const REST = 0.02;

function svg(tag, attributes = {}) {
  const node = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

// Same store, same starting angle, so the picture is stable between visits.
function angleFor(id) {
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return (hash % 360) * (Math.PI / 180);
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

// What fits inside a bubble of radius r: name, biggest problem and count for big ones, less for small ones.
function labelLines(pin, r) {
  const name = locality(pin.name);
  const biggest = pin.problems[0]?.short;
  if (r >= 40 && biggest) {
    return [
      { text: wrap(name, Math.floor(r / 4.3), 1)[0], cls: "b-name" },
      ...wrap(biggest, Math.floor(r / 3.1), 2).map((text) => ({ text, cls: "b-problem" })),
      { text: plural(pin.cases, "case"), cls: "b-count" },
    ];
  }
  if (r >= 27) return [{ text: wrap(name, Math.floor(r / 4.5), 1)[0], cls: "b-name" }, { text: String(pin.cases), cls: "b-count" }];
  if (r >= 15) return [{ text: String(pin.cases), cls: "b-count" }];
  return [];
}

function labelNode(lines) {
  const group = svg("g", { class: "b-text" });
  const step = 14;
  const top = -((lines.length - 1) * step) / 2;
  lines.forEach((line, i) => {
    const text = svg("text", { class: line.cls, y: top + i * step, "text-anchor": "middle", "dominant-baseline": "central" });
    text.textContent = line.text;
    group.append(text);
  });
  return group;
}

// Gradients, sheen, shadow and halo fills. Colours come from styles.css so dark mode follows the theme.
function definitions() {
  const defs = svg("defs");
  for (const severity of SEVERITY_FILLS) {
    const gradient = svg("radialGradient", { id: `bubble-${severity}`, cx: "35%", cy: "30%", r: "80%", class: `fill-${severity}` });
    gradient.append(svg("stop", { offset: "0%", class: "s-light" }), svg("stop", { offset: "62%", class: "s-base" }), svg("stop", { offset: "100%", class: "s-deep" }));
    defs.append(gradient);
  }
  const sheen = svg("radialGradient", { id: "bubble-sheen", cx: "32%", cy: "22%", r: "55%" });
  sheen.append(svg("stop", { offset: "0%", class: "sheen-top" }), svg("stop", { offset: "100%", class: "sheen-end" }));
  const halo = svg("radialGradient", { id: "region-halo", cx: "50%", cy: "50%", r: "50%" });
  halo.append(svg("stop", { offset: "0%", class: "halo-in" }), svg("stop", { offset: "78%", class: "halo-mid" }), svg("stop", { offset: "100%", class: "halo-out" }));
  const shadow = svg("filter", { id: "bubble-shadow", x: "-40%", y: "-40%", width: "180%", height: "180%" });
  shadow.append(svg("feDropShadow", { dx: "0", dy: "6", stdDeviation: "7", class: "shadow-drop" }));
  defs.append(sheen, halo, shadow);
  return defs;
}

function matches(pin, filter) {
  if (filter === "urgent") return pin.urgent > 0;
  if (filter === "warnings") return pin.warnings.length > 0;
  return true;
}

export function bubbleBoard({ onPick }) {
  const root = el("div", null, "bubble-board");
  const canvas = svg("svg", { role: "group", "aria-label": "Stores by cases this week" });
  const halos = svg("g", { class: "halos", "aria-hidden": "true" });
  const layer = svg("g", { class: "bubbles" });
  const labels = svg("g", { class: "region-labels", "aria-hidden": "true" });
  canvas.append(definitions(), halos, layer, labels);
  const tip = el("div", null, "bubble-tip", { role: "tooltip", hidden: "" });
  root.append(canvas, tip);

  const nodes = new Map(); // store id -> bubble state and its SVG parts
  const regions = new Map(); // region -> halo and label
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let size = { width: 0, height: 0 };
  let filter = "all";
  let heat = 0;
  let frame = 0;
  let hovered = null;

  function centreOf(region) {
    const [fx, fy] = REGION_AT[region] || [0.5, 0.5];
    return [fx * size.width, fy * size.height];
  }

  function showTip(node) {
    const pin = node.pin;
    const head = el("div", null, "tip-head");
    head.append(el("i", null, `dot ${pin.worst || "clear"}`), el("strong", pin.name));
    const stats = el("div", null, "tip-stats");
    for (const [label, value] of [["Cases", pin.cases], ["Urgent", pin.urgent], ["Warnings", pin.warnings.length]]) {
      const cell = el("span");
      cell.append(el("b", String(value)), el("small", label));
      stats.append(cell);
    }
    tip.replaceChildren(head, el("span", `${pin.city} · ${pin.region} region`, "tip-meta"), stats);
    if (pin.problems[0]) {
      const biggest = el("p", null, "tip-problem");
      biggest.append(el("small", "Biggest problem"), el("span", pin.problems[0].problem));
      tip.append(biggest);
    }
    if (pin.warnings.length) tip.append(el("p", `Early warning: ${pin.warnings.join(", ")}`, "tip-warning"));
    tip.hidden = false;
    placeTip(node);
  }

  // Above the bubble if the card fits there, otherwise below it.
  function placeTip(node) {
    const left = Math.min(Math.max(node.x, 140), size.width - 140);
    const below = node.y - node.r - 12 < tip.offsetHeight;
    tip.classList.toggle("below", below);
    tip.style.left = `${left}px`;
    tip.style.top = `${below ? node.y + node.r + 12 : node.y - node.r - 12}px`;
  }

  function hover(node) {
    hovered = node;
    root.classList.toggle("focusing", Boolean(node));
    for (const other of nodes.values()) other.g.classList.toggle("hot", other === node);
    if (node) showTip(node);
    else tip.hidden = true;
  }

  function build(pin) {
    const g = svg("g", { class: "bubble", tabindex: "0", role: "button" });
    const body = svg("g", { class: "b-body" });
    const pulse = svg("circle", { class: "b-pulse" });
    const ring = svg("circle", { class: "b-ring" });
    const fill = svg("circle", { class: "b-fill", filter: "url(#bubble-shadow)" });
    const sheen = svg("circle", { class: "b-sheen", fill: "url(#bubble-sheen)" });
    const text = svg("g");
    body.append(pulse, ring, fill, sheen, text);
    g.append(body);
    layer.append(g);
    const [cx, cy] = centreOf(pin.region);
    const angle = angleFor(pin.store_id);
    const node = { pin, g, pulse, ring, fill, sheen, text, x: cx + Math.cos(angle) * 20, y: cy + Math.sin(angle) * 20, vx: 0, vy: 0, r: 0, target: 0, lines: "" };
    g.addEventListener("click", () => onPick(node.pin));
    g.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onPick(node.pin);
      }
    });
    g.addEventListener("mouseenter", () => hover(node));
    g.addEventListener("focus", () => hover(node));
    g.addEventListener("mouseleave", () => hover(null));
    g.addEventListener("blur", () => hover(null));
    return node;
  }

  function dress(node) {
    const pin = node.pin;
    const severity = pin.worst || "clear";
    const warned = pin.warnings.length > 0;
    node.g.setAttribute("class", `bubble sev-${severity}${warned ? " warned" : ""}${node === hovered ? " hot" : ""}`);
    node.g.classList.toggle("dimmed", !matches(pin, filter));
    node.fill.setAttribute("fill", `url(#bubble-${severity})`);
    node.g.setAttribute(
      "aria-label",
      `${pin.name}: ${plural(pin.cases, "case")}, worst ${SEVERITY_NAME[pin.worst] || "none"}` +
        (pin.problems[0] ? `, biggest problem ${pin.problems[0].problem}` : "") +
        (warned ? ", early warning" : ""),
    );
    const lines = labelLines(pin, node.target);
    const key = JSON.stringify(lines);
    if (key !== node.lines) {
      node.lines = key;
      node.text.replaceChildren(labelNode(lines));
    }
  }

  function region(name) {
    if (!regions.has(name)) {
      const halo = svg("circle", { class: "halo", fill: "url(#region-halo)" });
      const tag = svg("g", { class: "region-tag" });
      const box = svg("rect", { rx: "11", height: "22", y: "-11" });
      const text = svg("text", { "text-anchor": "middle", "dominant-baseline": "central" });
      tag.append(box, text);
      halos.append(halo);
      labels.append(tag);
      regions.set(name, { halo, tag, box, text, label: "" });
    }
    return regions.get(name);
  }

  // Bubble areas are proportional to cases, scaled so together they cover FILL of the board.
  function setTargets() {
    const all = [...nodes.values()].filter((n) => !n.leaving);
    const total = all.reduce((sum, n) => sum + n.pin.cases, 0) || 1;
    const scale = Math.sqrt((FILL * size.width * size.height) / (Math.PI * total));
    for (const n of all) n.target = Math.min(MAX_R, Math.max(MIN_R, scale * Math.sqrt(n.pin.cases)));
  }

  function step() {
    const list = [...nodes.values()];
    let motion = 0;
    for (const n of list) {
      const dr = (n.target - n.r) * GROW;
      n.r += dr;
      const [cx, cy] = centreOf(n.pin.region);
      const pull = GRAVITY * (0.35 + heat);
      n.vx += (cx - n.x) * pull;
      n.vy += (cy - n.y) * pull;
      motion = Math.max(motion, Math.abs(dr));
    }
    for (let i = 0; i < list.length; i += 1) {
      for (let j = i + 1; j < list.length; j += 1) {
        const a = list[i];
        const b = list[j];
        const dx = b.x - a.x || 0.01;
        const dy = b.y - a.y || 0.01;
        const distance = Math.hypot(dx, dy);
        const needed = a.r + b.r + (a.pin.region === b.pin.region ? GAP : REGION_GAP);
        if (distance < needed) {
          const push = ((needed - distance) / distance) * 0.5;
          a.x -= dx * push;
          a.y -= dy * push;
          b.x += dx * push;
          b.y += dy * push;
          a.vx -= dx * push * 0.12;
          a.vy -= dy * push * 0.12;
          b.vx += dx * push * 0.12;
          b.vy += dy * push * 0.12;
        }
      }
    }
    for (const n of list) {
      n.vx *= DAMPING;
      n.vy *= DAMPING;
      n.x = Math.min(size.width - n.r - 6, Math.max(n.r + 6, n.x + n.vx));
      n.y = Math.min(size.height - n.r - 6, Math.max(n.r + 30, n.y + n.vy));
      motion = Math.max(motion, Math.abs(n.vx), Math.abs(n.vy));
    }
    heat *= COOLING;
    return motion;
  }

  // Once motion has died down, nudge apart any bubbles still touching so the final picture is clean.
  function relax(passes = 40) {
    const list = [...nodes.values()].filter((n) => !n.leaving);
    for (let pass = 0; pass < passes; pass += 1) {
      let moved = false;
      for (let i = 0; i < list.length; i += 1) {
        for (let j = i + 1; j < list.length; j += 1) {
          const a = list[i];
          const b = list[j];
          const dx = b.x - a.x || 0.01;
          const dy = b.y - a.y || 0.01;
          const distance = Math.hypot(dx, dy);
          const needed = a.r + b.r + (a.pin.region === b.pin.region ? GAP : REGION_GAP);
          if (distance < needed - 0.5) {
            const push = ((needed - distance) / distance) * 0.5;
            a.x -= dx * push;
            a.y -= dy * push;
            b.x += dx * push;
            b.y += dy * push;
            moved = true;
          }
        }
      }
      for (const n of list) {
        n.x = Math.min(size.width - n.r - 6, Math.max(n.r + 6, n.x));
        n.y = Math.min(size.height - n.r - 6, Math.max(n.r + 30, n.y));
      }
      if (!moved) return;
    }
  }

  function render() {
    const groups = new Map();
    for (const n of nodes.values()) {
      n.g.setAttribute("transform", `translate(${n.x.toFixed(1)} ${n.y.toFixed(1)})`);
      const r = Math.max(n.r, 0.01);
      n.fill.setAttribute("r", r.toFixed(1));
      n.sheen.setAttribute("r", r.toFixed(1));
      n.ring.setAttribute("r", (r + 5).toFixed(1));
      n.pulse.setAttribute("r", (r + 5).toFixed(1));
      n.text.setAttribute("transform", `scale(${n.target ? Math.min(r / n.target, 1).toFixed(3) : 0})`);
      if (!n.leaving) groups.set(n.pin.region, [...(groups.get(n.pin.region) || []), n]);
    }
    for (const [name, parts] of regions) {
      const members = groups.get(name);
      parts.halo.toggleAttribute("hidden", !members);
      parts.tag.toggleAttribute("hidden", !members);
      if (!members) continue;
      const weight = members.reduce((sum, n) => sum + n.r * n.r, 0) || 1;
      const cx = members.reduce((sum, n) => sum + n.x * n.r * n.r, 0) / weight;
      const cy = members.reduce((sum, n) => sum + n.y * n.r * n.r, 0) / weight;
      const radius = Math.max(...members.map((n) => Math.hypot(n.x - cx, n.y - cy) + n.r)) + HALO_PAD;
      parts.halo.setAttribute("cx", cx.toFixed(1));
      parts.halo.setAttribute("cy", cy.toFixed(1));
      parts.halo.setAttribute("r", radius.toFixed(1));
      const [x, y] = tagSpot(parts, members, cx);
      parts.tag.setAttribute("transform", `translate(${x.toFixed(1)} ${y.toFixed(1)})`);
    }
    if (hovered && !tip.hidden) placeTip(hovered);
  }

  // Put a region's name tag where it covers the fewest bubbles: above the cluster first, then below or nudged.
  function tagSpot(parts, members, cx) {
    const width = Number(parts.box.getAttribute("width")) || 120;
    const top = Math.min(...members.map((n) => n.y - n.r)) - 16;
    const bottom = Math.max(...members.map((n) => n.y + n.r)) + 16;
    const left = Math.min(...members.map((n) => n.x - n.r)) - width / 2 - 8;
    const right = Math.max(...members.map((n) => n.x + n.r)) + width / 2 + 8;
    const middle = members.reduce((sum, n) => sum + n.y, 0) / members.length;
    const spots = [[cx, top], [cx - width / 2, top], [cx + width / 2, top], [cx, bottom], [left, middle], [right, middle]];
    const inside = spots.map(([x, y]) => [
      Math.min(Math.max(x, width / 2 + 6), size.width - width / 2 - 6),
      Math.min(Math.max(y, 17), size.height - 17),
    ]);
    const covered = ([x, y]) => {
      let count = 0;
      for (const n of nodes.values()) {
        const nx = Math.max(x - width / 2, Math.min(n.x, x + width / 2));
        const ny = Math.max(y - 11, Math.min(n.y, y + 11));
        if (Math.hypot(n.x - nx, n.y - ny) < n.r) count += 1;
      }
      return count;
    };
    let best = inside[0];
    let fewest = covered(best);
    for (const spot of inside.slice(1)) {
      const count = covered(spot);
      if (count < fewest) [best, fewest] = [spot, count];
    }
    return best;
  }

  function loop() {
    const motion = step();
    render();
    for (const [id, n] of nodes) {
      if (n.leaving && n.r < 0.5) {
        n.g.remove();
        nodes.delete(id);
      }
    }
    if (motion > REST || heat > 0.05) frame = requestAnimationFrame(loop);
    else {
      frame = 0;
      relax();
      render();
    }
  }

  function start(energy) {
    heat = Math.max(heat, energy);
    if (calm) {
      // Reduced motion: settle out of sight and show the final picture at once.
      for (let i = 0; i < 400 && (step() > REST || heat > 0.05); i += 1);
      for (const [id, n] of nodes) {
        n.r = n.target;
        if (n.leaving) {
          n.g.remove();
          nodes.delete(id);
        }
      }
      relax();
      render();
      return;
    }
    if (!frame) frame = requestAnimationFrame(loop);
  }

  function measure() {
    size = { width: Math.max(root.clientWidth, 320), height: Math.max(root.clientHeight, 300) };
    canvas.setAttribute("viewBox", `0 0 ${size.width} ${size.height}`);
  }

  function paintRegionTags(pins) {
    const totals = new Map();
    for (const pin of pins) totals.set(pin.region, (totals.get(pin.region) || 0) + pin.cases);
    for (const [name, cases] of totals) {
      const parts = region(name);
      const label = `${regionText(name).toUpperCase()} · ${cases}`;
      if (label === parts.label) continue;
      parts.label = label;
      parts.text.textContent = label;
      // Measured once the text is on the page; a rough width stands in if the board is hidden.
      const width = (parts.text.getComputedTextLength() || label.length * 6.6) + 22;
      parts.box.setAttribute("width", width.toFixed(0));
      parts.box.setAttribute("x", (-width / 2).toFixed(0));
    }
  }

  let lastPins = [];
  let pending = 0;
  new ResizeObserver(() => {
    clearTimeout(pending);
    pending = setTimeout(() => {
      if (!lastPins.length || !root.offsetParent) return;
      measure();
      setTargets();
      for (const n of nodes.values()) dress(n);
      start(0.6);
    }, 150);
  }).observe(root);

  return {
    root,
    update(pins) {
      lastPins = pins;
      measure();
      const seen = new Set();
      for (const pin of pins) {
        seen.add(pin.store_id);
        const node = nodes.get(pin.store_id) || build(pin);
        node.pin = pin;
        node.leaving = false;
        nodes.set(pin.store_id, node);
      }
      for (const [id, n] of nodes) {
        if (!seen.has(id)) {
          n.leaving = true;
          n.target = 0;
        }
      }
      setTargets();
      for (const n of nodes.values()) if (!n.leaving) dress(n);
      paintRegionTags(pins);
      start(1);
    },
    filter(next) {
      filter = next;
      for (const n of nodes.values()) n.g.classList.toggle("dimmed", !matches(n.pin, filter));
    },
  };
}
