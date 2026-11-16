import { useState } from "react";
import { api } from "../api";
import { Badge, Card, CopyButton, ErrorText, PromptBox, Toggle, useLoad } from "../components/ui";

type Mode = "existing" | "new" | "none";
const STEPS = ["Тип", "Репозиторий", "Анкета", "Предпросмотр", "Готово"];
const KIND_HINTS: Record<string, string> = {
  game: "Godot и другие движки, релизы для игроков",
  android: "Gradle, подписанные APK",
  web: "Сайты и веб-приложения",
  server: "API, сервисы, боты",
  other: "Любой другой софт",
};

export default function NewProject() {
  const opts = useLoad(() => api("/api/wizard/options"), []);
  const [step, setStep] = useState(0);
  const [mode, setMode] = useState<Mode>("existing");
  const [priv, setPriv] = useState(true);
  const [params, setParams] = useState<Record<string, string>>({ kind: "game", template: "", default_branch: "main" });
  const [analysis, setAnalysis] = useState<any>(null);
  const [preview, setPreview] = useState<any>(null);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string) => setParams((p) => ({ ...p, [k]: v }));

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try { await fn(); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };

  const analyze = () => run(async () => {
    const r = await api("/api/wizard/analyze", { body: { repo_full_name: params.repo_full_name } });
    setAnalysis(r);
    setParams((p) => ({
      ...p, default_branch: r.default_branch, kind: r.analysis.recommended_kind, template: r.analysis.recommended_template,
      description: p.description || r.description,
    }));
  });

  const doPreview = () => run(async () => {
    const body = { params: mode === "none" ? { ...params, repo_full_name: "" } : params, create_repo: mode === "new", private: priv };
    setPreview(await api("/api/wizard/preview", { body }));
    setStep(3);
  });

  const apply = () => run(async () => {
    const body = { params: mode === "none" ? { ...params, repo_full_name: "" } : params, digest: preview?.digest ?? "", create_repo: mode === "new", private: priv };
    setResult(await api("/api/wizard/apply", { body }));
    setStep(4);
  });

  const kinds: Record<string, string> = opts.data?.kinds ?? {};
  const templates: Record<string, string> = opts.data?.templates ?? {};

  return (
    <>
      <div className="page-head"><div><h1>Новый проект</h1><p className="muted">Мастер создания или подключения проекта</p></div></div>
      <div className="steps" aria-label="Шаги мастера">{STEPS.map((s, i) => <span key={s} className={i === step ? "on" : ""}>{i + 1}. {s}</span>)}</div>
      <ErrorText error={error ?? opts.error} />

      {step === 0 && (
        <Card title="Что создаём?">
          <div className="choice-grid">
            {Object.entries(kinds).map(([k, label]) => (
              <button key={k} className="choice" aria-pressed={params.kind === k} onClick={() => setParams((p) => ({ ...p, kind: k, template: opts.data.kind_default_template[k] }))}>
                <strong>{label}</strong><br /><span className="muted small">{KIND_HINTS[k]}</span>
              </button>
            ))}
          </div>
          <div className="row gap" style={{ marginTop: 14 }}><button className="btn btn-primary" onClick={() => setStep(1)}>Далее</button></div>
        </Card>
      )}

      {step === 1 && (
        <Card title="Репозиторий GitHub">
          <div className="choice-grid">
            <button className="choice" aria-pressed={mode === "existing"} onClick={() => setMode("existing")}><strong>Подключить существующий</strong><br /><span className="muted small">Анализ структуры, существующие файлы не изменяются</span></button>
            <button className="choice" aria-pressed={mode === "new"} onClick={() => setMode("new")}><strong>Создать новый</strong><br /><span className="muted small">Через GitHub API общим токеном</span></button>
            <button className="choice" aria-pressed={mode === "none"} onClick={() => setMode("none")}><strong>Без GitHub</strong><br /><span className="muted small">Подключить позже</span></button>
          </div>
          {mode !== "none" && (
            <div className="col" style={{ marginTop: 14 }}>
              <label>Репозиторий (владелец/имя)<input placeholder="owner/my-game" value={params.repo_full_name ?? ""} onChange={(e) => set("repo_full_name", e.target.value.trim())} /></label>
              {mode === "existing" && <div><button className="btn" onClick={analyze} disabled={busy || !params.repo_full_name}>{busy ? "Анализ…" : "Проанализировать"}</button></div>}
              {mode === "new" && <Toggle label="Приватный репозиторий" checked={priv} onChange={setPriv} />}
              {analysis && (
                <div className="ok-box small">
                  Файлов: {analysis.analysis.files_total}. Стек: {analysis.analysis.stack.join(", ") || "не определён"}.
                  Рекомендуемый шаблон: <b>{templates[analysis.analysis.recommended_template]}</b>.
                  {analysis.analysis.existing_portal_files.length > 0 && <> Уже есть: {analysis.analysis.existing_portal_files.join(", ")}.</>}
                </div>
              )}
            </div>
          )}
          <div className="row gap" style={{ marginTop: 14 }}>
            <button className="btn" onClick={() => setStep(0)}>Назад</button>
            <button className="btn btn-primary" onClick={() => setStep(2)} disabled={mode !== "none" && !params.repo_full_name}>Далее</button>
          </div>
        </Card>
      )}

      {step === 2 && (
        <Card title="Анкета проекта">
          <p className="muted small">Ответы попадут в черновик GDD и стартовый промпт директора. GDD окончательно готовит внешний ИИ-директор.</p>
          <div className="form-grid">
            <label>Название<input value={params.name ?? ""} onChange={(e) => set("name", e.target.value)} required /></label>
            <label>Идентификатор (латиница)<input value={params.slug ?? ""} placeholder="my-game" onChange={(e) => set("slug", e.target.value.toLowerCase())} /></label>
            <label>Шаблон<select value={params.template} onChange={(e) => set("template", e.target.value)}>{Object.entries(templates).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            <label>Тип<select value={params.kind} onChange={(e) => set("kind", e.target.value)}>{Object.entries(kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          </div>
          <div className="col" style={{ marginTop: 12 }}>
            <label>Описание<textarea value={params.description ?? ""} onChange={(e) => set("description", e.target.value)} /></label>
            <label>Цели проекта<textarea value={params.goals ?? ""} onChange={(e) => set("goals", e.target.value)} placeholder="Чего должен достичь проект?" /></label>
            <div className="form-grid">
              <label>Аудитория<input value={params.audience ?? ""} onChange={(e) => set("audience", e.target.value)} /></label>
              <label>Платформы<input value={params.platforms ?? ""} onChange={(e) => set("platforms", e.target.value)} placeholder="Android, Web…" /></label>
              <label>Технологии<input value={params.stack ?? ""} onChange={(e) => set("stack", e.target.value)} /></label>
            </div>
          </div>
          <div className="row gap" style={{ marginTop: 14 }}>
            <button className="btn" onClick={() => setStep(1)}>Назад</button>
            <button className="btn btn-primary" onClick={doPreview} disabled={busy || !params.name || !params.slug}>{busy ? "Подготовка…" : "Предпросмотр изменений"}</button>
          </div>
        </Card>
      )}

      {step === 3 && preview && (
        <Card title="Предпросмотр изменений">
          <p className="muted small">
            {mode === "none" ? "Файлы будут доступны для копирования; в GitHub ничего не записывается." :
              "Портал создаст отдельную ветку и Pull Request только с отсутствующими файлами. Существующие файлы не перезаписываются."}
          </p>
          {preview.changes.map((c: any) => (
            <details key={c.path} className="change">
              <summary><Badge tone={c.action === "create" ? "ok" : "neutral"}>{c.action === "create" ? "Создать" : "Существует — пропуск"}</Badge> <span className="mono">{c.path}</span></summary>
              {c.diff ? <pre className="pre">{c.diff}</pre> : <pre className="pre">{c.content}</pre>}
            </details>
          ))}
          <div className="row gap wrap" style={{ marginTop: 14 }}>
            <button className="btn" onClick={() => setStep(2)}>Назад</button>
            <button className="btn btn-primary" onClick={apply} disabled={busy}>{busy ? "Запись…" : mode === "none" ? "Создать проект" : "Подтвердить и записать"}</button>
          </div>
        </Card>
      )}

      {step === 4 && result && (
        <Card title="Проект создан">
          {result.pull_request && <p className="ok-box">Открыт PR: <a href={result.pull_request.html_url} target="_blank" rel="noreferrer">#{result.pull_request.number}</a>. Создано файлов: {result.written.length}.</p>}
          {result.skipped?.length > 0 && <p className="muted small">Пропущены существующие: {result.skipped.join(", ")}</p>}
          <p>Скопируйте стартовый обучающий промпт и вставьте его в ChatGPT или Claude — это ваш ИИ-директор.</p>
          <div className="row gap wrap"><CopyButton text={result.bootstrap_prompt} label="Копировать промпт директора" /><a className="btn" href="#/roadmap">К дорожной карте</a></div>
          <PromptBox title="Стартовый промпт ИИ-директора" text={result.bootstrap_prompt} />
        </Card>
      )}
    </>
  );
}
