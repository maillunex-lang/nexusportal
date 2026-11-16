import { FormEvent, useState } from "react";
import { api } from "../api";
import { Badge, Card, Empty, ErrorText, fmtDate, ProjectPicker, statusTone, useCurrentProject, useLoad } from "../components/ui";

export default function Servers() {
  const cp = useCurrentProject();
  const pid = cp.current?.id;
  const ov = useLoad(() => (pid ? api(`/api/projects/${pid}/deploy`) : Promise.resolve(null)), [pid]);
  const settings = useLoad(() => api("/api/settings"), []);
  const [env, setEnv] = useState<"dev" | "prod">("dev");
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [remote, setRemote] = useState<any>(null);
  const recipe = ov.data?.recipes?.[env];
  const [kind, setKind] = useState("static");
  const [unit, setUnit] = useState("");
  const [hc, setHc] = useState("");
  const [script, setScript] = useState("");
  const [editing, setEditing] = useState(false);

  const startEdit = () => {
    setKind(recipe?.kind ?? "static");
    setUnit(recipe?.config?.systemd_unit ?? "");
    setHc(recipe?.config?.healthcheck_url ?? "");
    setScript(recipe?.script ?? "");
    setEditing(true);
  };
  const run = async (fn: () => Promise<string>) => {
    setError(null); setMsg(null);
    try { setMsg(await fn()); ov.reload(); } catch (e: any) { setError(e.message); }
  };
  const saveRecipe = () => run(async () => {
    const config: Record<string, string> = {};
    if (unit) config.systemd_unit = unit;
    if (hc) config.healthcheck_url = hc;
    const r = await api(`/api/projects/${pid}/deploy/${env}/recipe`, { method: "PUT", body: { kind, config, script } });
    setEditing(false);
    return `Сценарий ${env} сохранён: версия ${r.version}`;
  });
  const deploy = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    run(async () => { const r = await api(`/api/projects/${pid}/deploy/${env}`, { form: fd }); return `Развёрнуто ${r.version} (${r.status})`; });
  };
  const rollback = (target?: string) => run(async () => { const r = await api(`/api/projects/${pid}/deploy/${env}/rollback`, { body: { target: target ?? null } }); return `Откат на ${r.version}`; });
  const loadRemote = () => run(async () => { setRemote(await api(`/api/projects/${pid}/deploy/${env}/releases`)); return "Список версий обновлён"; });

  const s = settings.data;
  return (
    <>
      <div className="page-head">
        <div><h1>Серверы</h1><p className="muted">Один VPS · прямой SSH · сценарии dev/prod, резервные копии и откат</p></div>
        <ProjectPicker {...cp} />
      </div>
      <Card title="VPS">
        {s && (
          <div className="row gap wrap">
            <Badge tone="info">Исполнитель: {s.settings.deploy_executor === "local" ? "локально (портал на этом VPS)" : "SSH"}</Badge>
            <Badge tone={s.settings.ssh_host ? "ok" : "warn"}>Хост: {s.settings.ssh_host || "не задан"}</Badge>
            <Badge tone={s.server.ssh_key_configured ? "ok" : "warn"}>SSH-ключ {s.server.ssh_key_configured ? "есть" : "нет"}</Badge>
            <Badge tone={s.server.known_hosts_configured ? "ok" : "warn"}>known_hosts {s.server.known_hosts_configured ? "есть" : "нет"}</Badge>
          </div>
        )}
        <p className="muted small">Портал работает только внутри <span className="mono">{ov.data?.base_dirs?.[env] ?? s?.server.deploy_root}</span> и службами <span className="mono">nexus-{cp.current?.slug}-*.service</span>. Команды из PR не выполняются.</p>
      </Card>
      {pid && (
        <>
          <div className="tabs" role="tablist">
            {(["dev", "prod"] as const).map((e) => <button key={e} role="tab" aria-selected={env === e} className="btn btn-sm" onClick={() => { setEnv(e); setEditing(false); setRemote(null); }}>{e}</button>)}
          </div>
          {env === "prod" && !cp.current?.prod_deploy_allowed && <p className="warn-box small">Продакшен-деплой не разрешён для проекта. Разрешение включается в разделе «Проекты».</p>}
          <ErrorText error={error ?? ov.error} />
          {msg && <p className="ok-box small">{msg}</p>}
          <Card title={`Сценарий ${env}`} actions={<button className="btn btn-sm" onClick={startEdit}>{recipe ? "Изменить" : "Создать"}</button>}>
            {recipe ? (
              <p className="small">Тип: <b>{recipe.kind}</b> · версия {recipe.version} · sha256 <span className="mono">{recipe.sha256.slice(0, 12)}</span>{recipe.config.systemd_unit && <> · служба <span className="mono">{recipe.config.systemd_unit}</span></>}</p>
            ) : <Empty>Сценарий не задан</Empty>}
            {recipe?.script && <pre className="pre">{recipe.script}</pre>}
            {editing && (
              <div className="col" style={{ marginTop: 12 }}>
                <div className="form-grid">
                  <label>Тип<select value={kind} onChange={(e) => setKind(e.target.value)}><option value="static">static — только файлы</option><option value="script">script — файлы + сценарий</option></select></label>
                  <label>Служба systemd (необязательно)<input value={unit} placeholder={`nexus-${cp.current?.slug}-web.service`} onChange={(e) => setUnit(e.target.value)} /></label>
                  <label>Проверка работоспособности URL<input value={hc} placeholder="http://127.0.0.1:8080/health" onChange={(e) => setHc(e.target.value)} /></label>
                </div>
                {kind === "script" && <label>Сценарий bash (выполняется в каталоге релиза; переменные NEXUS_RELEASE_DIR, NEXUS_SHARED, NEXUS_VERSION)<textarea value={script} onChange={(e) => setScript(e.target.value)} /></label>}
                <div className="row gap"><button className="btn btn-primary" onClick={saveRecipe}>Сохранить новую версию</button><button className="btn" onClick={() => setEditing(false)}>Отмена</button></div>
              </div>
            )}
          </Card>
          <Card title="Развернуть">
            <form className="form-grid" onSubmit={deploy}>
              <label>Версия<input name="version" required placeholder="1.0.0" /></label>
              <label>Файл или архив .tar.gz<input type="file" name="file" required /></label>
              <div className="row gap" style={{ alignItems: "flex-end" }}><button className="btn btn-primary" disabled={!recipe}>Развернуть в {env}</button></div>
            </form>
          </Card>
          <Card title="Версии на сервере" actions={<><button className="btn btn-sm" onClick={loadRemote}>Обновить</button><button className="btn btn-sm btn-danger" onClick={() => rollback()}>Откат на предыдущую</button></>}>
            {remote ? (
              <ul className="list">{remote.releases.map((r: string) => (
                <li key={r}><span>{r} {r === remote.current && <Badge tone="ok">текущая</Badge>}</span>{r !== remote.current && <button className="btn btn-sm" onClick={() => rollback(r)}>Переключить</button>}</li>
              ))}</ul>
            ) : <Empty>Нажмите «Обновить», чтобы получить список с сервера</Empty>}
          </Card>
          <Card title="Журнал операций">
            {!ov.data?.operations?.length ? <Empty>Операций не было</Empty> : (
              <ul className="list">{ov.data.operations.map((o: any) => (
                <li key={o.id}>
                  <details className="grow"><summary>{fmtDate(o.started_at)} · {o.env} · {o.action} {o.version}{o.previous_version && ` (было ${o.previous_version})`}</summary><pre className="pre">{o.log || "—"}</pre></details>
                  <Badge tone={statusTone(o.status)}>{o.status}</Badge>
                </li>
              ))}</ul>
            )}
          </Card>
        </>
      )}
    </>
  );
}
