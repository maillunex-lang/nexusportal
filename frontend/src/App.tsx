import { FormEvent, useEffect, useState } from "react";
import { api, onUnauthorized, setCsrf } from "./api";
import { ErrorText } from "./components/ui";
import { useRoute } from "./router";
import Home from "./pages/Home";
import Projects from "./pages/Projects";
import NewProject from "./pages/NewProject";
import Roadmap from "./pages/Roadmap";
import Tasks from "./pages/Tasks";
import GitHub from "./pages/GitHub";
import CI from "./pages/CI";
import Servers from "./pages/Servers";
import Releases from "./pages/Releases";
import Apk from "./pages/Apk";
import Memory from "./pages/Memory";
import Notifications from "./pages/Notifications";
import Settings from "./pages/Settings";

export const NAV = [
  { to: "/", label: "Главная", icon: "⌂", main: true },
  { to: "/projects", label: "Проекты", icon: "▦", main: true },
  { to: "/new", label: "Новый проект", icon: "+" },
  { to: "/roadmap", label: "Дорожная карта", icon: "⇶" },
  { to: "/tasks", label: "Задачи", icon: "☑", main: true },
  { to: "/github", label: "GitHub", icon: "⑂" },
  { to: "/ci", label: "CI", icon: "◉", main: true },
  { to: "/servers", label: "Серверы", icon: "⌁" },
  { to: "/releases", label: "Релизы", icon: "⬆" },
  { to: "/apk", label: "APK", icon: "▣" },
  { to: "/memory", label: "Память", icon: "✎" },
  { to: "/notifications", label: "Уведомления", icon: "🔔" },
  { to: "/settings", label: "Настройки", icon: "⚙" },
];

const PAGES: Record<string, () => JSX.Element> = {
  "/": Home, "/projects": Projects, "/new": NewProject, "/roadmap": Roadmap, "/tasks": Tasks, "/github": GitHub,
  "/ci": CI, "/servers": Servers, "/releases": Releases, "/apk": Apk, "/memory": Memory,
  "/notifications": Notifications, "/settings": Settings,
};

type AuthState = { loading: boolean; authenticated: boolean; ownerExists: boolean };

export default function App() {
  const [auth, setAuth] = useState<AuthState>({ loading: true, authenticated: false, ownerExists: true });
  const [route] = useRoute();
  const [more, setMore] = useState(false);
  const [unread, setUnread] = useState(0);

  const check = () =>
    api("/api/auth/status")
      .then((s) => {
        setCsrf(s.csrf_token);
        setAuth({ loading: false, authenticated: s.authenticated, ownerExists: s.owner_exists });
      })
      .catch(() => setAuth({ loading: false, authenticated: false, ownerExists: true }));

  useEffect(() => {
    check();
    onUnauthorized(() => setAuth((a) => ({ ...a, authenticated: false })));
  }, []);

  useEffect(() => {
    if (!auth.authenticated) return;
    const load = () => api("/api/notifications?unread=true").then((n) => setUnread(n.length)).catch(() => undefined);
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [auth.authenticated, route]);

  useEffect(() => setMore(false), [route]);

  if (auth.loading) return <div className="splash">NEXUS PORTAL</div>;
  if (!auth.authenticated) return <Login ownerExists={auth.ownerExists} onDone={check} />;

  const base = "/" + (route.split("/")[1] ?? "");
  const Page = PAGES[base] ?? Home;
  const mainNav = NAV.filter((n) => n.main);

  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Навигация">
        <div className="brand"><img src="/icon.svg" alt="" width={32} height={32} /> <span>NEXUS PORTAL</span></div>
        <nav>
          {NAV.map((n) => (
            <a key={n.to} href={`#${n.to}`} className={base === n.to ? "active" : ""} aria-current={base === n.to ? "page" : undefined}>
              <span className="nav-ico" aria-hidden>{n.icon}</span>{n.label}
              {n.to === "/notifications" && unread > 0 && <span className="dot">{unread}</span>}
            </a>
          ))}
        </nav>
      </aside>
      <main className="content" id="main">
        <Page />
      </main>
      <nav className="bottom-nav" aria-label="Основная навигация">
        {mainNav.map((n) => (
          <a key={n.to} href={`#${n.to}`} className={base === n.to ? "active" : ""} aria-current={base === n.to ? "page" : undefined}>
            <span className="nav-ico" aria-hidden>{n.icon}</span><span>{n.label}</span>
          </a>
        ))}
        <button className={more ? "active" : ""} onClick={() => setMore(!more)} aria-expanded={more}>
          <span className="nav-ico" aria-hidden>☰</span><span>Ещё{unread > 0 ? ` · ${unread}` : ""}</span>
        </button>
      </nav>
      {more && (
        <div className="sheet-back" onClick={() => setMore(false)}>
          <div className="sheet" onClick={(e) => e.stopPropagation()} role="menu">
            {NAV.filter((n) => !n.main).map((n) => (
              <a key={n.to} href={`#${n.to}`} role="menuitem" className={base === n.to ? "active" : ""}>
                <span className="nav-ico" aria-hidden>{n.icon}</span>{n.label}
                {n.to === "/notifications" && unread > 0 && <span className="dot">{unread}</span>}
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Login({ ownerExists, onDone }: { ownerExists: boolean; onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api("/api/auth/login", { body: { username, password } });
      setCsrf(r.csrf_token);
      onDone();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="login">
      <form className="card login-card" onSubmit={submit}>
        <div className="brand center"><img src="/icon.svg" alt="" width={48} height={48} /></div>
        <h1>NEXUS PORTAL</h1>
        <p className="muted">Вход владельца</p>
        {!ownerExists && (
          <p className="warn-box">Владелец ещё не создан. На сервере выполните: <code>python -m backend.cli set-owner &lt;логин&gt;</code></p>
        )}
        <label>Логин<input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></label>
        <label>Пароль<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        <ErrorText error={error} />
        <button className="btn btn-primary wide" disabled={busy}>{busy ? "Вход…" : "Войти"}</button>
      </form>
    </div>
  );
}
