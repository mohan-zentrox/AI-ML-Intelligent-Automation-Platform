/**
 * Minimal auth store backed by localStorage. No external state-management
 * library is needed for this vertical slice; if the app grows, this is the
 * seam to swap in something like zustand/redux without touching callers
 * (they only import getAuth/setAuth/clearAuth/subscribe from here).
 */
export interface AuthState {
  token?: string;
  apiKey?: string;
  role: string;
  roleId: string;
}

const STORAGE_KEY = "synapse.auth";
type Listener = (state: AuthState | null) => void;
const listeners = new Set<Listener>();

export function getAuth(): AuthState | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthState;
  } catch {
    return null;
  }
}

export function setAuth(state: AuthState): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  listeners.forEach((l) => l(state));
}

export function clearAuth(): void {
  localStorage.removeItem(STORAGE_KEY);
  listeners.forEach((l) => l(null));
}

export function subscribeAuth(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function isAuthenticated(): boolean {
  return getAuth() !== null;
}

export function hasAnyRole(roles: string[]): boolean {
  const auth = getAuth();
  return !!auth && roles.includes(auth.role);
}
