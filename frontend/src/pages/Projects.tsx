import { useState } from "react";
import { api, KIND_LABELS, Project } from "../api";
import { Badge, Card, CopyButton, Empty, ErrorText, PromptBox, Toggle, useLoad } from "../components/ui";

export default function Projects() {
  const { data, error, reload } = useLoad(() => api<Project[]>("/api/projects"), []);
  const [open, setOpen] = useState<number | null>(null);
  return (
    <>
      <div className="page-head">
        <div><h1>Проекты</h1><p className="muted">Игры, Android-приложения, сайты, серверы и другие проекты</p></div>
        <a className="btn btn-primary" href="#/new">+ Новый проект</a>
      </div>
      <ErrorText error={error} />
      {data && !data.length && <Empty>Проектов пока нет.</Empty>}
      {(data ?? []).map((p) => (
        <Card key={p.id} title={<>{p.name} {p.archived && <Badge>Архив</Badge>}</>}
          actions={<><Badge>{KIND_LABELS[p.kind]}</Badge><button className="btn btn-sm" onClick={() => setOpen(open === p.id ? null : p.id)} aria-expanded={open === p.id}>{open === p.id ? "Свернуть" : "Подробнее"}</button></>}>
          <p className="muted small mono">{p.repo_full_name || "без репозитория"} · {p.default_branch} · {p.slug}</p>
          {p.description && <p>{p.description}</p>}
          {open === p.id && <ProjectDetail project={p} onChange={reload} />}
        </Card>
      ))}
    </>
  );
}

function ProjectDetail({ project, onChange }: { project: Project; onChange: () => void }) {
  const [p, setP] = useState(project);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const prompts = useLoad(() => api(`/api/projects/${project.id}/prompts`), [project.id]);
  const [file, setFile] = useState<string | null>(null);

  const save = async (patch: Partial<Project>) => {
    setError(null);
    try {
      const r = await api<Project>(`/api/projects/${p.id}`, { method: "PATCH", body: patch });
      setP(r);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
      onChange();
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <div className="col">
      <h3>Автоматизация</h3>
      <Toggle label="Автоматизация проекта" hint="Аварийный выключатель проекта: при выключении портал не сливает PR и не публикует релизы" checked={p.automation_enabled} onChange={(v) => save({ automation_enabled: v })} danger={!p.automation_enabled} />
      <Toggle label="Автослияние PR после зелёного CI" checked={p.auto_merge_enabled} onChange={(v) => save({ auto_merge_enabled: v })} />
      <Toggle label="Автопубликация релизов после релизного CI" checked={p.auto_publish_releases} onChange={(v) => save({ auto_publish_releases: v })} />
      <Toggle label="Разрешить продакшен-деплой" hint="Отдельное разрешение владельца на окружение prod" checked={p.prod_deploy_allowed} onChange={(v) => save({ prod_deploy_allowed: v })} />
      <div className="form-grid">
        <label>Репозиторий (владелец/имя)<input defaultValue={p.repo_full_name ?? ""} onBlur={(e) => e.target.value !== (p.repo_full_name ?? "") && save({ repo_full_name: e.target.value })} /></label>
        <label>Основная ветка<input defaultValue={p.default_branch} onBlur={(e) => e.target.value !== p.default_branch && save({ default_branch: e.target.value })} /></label>
        <label>Обязательные проверки CI (через запятую)<input defaultValue={p.required_checks.join(", ")} onBlur={(e) => save({ required_checks: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} /></label>
      </div>
      {saved && <p className="ok-box small">Сохранено</p>}
      <ErrorText error={error} />
      <h3>Обучение ИИ</h3>
      <div className="row gap wrap">
        {prompts.data && <CopyButton text={prompts.data.bootstrap} label="Копировать стартовый промпт директора" />}
        {prompts.data && <CopyButton text={prompts.data.handover} label="Контекст для ИИ" />}
      </div>
      {prompts.data && (
        <div className="row gap wrap">
          {Object.keys(prompts.data.files).map((f) => <button key={f} className="btn btn-sm" onClick={() => setFile(f)}>{f}</button>)}
        </div>
      )}
      {file && prompts.data && <PromptBox title={file} text={prompts.data.files[file]} onClose={() => setFile(null)} />}
      <div className="row gap wrap">
        <button className="btn btn-sm btn-danger" onClick={() => save({ archived: !p.archived })}>{p.archived ? "Вернуть из архива" : "В архив"}</button>
      </div>
    </div>
  );
}
