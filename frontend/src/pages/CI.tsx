import { useState } from "react";
import { api, CI_LABELS } from "../api";
import { Badge, Card, Empty, ErrorText, Modal, PromptBox, statusTone, useLoad } from "../components/ui";

export default function CI() {
  const { data, error, reload } = useLoad(() => api<any[]>("/api/ci"), []);
  const [prompt, setPrompt] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const repair = async (p: any) => {
    try { setPrompt((await api(`/api/projects/${p.project_id}/pulls/${p.number}/repair-prompt`)).prompt); } catch (e: any) { setErr(e.message); }
  };
  const evaluate = async (p: any) => {
    setErr(null);
    try { await api(`/api/projects/${p.project_id}/pulls/${p.number}/evaluate`, { method: "POST" }); reload(); } catch (e: any) { setErr(e.message); }
  };
  return (
    <>
      <div className="page-head"><div><h1>CI</h1><p className="muted">Обязательные проверки открытых PR на актуальном SHA</p></div><button className="btn" onClick={reload}>Обновить</button></div>
      <ErrorText error={err ?? error} />
      {data && !data.length && <Empty>Открытых PR нет</Empty>}
      {(data ?? []).map((p) => {
        const req: string[] = p.checks?.required ?? [];
        const checks: Record<string, any> = p.checks?.checks ?? {};
        return (
          <Card key={p.id} title={<>{p.project_name} · #{p.number}</>} actions={<Badge tone={statusTone(p.ci_state)}>{CI_LABELS[p.ci_state] ?? p.ci_state}</Badge>}>
            <p className="small"><a href={p.html_url} target="_blank" rel="noreferrer">{p.title}</a> · <span className="mono">{p.head_sha.slice(0, 10)}</span></p>
            {!req.length && <p className="warn-box small">Обязательные проверки не заданы — автослияние невозможно. Задайте их в настройках проекта или защите ветки.</p>}
            <ul className="list">
              {Object.entries(checks).map(([name, c]) => (
                <li key={name}>
                  <span className="grow">{name} {req.includes(name) && <Badge tone="info">обязательная</Badge>}</span>
                  <span className="row gap"><Badge tone={statusTone(c.state)}>{c.state}</Badge>{c.url && <a className="small" href={c.url} target="_blank" rel="noreferrer">лог</a>}</span>
                </li>
              ))}
              {req.filter((n) => !checks[n]).map((n) => <li key={n}><span>{n} <Badge tone="info">обязательная</Badge></span><Badge tone="warn">ожидание</Badge></li>)}
            </ul>
            <div className="row gap wrap">
              <button className="btn btn-sm" onClick={() => evaluate(p)}>Проверить сейчас</button>
              {p.ci_state === "failure" && <button className="btn btn-sm btn-danger" onClick={() => repair(p)}>Промпт исправления</button>}
            </div>
          </Card>
        );
      })}
      {prompt && <Modal title="Промпт исправления" onClose={() => setPrompt(null)}><PromptBox title="" text={prompt} /></Modal>}
    </>
  );
}
