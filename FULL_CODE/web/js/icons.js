// Line icons drawn for this app on a 24 x 24 grid. Each entry is a list of SVG path strings.

const PATHS = {
  overview: ["M4 4h7v7H4z", "M13 4h7v4h-7z", "M13 10h7v10h-7z", "M4 13h7v7H4z"],
  brief: ["M7 3h7l5 5v13H7z", "M14 3v5h5", "M10 12h6", "M10 16h6"],
  cases: ["M9 6h11", "M9 12h11", "M9 18h11", "M4 6l1 1 2-2", "M4 12l1 1 2-2", "M4 18l1 1 2-2"],
  inbox: ["M3 13l3-8h12l3 8", "M3 13v6h18v-6", "M3 13h5l1 2h6l1-2h5"],
  bell: ["M6 16V11a6 6 0 0 1 12 0v5l2 2H4z", "M10 20a2 2 0 0 0 4 0"],
  review: ["M11 4a7 7 0 1 1 0 14a7 7 0 0 1 0-14z", "M16 16l4 4"],
  model: ["M4 20V10", "M10 20V4", "M16 20v-7", "M22 20H2"],
  store: ["M4 9l1.5-5h13L20 9", "M4 9h16v2a3 3 0 0 1-5.3 2 3 3 0 0 1-5.4 0A3 3 0 0 1 4 11z", "M5 13v7h14v-7", "M10 20v-4h4v4"],
  report: ["M12 4v12", "M6 10l6-6 6 6", "M5 20h14"],
  upload: ["M12 16V4", "M7 9l5-5 5 5", "M4 16v4h16v-4"],
  logout: ["M10 4H5v16h5", "M14 8l4 4-4 4", "M18 12H9"],
  alert: ["M12 4l9 16H3z", "M12 10v4", "M12 17v.5"],
  check: ["M5 12l4 4 10-10"],
  x: ["M6 6l12 12", "M18 6L6 18"],
  chevron: ["M6 9l6 6 6-6"],
  back: ["M15 6l-6 6 6 6"],
  star: ["M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"],
  clock: ["M12 3a9 9 0 1 1 0 18a9 9 0 0 1 0-18z", "M12 7v5l3 2"],
  map: ["M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z", "M9 4v14", "M15 6v14"],
  bubbles: ["M8 6a4 4 0 1 1 0 8a4 4 0 0 1 0-8z", "M16.5 11a3.5 3.5 0 1 1 0 7a3.5 3.5 0 0 1 0-7z", "M15 3a2 2 0 1 1 0 4a2 2 0 0 1 0-4z"],
  message: ["M4 5h16v11H9l-5 4z"],
  trendUp: ["M4 17l6-6 4 4 6-6", "M15 9h5v5"],
  trendDown: ["M4 7l6 6 4-4 6 6", "M15 15h5v-5"],
  print: ["M7 9V3h10v6", "M7 17H4v-8h16v8h-3", "M7 14h10v7H7z"],
  team: ["M9 11a3 3 0 1 0 0-6a3 3 0 0 0 0 6z", "M3 20a6 6 0 0 1 12 0", "M16 11a3 3 0 1 0-1-5.8", "M17 14a6 6 0 0 1 4 6"],
};

export function icon(name, size = 18) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", "icon");
  for (const d of PATHS[name] || []) {
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}
