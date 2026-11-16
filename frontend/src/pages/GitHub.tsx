import { useState } from "react";
import { api, CI_LABELS } from "../api";
import { Badge, Card, Empty, ErrorText, fmtDate, ProjectPicker, statusTone, useCurrentProject, useLoad } from "../components/ui";

export default function GitHub() {
  const cp = useCurrentProject();
  const pid = cp.current?.id;
  const st = useLoad(() => api("/api/github/status"), []);
  const pulls = useLoad(() => (pid ? api<any[]>(`/api/projects/${pid}/pulls`) : Promise.resolve([])), [pid]);
  const commits = useLoad(() => (pid ? api<any[]>(`/api/projects/${pid}/commits`) : Promise.resolve([])), [pid]);
  const log = useLoad(() => (pid ? api<any[]>(`/api/projects/${pid}/merge-log`) : Promise.resolve([])), [pid]);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const sync = async () => {
    setBusy(true); setError(null); setMsg(null);
    try {
      const r = await api(`/api/projects/${pid}/sync`, { method: "POST" });
      setMsg(`Сверка завершена: открытых PR ${r.open_prs}`);
      pulls.reload(); commits.reload(); log.reload();
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };

  return (
    <>
      <div className="page-head">
        <div><h1>GitHub</h1><p className="muted">PR, коммиты, webhooks и журнал автослияния</p></div>
        <ProjectPicker {...cp} />
      </div>
      <Card title="Подключение">
        {st.data && (
          <div className="row gap wrap">
            <Badge tone={st.data.token_configured ? "ok" : "err"}>Токен {st.data.token_configured ? "настроен" : "не настроен"}</Badge>
            <Badge tone={st.data.webhook_secret_configured ? "ok" : "err"}>Секрет webhook {st.data.webhook_secret_configured ? "настроен" : "не настроен"}</Badge>
            {st.data.login && <Badge tone="info">Аккаунт: {st.data.login}</Badge>}
          </div>
        )}
        <ErrorText error={st.data?.error ?? st.error} />
        <p className="muted small">Webhook: <span className="mono">{window.location.origin}/api/github/webhook</span> · Content type: application/json · события: Pull requests, Check suites, Check runs, Statuses, Workflow runs, Pushes. Токен хранится только на сервере.</p>
      </Card>
      {pid && (
        <div className="row gap wrap" style={{ marginBottom: 12 }}>
          <button className="btn btn-primary" onClick={sync} disabled={busy || !cp.current?.repo_full_name}>{busy ? "Сверка…" : "Синхронизировать сейчас"}</button>
          {msg && <span className="ok-box small">{msg}</span>}
        </div>
      )}
      <ErrorText error={error} />
      <Card title="Pull Requests">
        {!pulls.data?.length ? <Empty>PR пока нет</Empty> : (
          <ul className="list">
            {pulls.data.map((p) => (
              <li key={p.id}>
                <div className="grow">
                  <a href={p.html_url} target="_blank" rel="noreferrer">#{p.number} {p.title}</a>
                  <div className="small muted"><span className="mono">{p.branch}</span> · SHA <span className="mono">{p.head_sha.slice(0, 10)}</span>{p.task_key && ` · задача ${p.task_key}`}{p.is_fork && " · форк"}</div>
                </div>
                <div className="row gap wrap">
                  <Badge tone={statusTone(p.state)}>{p.state}</Badge>
                  <Badge tone={statusTone(p.ci_state)}>{CI_LABELS[p.ci_state] ?? p.ci_state}</Badge>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <div className="grid">
        <Card title="Журнал автослияния">
          {!log.data?.length ? <Empty>Решений ещё не было</Empty> : (
            <ul className="list">{log.data.map((m) => (
              <li key={m.id}><div className="grow">#{m.number} <Badge tone={statusTone(m.decision)}>{m.decision}</Badge><div className="small muted">{m.reasons.join("; ")}</div></div><span className="small muted">{fmtDate(m.ts)}</span></li>
            ))}</ul>
          )}
        </Card>
        <Card title="Коммиты">
          {!commits.data?.length ? <Empty>Нет данных</Empty> : (
            <ul className="list">{commits.data.map((c) => <li key={c.sha}><span className="grow">{c.message.split("\n")[0]}<div className="small muted mono">{c.sha.slice(0, 10)} · {c.branch} · {c.author}</div></span></li>)}</ul>
          )}
        </Card>
      </div>
      <Card title="Последние доставки webhook">
        {!st.data?.deliveries?.length ? <Empty>Доставок ещё не было</Empty> : (
          <div className="table-wrap"><table><thead><tr><th>Событие</th><th>Репозиторий</th><th>Время</th><th>Статус</th></tr></thead><tbody>
            {st.data.deliveries.map((d: any) => <tr key={d.delivery_id}><td>{d.event}</td><td className="mono">{d.repo}</td><td>{fmtDate(d.received_at)}</td><td><Badge tone={d.status === "processed" ? "ok" : d.status === "error" ? "err" : "warn"}>{d.status}</Badge>{d.error && <div className="small error">{d.error}</div>}</td></tr>)}
          </tbody></table></div>
        )}
      </Card>
    </>
  );
}
