// What every screen needs to know: who is signed in, the data loaded, the picked week and region.

export const ctx = {
  user: null,
  status: null,
  week: null,
  region: null,
  unread: 0,
};

const listeners = new Set();

export function onChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function update(patch) {
  Object.assign(ctx, patch);
  listeners.forEach((listener) => listener(patch));
}

export const isAdmin = () => ctx.user?.role === "admin";

// Screens call this after changing a case so lists, counts and the inbox refresh.
const caseListeners = new Set();
export function onCasesChanged(listener) {
  caseListeners.add(listener);
  return () => caseListeners.delete(listener);
}
export function casesChanged() {
  caseListeners.forEach((listener) => listener());
}
