import { useState } from "react";
import { api, STATUS_LABELS } from "../api";
import { Badge, Card, CopyButton, Empty, ErrorText, Modal, ProjectPicker, PromptBox, statusTone, useCurrentProject, useLoad } from "../components/ui";

const EXECUTORS = [
  { id: "claude", label: "Claude" },
  { id: "chatgpt", label: "ChatGPT" },
  { id: "codex", label: "Codex" },
  { id: "generic", label: "Другой" },
];

function CopyAssignment({ pid, taskId, onShow }: { pid: number; taskId: string; onShow: (t: string, title: string) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const copy = async (ex: string) => {
    setBusy(ex);
    try {
      const r = await api(`/api/projects/${pid}/tasks/${taskId}/assignment?executor=${ex}`);
      try { await navigator.clipboard.writeText(r.prompt); setDone(ex); setTimeout(() => setDone(null), 1500); }
      catch { onShow(r.prompt, `Задание ${taskId}`); }
    } finally { setBusy(null); }
  };
  return (
    <div className="row gap wrap">
      {EXECUTORS.map((e) => (
        <button key={e.id} className={`btn btn-sm ${e.id === "claude" ? "btn-primary" : ""}`} disabled={busy !== null} onClick={() => copy(e.id)}>
          {done === e.id ? "Скопировано ✓" : `Копировать для ${e.label}`}
        </button>
      ))}
      <button className="btn btn-sm btn-ghost" onClick={async () => onShow((await api(`/api/projects/${pid}/tasks/${taskId}/assignment`)).prompt, `Задание ${taskId}`)}>Показать</button>
    </div>
  );
}

function TaskCard({ c, pid, onShow, extra }: { c: any; pid: number; onShow: (t: string, title: string) => void; extra?: React.ReactNode }) {
  return (
    <li>
      <div className="grow">
        <div className="row gap wrap">
          <strong>{c.id}</strong> {c.title}
          <Badge tone={c.priority === "P0" ? "err" : c.priority === "P1" ? "warn" : "neutral"}>{c.priority}</Badge>
          <Badge tone={statusTone(c.status)}>{STATUS_LABELS[c.status] ?? c.status}</Badge>
          {c.executor_hint !== "any" && <Badge tone="info">рекомендуется: {c.executor_hint}</Badge>}
        </div>
        <div className="small">{c.goal}</div>
        <div className="small muted">Этап {c.phase}{c.workstream && ` · поток ${c.workstream}`}{c.estimate && ` · ${c.estimate}`} · ветка <span className="mono">{c.branch}</span>
          {c.pr && <> · <a href={c.pr.url} target="_blank" rel="noreferrer">PR #{c.pr.number}</a> · CI {c.pr.ci}</>}</div>
        {c.blocked_reason && <div className="small error">{c.blocked_reason}</div>}
        {extra}
      </div>
      <CopyAssignment pid={pid} taskId={c.id} onShow={onShow} />
    </li>
  );
}

export default function Now() {
  const cp = useCurrentProject();
  const pid = cp.current?.id;
  const { data, error, reload } = useLoad(() => (pid ? api(`/api/projects/${pid}/now`) : Promise.resolve(null)), [pid]);
  const [show, setShow] = useState<{ text: string; title: string } | null>(null);
  const onShow = (text: string, title: string) => setShow({ text, title });

  return (
    <>
      <div className="page-head">
        <div><h1>Что делать сейчас</h1><p className="muted">Готовые задачи с учётом зависимостей и безопасного параллелизма</p></div>
        <div className="row gap wrap"><ProjectPicker {...cp} /><button className="btn" onClick={reload}>Обновить</button></div>
      </div>
      <ErrorText error={error} />
      {data && !data.blueprint && (
        <Card><Empty>Для проекта нет утверждённого blueprint. <a href="#/blueprint">Импортируйте и утвердите его</a> — после этого здесь появятся задачи.</Empty></Card>
      )}
      {data?.blueprint && pid && (
        <>
          <div className="stats">
            <div className="stat"><span className="muted small">Прогресс</span><b>{data.progress.percent}%</b><span className="small muted">{data.progress.done} из {data.progress.total}</span></div>
            <div className="stat"><span className="muted small">Выдать сейчас</span><b>{data.now.length}</b></div>
            <div className="stat"><span className="muted small">В работе</span><b>{data.active.length}</b><span className="small muted">предел {data.max_parallel}</span></div>
            <div className="stat"><span className="muted small">Требуют внимания</span><b>{data.attention.length}</b></div>
            <div className="stat"><span className="muted small">Blueprint</span><b>v{data.blueprint.version}</b><span className="small muted">{data.blueprint.doc_version}</span></div>
          </div>
          <Card title="Этапы">
            {data.phases.map((ph: any) => (
              <div key={ph.id} className="small" style={{ marginBottom: 6 }}>
                <div className="row between"><span>{ph.id} · {ph.title}</span><span className="muted">{ph.done}/{ph.total}</span></div>
                <progress max={ph.total || 1} value={ph.done} style={{ width: "100%" }} aria-label={ph.title} />
              </div>
            ))}
          </Card>
          {data.attention.length > 0 && (
            <Card title="Требуют внимания — упал CI" className="danger-zone">
              <p className="muted small">Задание уже содержит промпт исправления. Исправление пушится в ту же ветку.</p>
              <ul className="list">{data.attention.map((c: any) => <TaskCard key={c.id} c={c} pid={pid} onShow={onShow} />)}</ul>
            </Card>
          )}
          <Card title="Выдать сейчас">
            {!data.now.length ? <Empty>Нет задач, которые можно безопасно начать сейчас.</Empty> : (
              <ul className="list">{data.now.map((c: any) => <TaskCard key={c.id} c={c} pid={pid} onShow={onShow} />)}</ul>
            )}
          </Card>
          <Card title="В работе">
            {!data.active.length ? <Empty>Нет</Empty> : <ul className="list">{data.active.map((c: any) => <TaskCard key={c.id} c={c} pid={pid} onShow={onShow} />)}</ul>}
          </Card>
          {data.deferred.length > 0 && (
            <Card title="Готовы, но отложены">
              <ul className="list">{data.deferred.map((c: any) => (
                <li key={c.id}><span className="grow"><strong>{c.id}</strong> {c.title}<div className="small muted">{c.reason}</div></span><Badge>{c.priority}</Badge></li>
              ))}</ul>
            </Card>
          )}
          <Card title="Ждут зависимостей">
            {!data.waiting.length ? <Empty>Нет</Empty> : (
              <ul className="list">{data.waiting.map((c: any) => (
                <li key={c.id}><span className="grow"><strong>{c.id}</strong> {c.title}<div className="small muted">ждёт: {c.waiting_for.join(", ")}</div></span><Badge>{c.priority}</Badge></li>
              ))}</ul>
            )}
          </Card>
        </>
      )}
      {show && <Modal title={show.title} onClose={() => setShow(null)}><div className="row gap"><CopyButton text={show.text} /></div><PromptBox title="" text={show.text} /></Modal>}
    </>
  );
}
