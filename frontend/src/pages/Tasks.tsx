import { useEffect, useState } from "react";
import { api, CI_LABELS, Plan, STATUS_LABELS, Task } from "../api";
import { Badge, Card, Empty, ErrorText, Modal, ProjectPicker, PromptBox, statusTone, useCurrentProject, useLoad } from "../components/ui";

const LEVEL_LABELS = { brief: "краткий", standard: "стандартный", extended: "расширенный" } as const;
const FILTERS = ["all", "ready", "in_progress", "blocked", "planned", "done"];

export default function Tasks() {
  const cp = useCurrentProject();
  const pid = cp.current?.id;
  const rm = useLoad(() => (pid ? api(`/api/projects/${pid}/roadmap`) : Promise.resolve(null)), [pid]);
  const [filter, setFilter] = useState("all");
  const [syncState, setSyncState] = useState<{synced_at: string; main_sha: string; branch: string} | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  useEffect(() => {
    if (!pid) return;
    let active = true;
    const refresh = async () => {
      if (!active || document.hidden) return;
      setSyncing(true);
      try {
        const state = await api<{synced_at: string; main_sha: string; branch: string}>(`/api/projects/${pid}/sync-and-state`, {method: "POST"});
        if (active) { setSyncState(state); setSyncError(null); rm.reload(); }
      } catch (e: any) {
        if (active) setSyncError(e.message || "Ошибка синхронизации GitHub");
      } finally { if (active) setSyncing(false); }
    };
    setSyncState(null);
    void refresh();
    const timer = window.setInterval(refresh, 60000);
    const onVisible = () => { if (!document.hidden) void refresh(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { active = false; window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [pid]);
  const [prompt, setPrompt] = useState<{ title: string; text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [level, setLevel] = useState<"brief" | "standard" | "extended">("standard");
  const [ctxTask, setCtxTask] = useState<Task | null>(null);

  const showContext = async (t: Task, lvl = level) => {
    setError(null);
    try {
      const r = await api(`/api/projects/${pid}/tasks/${t.id}/context?level=${lvl}`);
      setCtxTask(t);
      setPrompt({ title: `Контекст ${t.id} · ${LEVEL_LABELS[lvl]} · ${r.chars} симв.`, text: r.prompt });
    } catch (e: any) { setError(e.message); }
  };
  const plan: Plan | null = rm.data?.plan ?? null;
  const tasks = (plan?.tasks ?? []).filter((t) => filter === "all" || t.status === filter);

  const show = async (t: Task, repair = false) => {
    setError(null);
    try {
      const r = repair ? await api(`/api/projects/${pid}/pulls/${t.pr_number}/repair-prompt`) : await api(`/api/projects/${pid}/tasks/${t.id}/prompt`);
      setPrompt({ title: repair ? `Промпт исправления ${t.id}` : `Промпт задачи ${t.id}`, text: r.prompt });
    } catch (e: any) { setError(e.message); }
  };
  const setStatus = async (t: Task, status: string) => {
    setError(null);
    try { await api(`/api/projects/${pid}/tasks/${t.id}/status`, { body: { status } }); rm.reload(); } catch (e: any) { setError(e.message); }
  };

  return (
    <>
      <div className="page-head">
        <div><h1>Задачи</h1><p className="muted">Компактный контекст и промпты для исполнителей</p></div>
        <ProjectPicker {...cp} />
      </div>
      <div className="row gap wrap small muted" aria-live="polite">
        {syncState ? <span>GitHub: {syncState.branch} <span className="mono">{syncState.main_sha.slice(0, 8)}</span> · синхронизация {new Date(syncState.synced_at).toLocaleString("ru-RU")}</span> : <span>GitHub: проверка состояния…</span>}
        {syncing && <span>Обновляется…</span>}
        {syncError && <span className="error">Данные могут устареть: {syncError}</span>}
      </div>
      <div className="tabs" role="tablist">
        {FILTERS.map((f) => (
          <button key={f} role="tab" aria-selected={filter === f} className="btn btn-sm" onClick={() => setFilter(f)}>
            {f === "all" ? "Все" : STATUS_LABELS[f]} ({(plan?.tasks ?? []).filter((t) => f === "all" || t.status === f).length})
          </button>
        ))}
      </div>
      <ErrorText error={error ?? rm.error} />
      <Card>
        {!tasks.length && <Empty>Нет задач</Empty>}
        <ul className="list">
          {tasks.map((t) => (
            <li key={t.id}>
              <div className="grow">
                <div className="row gap wrap"><strong>{t.id}</strong> {t.title} <Badge tone={statusTone(t.status)}>{STATUS_LABELS[t.status]}</Badge></div>
                <div className="small muted">{t.goal}</div>
                <div className="small muted">Ветка <span className="mono">{t.branch}</span> · линия {t.lane}{t.pr_number ? ` · PR #${t.pr_number} · ${CI_LABELS[t.ci_state] ?? t.ci_state}` : ""}</div>
                {t.blocked_reason && <div className="small error">{t.blocked_reason}</div>}
              </div>
              <div className="row gap wrap">
                <button className="btn btn-sm btn-primary" onClick={() => showContext(t)}>Контекст</button>
                <button className="btn btn-sm" onClick={() => show(t)}>Полный промпт</button>
                {t.status === "blocked" && t.pr_number && <button className="btn btn-sm btn-danger" onClick={() => show(t, true)}>Промпт исправления</button>}
                {t.status === "ready" && <button className="btn btn-sm" onClick={() => setStatus(t, "in_progress")}>Выдана</button>}
                {t.status === "blocked" && <button className="btn btn-sm" onClick={() => setStatus(t, "in_progress")}>Снять блок</button>}
                {(t.status === "in_progress" || t.status === "ready") && <button className="btn btn-sm" onClick={() => setStatus(t, "blocked")}>Заблокировать</button>}
              </div>
            </li>
          ))}
        </ul>
      </Card>
      <p className="muted small">Статус «Выполнена» выставляет только портал после зелёного обязательного CI и подтверждённого слияния PR.</p>
      {prompt && (
        <Modal title={prompt.title} onClose={() => { setPrompt(null); setCtxTask(null); }}>
          {ctxTask && (
            <div className="tabs" role="radiogroup" aria-label="Уровень контекста">
              {(Object.keys(LEVEL_LABELS) as (keyof typeof LEVEL_LABELS)[]).map((l) => (
                <button key={l} role="radio" aria-checked={level === l} aria-selected={level === l} className="btn btn-sm"
                  onClick={() => { setLevel(l); showContext(ctxTask, l); }}>{LEVEL_LABELS[l]}</button>
              ))}
            </div>
          )}
          <PromptBox title="" text={prompt.text} />
        </Modal>
      )}
    </>
  );
}
