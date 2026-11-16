import { ChangeEvent, useState } from "react";
import { api } from "../api";
import { Badge, Card, CopyButton, Empty, ErrorText, fmtDate, Modal, ProjectPicker, PromptBox, statusTone, useCurrentProject, useLoad } from "../components/ui";

const STATUS: Record<string, string> = { draft: "черновик", approved: "утверждён", superseded: "заменён", rejected: "отклонён" };
const EVENTS: Record<string, string> = {
  blueprint_submitted: "загружена версия", blueprint_approved: "утверждена версия", task_added: "задача добавлена",
  task_changed: "задача изменена", task_removed: "задача удалена", pr_opened: "открыт PR", pr_updated: "обновлён PR",
  ci_failed: "упал CI", merged: "PR слит", assignment_copied: "задание скопировано",
};

export default function Blueprint() {
  const cp = useCurrentProject();
  const pid = cp.current?.id;
  const versions = useLoad(() => (pid ? api<any[]>(`/api/projects/${pid}/blueprints`) : Promise.resolve([])), [pid]);
  const hist = useLoad(() => (pid ? api<any[]>(`/api/projects/${pid}/blueprint-history`) : Promise.resolve([])), [pid]);
  const std = useLoad(() => api("/api/blueprint/standard"), []);
  const [text, setText] = useState("");
  const [check, setCheck] = useState<any>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [view, setView] = useState<{ title: string; text: string } | null>(null);
  const [path, setPath] = useState("docs/blueprint.json");

  const reload = () => { versions.reload(); hist.reload(); };
  const fail = (e: any) => {
    const d = e?.message ?? String(e);
    setError(d);
  };
  const parse = (): any | null => {
    try { return JSON.parse(text); } catch { setErrors(["Некорректный JSON"]); return null; }
  };
  const doValidate = async () => {
    setErrors([]); setError(null); setCheck(null);
    const doc = parse(); if (!doc) return;
    const r = await api("/api/blueprint/validate", { body: { document: doc } });
    setCheck(r); setErrors(r.errors);
  };
  const submit = async () => {
    setErrors([]); setError(null); setMsg(null);
    const doc = parse(); if (!doc) return;
    try {
      const r = await api(`/api/projects/${pid}/blueprints`, { body: { document: doc, source: "вставка" } });
      setMsg(`Сохранена версия ${r.version} (черновик). Проверьте изменения и утвердите.`); setText(""); reload();
    } catch (e: any) { setErrors(e.errors ?? []); fail(e); }
  };
  const pull = async () => {
    setErrors([]); setError(null); setMsg(null);
    try { const r = await api(`/api/projects/${pid}/blueprints/pull`, { body: { path } }); setMsg(`Загружена версия ${r.version} из GitHub`); reload(); }
    catch (e: any) { setErrors(e.errors ?? []); fail(e); }
  };
  const approve = async (id: number, force = false) => {
    setError(null); setMsg(null);
    try { await api(`/api/projects/${pid}/blueprints/${id}/approve`, { body: { force } }); setMsg("Версия утверждена, задачи синхронизированы с дорожной картой"); reload(); }
    catch (e: any) {
      if (!force && e.message.includes("удаляет задачи в работе") && confirm(e.message + "\n\nУтвердить принудительно?")) return approve(id, true);
      fail(e);
    }
  };
  const reject = async (id: number) => { try { await api(`/api/projects/${pid}/blueprints/${id}/reject`, { method: "POST" }); reload(); } catch (e) { fail(e); } };
  const onFile = async (e: ChangeEvent<HTMLInputElement>) => { const f = e.target.files?.[0]; if (f) setText(await f.text()); };
  const showVersion = async (id: number) => {
    const r = await api(`/api/projects/${pid}/blueprints/${id}`);
    setView({ title: `Blueprint v${r.version}`, text: JSON.stringify(r.content, null, 2) });
  };

  return (
    <>
      <div className="page-head">
        <div><h1>Blueprint</h1><p className="muted">План ИИ-архитектора: импорт, проверка, утверждение и версии</p></div>
        <ProjectPicker {...cp} />
      </div>
      <Card title="Стандарт nexus-blueprint/1">
        <p className="small muted">После утверждения GDD и дорожной карты скопируйте промпт архитектора в ChatGPT или Claude — он вернёт готовый JSON.</p>
        {std.data && (
          <div className="row gap wrap">
            <CopyButton text={std.data.architect_prompt} label="Копировать промпт ИИ-архитектора" />
            <button className="btn btn-sm" onClick={() => setView({ title: "Инструкция", text: std.data.guide })}>Инструкция</button>
            <button className="btn btn-sm" onClick={() => setView({ title: "JSON Schema", text: std.data.schema })}>JSON Schema</button>
            <button className="btn btn-sm" onClick={() => setText(std.data.template)}>Шаблон в редактор</button>
          </div>
        )}
      </Card>
      {pid && (
        <Card title="Импорт">
          <div className="row gap wrap" style={{ marginBottom: 8 }}>
            <label className="btn btn-sm">Открыть файл<input type="file" accept=".json,application/json" onChange={onFile} style={{ display: "none" }} /></label>
            <input style={{ maxWidth: 260 }} value={path} onChange={(e) => setPath(e.target.value)} aria-label="Путь в репозитории" />
            <button className="btn btn-sm" onClick={pull} disabled={!cp.current?.repo_full_name}>Загрузить из GitHub</button>
          </div>
          <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder='{"format": "nexus-blueprint/1", ...}' style={{ minHeight: 220 }} aria-label="JSON blueprint" />
          <div className="row gap wrap" style={{ marginTop: 8 }}>
            <button className="btn" onClick={doValidate} disabled={!text}>Проверить</button>
            <button className="btn btn-primary" onClick={submit} disabled={!text}>Сохранить как новую версию</button>
          </div>
          {check && !check.errors.length && <p className="ok-box small">Документ корректен ({check.format}): этапов {check.summary.phases}, задач {check.summary.tasks}. Порядок: {check.order.join(" → ")}</p>}
          {errors.map((e) => <p key={e} className="error small">{e}</p>)}
          {check?.warnings?.map((w: string) => <p key={w} className="warn-box small">{w}</p>)}
        </Card>
      )}
      <ErrorText error={error ?? versions.error} />
      {msg && <p className="ok-box small">{msg}</p>}
      <Card title="Версии">
        {!versions.data?.length ? <Empty>Версий пока нет</Empty> : (
          <ul className="list">{versions.data.map((v) => (
            <li key={v.id}>
              <div className="grow">
                <div className="row gap wrap"><strong>v{v.version}</strong> <span className="muted small">документ {v.doc_version}</span><Badge tone={v.status === "approved" ? "ok" : v.status === "draft" ? "info" : "neutral"}>{STATUS[v.status]}</Badge>{v.source_format !== "nexus-blueprint/1" && <Badge tone="warn">{v.source_format}</Badge>}</div>
                <div className="small muted">{fmtDate(v.created_at)} · {v.source} · sha256 <span className="mono">{v.sha256.slice(0, 12)}</span></div>
                <div className="small">+{v.changes.added?.length ?? 0} · −{v.changes.removed?.length ?? 0} · изменено {v.changes.changed?.length ?? 0}
                  {v.changes.removed?.length > 0 && <span className="muted"> (удаляются: {v.changes.removed.join(", ")})</span>}
                  {v.changes.changed?.length > 0 && <span className="muted"> (изменены: {v.changes.changed.map((c: any) => `${c.id}: ${c.fields.join("/")}`).join("; ")})</span>}</div>
                {v.validation.warnings?.length > 0 && <details className="small"><summary>Предупреждения: {v.validation.warnings.length}</summary>{v.validation.warnings.map((w: string) => <div key={w}>{w}</div>)}</details>}
              </div>
              <div className="row gap wrap">
                <button className="btn btn-sm" onClick={() => showVersion(v.id)}>JSON</button>
                {v.status === "draft" && <><button className="btn btn-sm btn-primary" onClick={() => approve(v.id)}>Утвердить</button><button className="btn btn-sm btn-danger" onClick={() => reject(v.id)}>Отклонить</button></>}
              </div>
            </li>
          ))}</ul>
        )}
      </Card>
      <Card title="История">
        {!hist.data?.length ? <Empty>Событий нет</Empty> : (
          <ul className="list">{hist.data.slice(0, 100).map((e) => (
            <li key={e.id}><span className="grow">{e.task_id && <strong>{e.task_id} </strong>}{EVENTS[e.event] ?? e.event}<div className="small muted">{e.detail}</div></span>
              <span className="small muted">{e.blueprint_version ? `v${e.blueprint_version} · ` : ""}{fmtDate(e.ts)}</span>
              <Badge tone={statusTone(e.event === "merged" ? "done" : e.event === "ci_failed" ? "failure" : "")}>{e.event}</Badge></li>
          ))}</ul>
        )}
      </Card>
      {view && <Modal title={view.title} onClose={() => setView(null)}><PromptBox title="" text={view.text} /></Modal>}
    </>
  );
}

