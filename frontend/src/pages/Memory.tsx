import { FormEvent, useState } from "react";
import { api } from "../api";
import { Badge, Card, CopyButton, Empty, ErrorText, fmtDate, Modal, ProjectPicker, PromptBox, useCurrentProject, useLoad } from "../components/ui";

const KINDS: Record<string, string> = { decision: "Решения", task: "История задач", error: "Ошибки", context: "Контекст", doc: "Документы" };

export default function Memory() {
  const cp = useCurrentProject();
  const pid = cp.current?.id;
  const [kind, setKind] = useState<string>("");
  const mem = useLoad(() => (pid ? api<any[]>(`/api/projects/${pid}/memory${kind ? `?kind=${kind}` : ""}`) : Promise.resolve([])), [pid, kind]);
  const [ctx, setCtx] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const add = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setError(null);
    try {
      await api(`/api/projects/${pid}/memory`, { body: Object.fromEntries(f.entries()) });
      (e.target as HTMLFormElement).reset();
      mem.reload();
    } catch (err: any) { setError(err.message); }
  };
  const del = async (id: number) => {
    if (!confirm("Удалить запись памяти?")) return;
    try { await api(`/api/projects/${pid}/memory/${id}`, { method: "DELETE" }); mem.reload(); } catch (err: any) { setError(err.message); }
  };
  const context = async () => {
    try { setCtx((await api(`/api/projects/${pid}/context`)).prompt); } catch (err: any) { setError(err.message); }
  };

  return (
    <>
      <div className="page-head">
        <div><h1>Память</h1><p className="muted">Изолированная память проекта: решения, история, ошибки, контекст, документы</p></div>
        <div className="row gap wrap"><ProjectPicker {...cp} />{pid && <button className="btn btn-primary" onClick={context}>Контекст для ИИ</button>}</div>
      </div>
      <ErrorText error={error ?? mem.error} />
      {pid && (
        <Card title="Новая запись">
          <form className="col" onSubmit={add}>
            <div className="form-grid">
              <label>Тип<select name="kind" defaultValue="decision">{Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
              <label>Заголовок<input name="title" required maxLength={300} /></label>
              <label>Ссылка (документ, PR)<input name="ref" placeholder="docs/GDD.md#3" /></label>
            </div>
            <label>Текст<textarea name="body" /></label>
            <div><button className="btn btn-primary">Сохранить</button></div>
          </form>
        </Card>
      )}
      <div className="tabs" role="tablist">
        <button className="btn btn-sm" role="tab" aria-selected={kind === ""} onClick={() => setKind("")}>Все</button>
        {Object.entries(KINDS).map(([k, v]) => <button key={k} role="tab" aria-selected={kind === k} className="btn btn-sm" onClick={() => setKind(k)}>{v}</button>)}
      </div>
      <Card>
        {!mem.data?.length ? <Empty>Записей нет</Empty> : (
          <ul className="list">{mem.data.map((m) => (
            <li key={m.id}>
              <div className="grow">
                <div className="row gap wrap"><Badge tone={m.kind === "error" ? "err" : m.kind === "decision" ? "ok" : "neutral"}>{KINDS[m.kind]}</Badge><strong>{m.title}</strong></div>
                {m.body && <div className="small" style={{ whiteSpace: "pre-wrap" }}>{m.body.length > 600 ? m.body.slice(0, 600) + "…" : m.body}</div>}
                <div className="small muted">{fmtDate(m.created_at)}{m.ref && <> · <span className="mono">{m.ref}</span></>}</div>
              </div>
              <button className="btn btn-sm btn-ghost" onClick={() => del(m.id)} aria-label="Удалить">✕</button>
            </li>
          ))}</ul>
        )}
      </Card>
      {ctx && (
        <Modal title="Контекст для ИИ" onClose={() => setCtx(null)}>
          <p className="muted small">Актуальный промпт передачи дел ИИ-директору. Секреты автоматически удаляются.</p>
          <div className="row gap"><CopyButton text={ctx} /></div>
          <PromptBox title="" text={ctx} />
        </Modal>
      )}
    </>
  );
}
