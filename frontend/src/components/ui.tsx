import { ReactNode, useEffect, useState } from "react";
import { api, Project } from "../api";

export function Card({ title, actions, children, className = "" }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          {title && <h2>{title}</h2>}
          {actions && <div className="row gap">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: string; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function statusTone(s: string): string {
  return ({ done: "ok", success: "ok", published: "ok", ready: "info", in_progress: "warn", pending: "warn", running: "warn",
    blocked: "err", failure: "err", failed: "err", ci_failed: "err", merged: "ok", merge: "ok" } as Record<string, string>)[s] ?? "neutral";
}

export function CopyButton({ text, label = "Копировать" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setDone(true);
    setTimeout(() => setDone(false), 1500);
  };
  return (
    <button type="button" className="btn btn-primary" onClick={copy} aria-live="polite">
      {done ? "Скопировано ✓" : label}
    </button>
  );
}

export function PromptBox({ title, text, onClose }: { title: string; text: string; onClose?: () => void }) {
  return (
    <div className="prompt-box">
      <div className="row between wrap gap">
        <strong>{title}</strong>
        <div className="row gap">
          <CopyButton text={text} />
          {onClose && <button className="btn" onClick={onClose}>Закрыть</button>}
        </div>
      </div>
      <pre className="pre">{text}</pre>
    </div>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const on = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [onClose]);
  return (
    <div className="modal-back" onClick={onClose} role="presentation">
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="row between gap">
          <h2>{title}</h2>
          <button className="btn btn-ghost" onClick={onClose} aria-label="Закрыть">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ErrorText({ error }: { error: string | null }) {
  return error ? <p className="error" role="alert">{error}</p> : null;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="muted empty">{children}</p>;
}

export function Toggle({ label, checked, onChange, hint, danger }: { label: string; checked: boolean; onChange: (v: boolean) => void; hint?: string; danger?: boolean }) {
  return (
    <label className={`toggle ${danger ? "toggle-danger" : ""}`}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="toggle-ui" aria-hidden />
      <span>
        {label}
        {hint && <small className="muted block">{hint}</small>}
      </span>
    </label>
  );
}

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]): { data: T | null; error: string | null; loading: boolean; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn().then((d) => { if (alive) { setData(d); setError(null); } })
      .catch((e) => { if (alive) setError(e.message); })
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { data, error, loading, reload: () => setN((x) => x + 1) };
}

const CURRENT_KEY = "nexus.currentProject";

export function useCurrentProject(): { projects: Project[]; current: Project | null; setCurrent: (id: number) => void; reload: () => void } {
  const { data, reload } = useLoad(() => api<Project[]>("/api/projects"), []);
  const [id, setId] = useState<number | null>(() => {
    try { return Number(localStorage.getItem(CURRENT_KEY)) || null; } catch { return null; }
  });
  const projects = (data ?? []).filter((p) => !p.archived);
  const current = projects.find((p) => p.id === id) ?? projects[0] ?? null;
  const setCurrent = (v: number) => {
    setId(v);
    try { localStorage.setItem(CURRENT_KEY, String(v)); } catch { /* приватный режим */ }
  };
  return { projects, current, setCurrent, reload };
}

export function ProjectPicker({ projects, current, setCurrent }: { projects: Project[]; current: Project | null; setCurrent: (id: number) => void }) {
  if (!projects.length) return <Empty>Проектов пока нет. Создайте первый в разделе «Новый проект».</Empty>;
  return (
    <label className="picker">
      <span className="muted">Проект</span>
      <select value={current?.id ?? ""} onChange={(e) => setCurrent(Number(e.target.value))}>
        {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
    </label>
  );
}

export function fmtDate(s?: string | null): string {
  if (!s) return "—";
  const d = new Date(s.replace(" ", "T") + (s.includes("Z") ? "" : "Z"));
  return isNaN(d.getTime()) ? s : d.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

export function fmtSize(n: number): string {
  if (n > 1 << 20) return (n / (1 << 20)).toFixed(1) + " МБ";
  if (n > 1 << 10) return (n / (1 << 10)).toFixed(0) + " КБ";
  return n + " Б";
}
