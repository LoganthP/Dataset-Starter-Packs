/** The signed-in app user and their Kaggle connection, shared across pages. The session itself is an HttpOnly cookie:
 * nothing about it (or any provider credential) is kept in browser storage. */
import { useEffect, useState } from "react";
import { api } from "../api";
import type { KaggleStatus, User } from "../types";

type State = { user: User | null; kaggle: KaggleStatus | null; loaded: boolean };
let state: State = { user: null, kaggle: null, loaded: false };
const subs = new Set<(s: State) => void>();

function emit(next: Partial<State>) {
  state = { ...state, ...next };
  subs.forEach((f) => f(state));
}

export async function refreshAccount(): Promise<State> {
  const [me, kaggle] = await Promise.all([api.me().catch(() => ({ user: null })), api.kaggle().catch(() => null)]);
  emit({ user: me.user, kaggle, loaded: true });
  return state;
}

export function setKaggle(kaggle: KaggleStatus) {
  emit({ kaggle });
}

export function useAccount() {
  const [s, set] = useState(state);
  useEffect(() => {
    subs.add(set);
    if (!state.loaded) void refreshAccount();
    return () => { subs.delete(set); };
  }, []);
  return s;
}
