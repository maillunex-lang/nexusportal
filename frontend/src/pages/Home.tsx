import { api, KIND_LABELS } from "../api";
import { Badge, Card, Empty, ErrorText, fmtDate, statusTone, useLoad } from "../components/ui";

export default function Home() {
  const { data, error } = useLoad(() => api("/api/dashboard"), []);
  const projects: any[] = data?.projects ?? [];
  const sum = (k: string) => projects.reduce((a, p) => a + (p.tasks?.[k] ?? 0), 0);
  return (
    <>
      <div className="page-head">
        <div><h1>Главная</h1><p className="muted">Проекты, задачи, CI, PR и действия владельца</p></div>
        <a className="btn btn-primary" href="#/new">+ Новый проект</a>
      </div>
      <ErrorText error={error} />
      {data?.kill_switch && <p className="error">Глобальный аварийный выключатель включён — автоматизация остановлена. <a href="#/settings">Настройки</a></p>}
      <div className="stats">
        <div className="stat"><span className="muted small">Проекты</span><b>{projects.length}</b></div>
        <div className="stat"><span className="muted small">Готовы к выдаче</span><b>{sum("ready")}</b></div>
        <div className="stat"><span className="muted small">В работе</span><b>{sum("in_progress")}</b></div>
        <div className="stat"><span className="muted small">Заблокированы</span><b>{sum("blocked")}</b></div>
        <div className="stat"><span className="muted small">Открытые PR</span><b>{projects.reduce((a, p) => a + p.open_prs, 0)}</b></div>
        <div className="stat"><span className="muted small">Уведомления</span><b>{data?.unread ?? 0}</b></div>
      </div>
      <Card title="Действия владельца">
        {data && !data.actions.length && <Empty>Всё под контролем — действий не требуется.</Empty>}
        <ul className="list">
          {(data?.actions ?? []).map((a: any, i: number) => (
            <li key={i}>
              <span className="grow"><Badge tone={a.kind === "blocked" ? "err" : "info"}>{a.kind === "blocked" ? "Блокировка" : "Готово"}</Badge> {a.text}</span>
              <a className="btn btn-sm" href="#/tasks">Открыть</a>
            </li>
          ))}
        </ul>
      </Card>
      <div className="grid">
        {projects.map((p) => {
          const total = Object.values(p.tasks as Record<string, number>).reduce((a, b) => a + b, 0);
          const done = p.tasks.done ?? 0;
          return (
            <Card key={p.id} title={p.name} actions={<Badge>{KIND_LABELS[p.kind]}</Badge>}>
              <p className="muted small mono">{p.repo_full_name || "репозиторий не подключён"}</p>
              <progress max={total || 1} value={done} style={{ width: "100%" }} aria-label="Прогресс" />
              <p className="small">Выполнено {done} из {total} · PR: {p.open_prs}{p.failing_prs > 0 && <> · <Badge tone="err">CI упал: {p.failing_prs}</Badge></>}</p>
              <p className="small muted">Релиз: {p.last_release ? `${p.last_release.version} (${fmtDate(p.last_release.published_at)})` : "нет"}</p>
              <div className="row gap wrap">
                {p.auto_merge_enabled ? <Badge tone="ok">Автослияние</Badge> : <Badge>Автослияние выкл.</Badge>}
                {!p.automation_enabled && <Badge tone="err">Автоматизация выкл.</Badge>}
              </div>
            </Card>
          );
        })}
      </div>
      <div className="grid" style={{ marginTop: 16 }}>
        <Card title="Последние слияния">
          {!data?.recent_merges?.length ? <Empty>Нет</Empty> : (
            <ul className="list">{data.recent_merges.map((m: any, i: number) => <li key={i}><span>{m.repo} #{m.number}</span><span className="muted small">{fmtDate(m.ts)}</span></li>)}</ul>
          )}
        </Card>
        <Card title="Серверы: последние операции">
          {!data?.servers?.length ? <Empty>Операций ещё не было</Empty> : (
            <ul className="list">{data.servers.map((s: any, i: number) => (
              <li key={i}><span>{s.name} · {s.env} · {s.action} {s.version}</span><Badge tone={statusTone(s.status)}>{s.status}</Badge></li>
            ))}</ul>
          )}
        </Card>
      </div>
    </>
  );
}
