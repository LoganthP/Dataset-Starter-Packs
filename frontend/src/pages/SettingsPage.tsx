/** Settings: the app account (keeps your connections and reports separate) and Connect Kaggle. */
import { CheckCircle2, ExternalLink, KeyRound, Loader2, LogOut, PlugZap, Unplug } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError, timeAgo } from "../api";
import { ErrorBox } from "../components/ui";
import { refreshAccount, setKaggle, useAccount } from "../lib/account";

function AccountCard() {
  const { user, loaded } = useAccount();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await (mode === "login" ? api.logIn(email, password) : api.signUp(email, password));
      setPassword("");
      await refreshAccount();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!loaded) return <section className="glass rounded-3xl p-6"><Loader2 className="animate-spin" size={18} /></section>;
  if (user) {
    return (
      <section className="glass rounded-3xl p-6" aria-labelledby="acct">
        <h2 id="acct" className="font-display text-xl font-bold">Account</h2>
        <p className="mt-2 text-ink-soft">Signed in as <strong className="text-ink">{user.email}</strong>. Runs you start and the providers you connect are visible only to you.</p>
        <button className="btn-ghost mt-4" onClick={async () => { await api.logOut(); await refreshAccount(); }}><LogOut size={15} /> Log out</button>
      </section>
    );
  }
  return (
    <section className="glass rounded-3xl p-6" aria-labelledby="acct">
      <h2 id="acct" className="font-display text-xl font-bold">{mode === "login" ? "Log in" : "Create an account"}</h2>
      <p className="mt-1 text-sm text-ink-soft">An account keeps your Kaggle connection and your reports separate from everyone else's. Anonymous runs stay shared.</p>
      <form className="mt-4 grid max-w-md gap-3" onSubmit={submit}>
        <label className="text-sm font-semibold">Email<input className="field mt-1" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label className="text-sm font-semibold">Password<input className="field mt-1" type="password" required minLength={mode === "signup" ? 10 : 1}
          autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        {mode === "signup" && <p className="-mt-1 text-xs text-ink-faint">At least 10 characters.</p>}
        <div className="flex flex-wrap items-center gap-3">
          <button className="btn-clay bg-peri" disabled={busy}>{busy && <Loader2 size={15} className="animate-spin" />}{mode === "login" ? "Log in" : "Sign up"}</button>
          <button type="button" className="text-sm font-semibold text-link underline underline-offset-2" onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(null); }}>
            {mode === "login" ? "New here? Sign up" : "Have an account? Log in"}
          </button>
        </div>
        {error && <ErrorBox message={error} />}
      </form>
    </section>
  );
}

function KaggleCard({ returnTo }: { returnTo: string | null }) {
  const { user, kaggle } = useAccount();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const [editing, setEditing] = useState(false);
  const [how, setHow] = useState<"token" | "json" | "pair">("token");
  const [token, setToken] = useState("");
  const [username, setUsername] = useState("");
  const [key, setKey] = useState("");
  const [kaggleJson, setKaggleJson] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const connected = !!kaggle?.connected;
  const showForm = !connected || editing;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = how === "token" ? { token } : how === "json" ? { kaggleJson } : { username, key };
      const st = await api.connectKaggle(body);
      setKaggle(st);
      setToken(""); setKey(""); setKaggleJson(""); // never kept in the page after it's stored server-side
      setEditing(false);
      if (returnTo) nav(returnTo);
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="glass rounded-3xl p-6" aria-labelledby="kg">
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="kg" className="font-display text-xl font-bold">Kaggle</h2>
        {connected
          ? <span className="inline-flex items-center gap-1 rounded-full bg-ok/12 px-2.5 py-0.5 text-xs font-bold text-ok"><CheckCircle2 size={13} /> Connected</span>
          : <span className="rounded-full bg-white/80 px-2.5 py-0.5 text-xs font-bold text-ink-soft">Not connected</span>}
      </div>
      {sp.get("kaggle") === "error" && <div className="mt-3"><ErrorBox message={`Kaggle sign-in didn't finish (${sp.get("reason") ?? "error"}). Try again.`} /></div>}
      {connected && (
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-ink-soft">Account</dt><dd className="font-semibold">{kaggle?.account ?? "API token"}</dd>
          <dt className="text-ink-soft">Method</dt><dd>{kaggle?.method}</dd>
          <dt className="text-ink-soft">Verified</dt><dd>{timeAgo(kaggle?.verifiedAt)}</dd>
          {kaggle?.lastError && <><dt className="text-ink-soft">Last error</dt><dd className="text-bad">{kaggle.lastError}</dd></>}
        </dl>
      )}
      <p className="mt-3 max-w-[70ch] text-sm text-ink-soft">
        Once connected, Kaggle dataset pages list their files here and <strong>Fetch and analyze</strong> runs inside the app. Your token is checked with Kaggle,
        stored encrypted on the server, used only in request headers, and never shown again or kept in your browser.
      </p>
      {!user && (
        <p className="mt-4 rounded-2xl bg-sun/30 px-4 py-3 text-sm text-warn-ink">Log in or sign up above first, so the connection belongs to your account.</p>
      )}
      {user && connected && !editing && (
        <div className="mt-4 flex flex-wrap gap-2">
          <button className="btn-ghost" onClick={() => setEditing(true)}><PlugZap size={15} /> Reconnect</button>
          <button className="btn-ghost" onClick={async () => setKaggle(await api.disconnectKaggle())}><Unplug size={15} /> Disconnect</button>
          {returnTo && <Link className="btn-clay bg-peri" to={returnTo}>Back to the dataset</Link>}
        </div>
      )}
      {user && showForm && (
        <div className="mt-4 space-y-4">
          {kaggle?.oauthAvailable && (
            <a className="btn-clay bg-ink text-on-accent" href={api.kaggleOAuthUrl(returnTo ?? "/settings")}><KeyRound size={15} /> Sign in with Kaggle</a>
          )}
          <form onSubmit={submit} className="max-w-xl space-y-3">
            <fieldset>
              <legend className="text-sm font-semibold">{kaggle?.oauthAvailable ? "Or use an API token" : "Connect with an official Kaggle API token"}</legend>
              <p className="mt-1 text-xs text-ink-soft">
                Create one at <a className="text-link underline" href="https://www.kaggle.com/settings" target="_blank" rel="noreferrer">kaggle.com/settings <ExternalLink size={11} className="inline" /></a> → API.
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5" role="radiogroup" aria-label="Token type">
                {([["token", "API token (KGAT_…)"], ["json", "kaggle.json file"], ["pair", "Username + key"]] as const).map(([v, t]) => (
                  <button key={v} type="button" role="radio" aria-checked={how === v} onClick={() => setHow(v)}
                    className={`rounded-xl px-3 py-1.5 text-sm font-semibold ${how === v ? "bg-ink text-on-accent" : "bg-white/70 text-ink-soft"}`}>{t}</button>
                ))}
              </div>
            </fieldset>
            {how === "token" && <label className="block text-sm font-semibold">API token<input className="field mt-1 font-mono" type="password" autoComplete="off" required value={token} onChange={(e) => setToken(e.target.value)} /></label>}
            {how === "json" && (
              <label className="block text-sm font-semibold">kaggle.json
                <input className="field mt-1" type="file" accept=".json,application/json" onChange={async (e) => setKaggleJson((await e.target.files?.[0]?.text()) ?? "")} />
                <span className="mt-1 block text-xs font-normal text-ink-faint">Read in this page and sent once over HTTPS; not stored in the browser.</span>
              </label>
            )}
            {how === "pair" && (
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-sm font-semibold">Username<input className="field mt-1" autoComplete="off" required value={username} onChange={(e) => setUsername(e.target.value)} /></label>
                <label className="text-sm font-semibold">Key<input className="field mt-1 font-mono" type="password" autoComplete="off" required value={key} onChange={(e) => setKey(e.target.value)} /></label>
              </div>
            )}
            <div className="flex gap-2">
              <button className="btn-clay bg-peri" disabled={busy || (how === "json" && !kaggleJson)}>{busy && <Loader2 size={15} className="animate-spin" />}{connected ? "Reconnect Kaggle" : "Connect Kaggle"}</button>
              {editing && <button type="button" className="btn-ghost" onClick={() => setEditing(false)}>Cancel</button>}
            </div>
            {error && <ErrorBox message={error} />}
          </form>
        </div>
      )}
    </section>
  );
}

export default function SettingsPage() {
  const [sp] = useSearchParams();
  const ret = sp.get("return");
  const returnTo = ret && ret.startsWith("/") ? ret : null;
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <h1 className="font-display text-4xl font-extrabold tracking-tight">Settings</h1>
      {returnTo && <p className="text-sm text-ink-soft">Connect Kaggle, then you'll go back to <Link className="text-link underline" to={returnTo}>the dataset</Link> with your selection kept.</p>}
      <AccountCard />
      <KaggleCard returnTo={returnTo} />
    </div>
  );
}
