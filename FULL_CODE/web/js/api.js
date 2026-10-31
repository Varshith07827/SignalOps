// Calls to the backend. Every change request carries the header the server checks against request forgery.

let onSignedOut = () => {};

export function whenSignedOut(handler) {
  onSignedOut = handler;
}

export async function api(path, { method = "GET", body, form } = {}) {
  const options = { method, credentials: "same-origin", headers: {} };
  if (method !== "GET") options.headers["X-Requested-With"] = "voice-of-store";
  if (form) options.body = form;
  else if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error("The server can't be reached. Check that it is running.");
  }
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 && path !== "/api/login") onSignedOut();
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? "Please check the form and try again." : data.detail;
    throw new Error(detail || `The server answered ${response.status}. Try again.`);
  }
  return data;
}

export function query(params) {
  const clean = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return new URLSearchParams(clean).toString();
}
