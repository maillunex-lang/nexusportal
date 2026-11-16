import { useState } from "react";
import { api, Plan, STATUS_LABELS, Task } from "../api";
import { Badge, Card, Empty, ErrorText, Modal, ProjectPicker, PromptBox, statusTone, useCurrentProject, useLoad } from "../components/ui";

export default function Roadmap() {
  const cp = useCurrentProject();
  const pid = cp.current?.id;
  const rm = useLoad(() => (pid ? api(`/api/projects/${pid}/roadmap`) : Promise.resolve(null)), [pid]);
  const [prompt, setPrompt] = useState<{ title: string; text: string } | null>(null);
  const [importing, setImporting] = useState(false);
  const [json, setJson] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"stages" | "lanes" | "md" | "index">("stages");
  const ci = useLoad(() => (pid && view === "index" ? api(`/api/projects/${pid}/context-index`) : Promise.resolve(null)), [pid, view]);
  const pullIndex = async () => {
    setError(null);
    try {
      const r = await api(`/api/projects/${pid}/context-index/pull`, { method: "POST" });
      ci.reload();
      if (r.check.warnings.length) setError("Устаревшие ссылки: " + r.check.warnings.join("; "));
    } catch (e: any) { setError(e.message); }
  };

  const plan: Plan | null = rm.data?.plan ?? null;
  const openPrompt = async (t: Task) => {
    try {
      const r = await api(`/api/projects/${pid}/tasks/${t.id}/prompt`);
      setPrompt({ title: `Промпт задачи ${t.id}`, text: r.prompt });
    } catch (e: any) { setError(e.message); }
  };
  const pull = async () => {
    setError(null);
    try { await api(`/api/projects/${pid}/roadmap/pull`, { method: "POST" }); rm.reload(); } catch (e: any) { setError(e.message); }
  };
  const doImport = async () => {
    setError(null);
    try {
      await api(`/api/projects/${pid}/roadmap`, { method: "PUT", body: { plan: JSON.parse(json) } });
      setImporting(false);
      rm.reload();
    } catch (e: any) { setError(e instanceof SyntaxError ? "Некорректный JSON" : e.message); }
  };

  const TaskCard = ({ t }: { t: Task }) => (
    <div className={`task ${t.status}`}>
      <div className="row between gap"><strong>{t.id}</strong><Badge tone={statusTone(t.status)}>{STATUS_LABELS[t.status]}</Badge></div>
      <span>{t.title}</span>
      <span className="lane-tag">линия: {t.lane}{t.depends_on.length ? ` · после ${t.depends_on.join(", ")}` : ""}</span>
      {t.pr_number && <span className="small muted">PR #{t.pr_number} · {t.ci_state || "—"}</span>}
      <button className="btn btn-sm" onClick={() => openPrompt(t)}>Промпт</button>
    </div>
  );

  return (
    <>
      <div className="page-head">
        <div><h1>Дорожная карта</h1><p className="muted">Этапы, зависимости и параллельные линии разработки</p></div>
        <ProjectPicker {...cp} />
      </div>
      <ErrorText error={error ?? rm.error} />
      {pid && (
        <div className="row gap wrap" style={{ marginBottom: 12 }}>
          <div className="tabs" role="tablist">
            {(["stages", "lanes", "md", "index"] as const).map((v) => (
              <button key={v} role="tab" aria-selected={view === v} className="btn btn-sm" onClick={() => setView(v)}>{{ stages: "По этапам", lanes: "По линиям", md: "Markdown", index: "Индекс контекста" }[v]}</button>
            ))}
          </div>
          <button className="btn btn-sm" onClick={pull} disabled={!cp.current?.repo_full_name}>Загрузить work_plan.json из GitHub</button>
          <button className="btn btn-sm" onClick={() => { setJson(JSON.stringify(plan, null, 2)); setImporting(true); }}>Редактировать JSON</button>
        </div>
      )}
      {rm.data && (
        <Card title="Готовы к выдаче">
          {rm.data.ready.length ? <div className="row gap wrap">{rm.data.ready.map((id: string) => <Badge key={id} tone="info">{id}</Badge>)}</div> : <Empty>Нет готовых задач</Empty>}
        </Card>
      )}
      {plan && view === "stages" && (plan.stages.length ? plan.stages : [{ id: "", title: "Задачи" }]).map((s) => {
        const tasks = plan.tasks.filter((t) => t.stage === s.id || (!s.id && !t.stage));
        return tasks.length ? (
          <Card key={s.id || "none"} title={`${s.id ? s.id + " · " : ""}${s.title}`} className="stage">
            <div className="task-grid">{tasks.map((t) => <TaskCard key={t.id} t={t} />)}</div>
          </Card>
        ) : null;
      })}
      {plan && view === "lanes" && Object.entries(rm.data.lanes as Record<string, string[]>).map(([lane, ids]) => (
        <Card key={lane} title={`Линия «${lane}»`}>
          <div className="task-grid">{ids.map((id) => <TaskCard key={id} t={plan.tasks.find((t) => t.id === id)!} />)}</div>
        </Card>
      ))}
      {plan && view === "md" && <Card><pre className="pre">{rm.data.markdown}</pre></Card>}
      {view === "index" && ci.data && (
        <Card title="NEXUS Smart Context" actions={<button className="btn btn-sm" onClick={pullIndex} disabled={!cp.current?.repo_full_name}>Обновить из GitHub</button>}>
          {[...ci.data.check.errors, ...ci.data.check.warnings].map((w: string) => <p key={w} className="warn-box small">{w}</p>)}
          {ci.data.markdown ? <pre className="pre">{ci.data.markdown}</pre> : <Empty>Индекс модулей не задан (docs/context/modules.json)</Empty>}
        </Card>
      )}
      {prompt && <Modal title={prompt.title} onClose={() => setPrompt(null)}><PromptBox title="" text={prompt.text} /></Modal>}
      {importing && (
        <Modal title="work_plan.json" onClose={() => setImporting(false)}>
          <p className="muted small">Статус done нельзя выставить вручную — только подтверждённым слиянием PR.</p>
          <textarea value={json} onChange={(e) => setJson(e.target.value)} style={{ minHeight: "50vh" }} aria-label="JSON плана" />
          <ErrorText error={error} />
          <div className="row gap" style={{ marginTop: 10 }}><button className="btn btn-primary" onClick={doImport}>Проверить и сохранить</button></div>
        </Modal>
      )}
    </>
  );
}
