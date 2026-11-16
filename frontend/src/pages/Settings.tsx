import { useState } from "react";
import { api, setCsrf } from "../api";
import { Badge, Card, ErrorText, fmtDate, Toggle, useLoad } from "../components/ui";
import { applyTheme, loadTheme, Theme } from "../theme";

const SECRET_LABELS: Record<string, string> = {
  github_token: "GitHub-токен (fine-grained, общий для разрешённых репозиториев)",
  github_webhook_secret: "Секрет GitHub Webhook",
  telegram_bot_token: "Токен Telegram-бота",
  max_bot_token: "Токен бота MAX",
};

export default function Settings() {
  const s = useLoad(() => api("/api/settings"), []);
  const audit = useLoad(() => api<any[]>("/api/audit"), []);
  const [theme, setTheme] = useState<Theme>(loadTheme());
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [secretVals, setSecretVals] = useState<Record<string, string>>({});

  const save = async (values: Record<string, unknown>) => {
    setError(null); setMsg(null);
    try { await api("/api/settings", { method: "PUT", body: { values } }); setMsg("Сохранено"); s.reload(); audit.reload(); } catch (e: any) { setError(e.message); }
  };
  const saveSecret = async (name: string) => {
    setError(null); setMsg(null);
    try {
      await api(`/api/settings/secrets/${name}`, { method: "PUT", body: { value: secretVals[name] } });
      setSecretVals((v) => ({ ...v, [name]: "" }));
      setMsg("Секрет сохранён на сервере");
      s.reload();
    } catch (e: any) { setError(e.message); }
  };
  const test = async () => {
    try { const r = await api("/api/notifications/test", { method: "POST" }); setMsg(`Тест отправлен: ${r.delivered}`); } catch (e: any) { setError(e.message); }
  };
  const logout = async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    setCsrf(null);
    window.location.reload();
  };

  const st = s.data?.settings;
  const channels: string[] = st?.notify_channels ?? [];
  const toggleChannel = (c: string, on: boolean) => save({ notify_channels: on ? [...new Set([...channels, c])] : channels.filter((x) => x !== c) });

  return (
    <>
      <div className="page-head"><div><h1>Настройки</h1><p className="muted">Автоматизация, интеграции, безопасность</p></div><button className="btn" onClick={logout}>Выйти</button></div>
      <ErrorText error={error ?? s.error} />
      {msg && <p className="ok-box small">{msg}</p>}
      <Card title="Оформление">
        <div className="tabs" role="radiogroup" aria-label="Тема">
          {(["system", "light", "dark"] as Theme[]).map((t) => (
            <button key={t} role="radio" aria-checked={theme === t} aria-selected={theme === t} className="btn btn-sm" onClick={() => { setTheme(t); applyTheme(t); }}>
              {{ system: "Как в системе", light: "Светлая", dark: "Тёмная" }[t]}
            </button>
          ))}
        </div>
      </Card>
      {st && (
        <>
          <Card title="Аварийный выключатель" className={st.global_kill_switch ? "danger-zone" : ""}>
            <Toggle danger label="Остановить всю автоматизацию" hint="Автослияние, автопубликация релизов и автоматические деплои всех проектов будут остановлены" checked={st.global_kill_switch} onChange={(v) => save({ global_kill_switch: v })} />
          </Card>
          <Card title="Секреты (хранятся только на сервере, файлы 0600)">
            <ul className="list">
              {Object.entries(SECRET_LABELS).map(([k, label]) => (
                <li key={k}>
                  <div className="grow">{label} <Badge tone={s.data.secrets[k] ? "ok" : "warn"}>{s.data.secrets[k] ? "настроен" : "не задан"}</Badge></div>
                  <div className="row gap" style={{ flex: "1 1 260px" }}>
                    <input type="password" autoComplete="off" placeholder="Новое значение" value={secretVals[k] ?? ""} onChange={(e) => setSecretVals((v) => ({ ...v, [k]: e.target.value }))} aria-label={label} />
                    <button className="btn btn-sm" disabled={!secretVals[k]} onClick={() => saveSecret(k)}>Сохранить</button>
                  </div>
                </li>
              ))}
            </ul>
            <p className="muted small">Значения никогда не возвращаются в браузер и не пишутся в журналы.</p>
          </Card>
          <Card title="GitHub">
            <label>Разрешённые репозитории (по одному в строке; пусто — любые доступные токену)
              <textarea defaultValue={(st.allowed_repos ?? []).join("\n")} onBlur={(e) => save({ allowed_repos: e.target.value.split("\n").map((x) => x.trim()).filter(Boolean) })} style={{ minHeight: 80 }} />
            </label>
          </Card>
          <Card title="Уведомления">
            <Toggle label="Telegram" checked={channels.includes("telegram")} onChange={(v) => toggleChannel("telegram", v)} />
            <Toggle label="MAX" checked={channels.includes("max")} onChange={(v) => toggleChannel("max", v)} />
            <div className="form-grid">
              <label>Telegram chat_id<input defaultValue={st.notify_telegram_chat_id} onBlur={(e) => save({ notify_telegram_chat_id: e.target.value.trim() })} /></label>
              <label>MAX chat_id<input defaultValue={st.notify_max_chat_id} onBlur={(e) => save({ notify_max_chat_id: e.target.value.trim() })} /></label>
            </div>
            <div className="row gap" style={{ marginTop: 10 }}><button className="btn" onClick={test}>Отправить тестовое уведомление</button></div>
          </Card>
          <Card title="SSH и развёртывание">
            <div className="form-grid">
              <label>Исполнитель<select value={st.deploy_executor} onChange={(e) => save({ deploy_executor: e.target.value })}><option value="ssh">SSH к VPS</option><option value="local">Локально (портал на этом VPS)</option></select></label>
              <label>Хост<input defaultValue={st.ssh_host} onBlur={(e) => save({ ssh_host: e.target.value.trim() })} /></label>
              <label>Пользователь<input defaultValue={st.ssh_user} onBlur={(e) => save({ ssh_user: e.target.value.trim() })} /></label>
              <label>Порт<input type="number" defaultValue={st.ssh_port} onBlur={(e) => save({ ssh_port: Number(e.target.value) })} /></label>
            </div>
            <p className="muted small">Приватный ключ и known_hosts задаются на сервере (NEXUS_SSH_KEY, NEXUS_SSH_KNOWN_HOSTS). Ключ: {s.data.server.ssh_key_configured ? "есть" : "нет"}; known_hosts: {s.data.server.known_hosts_configured ? "есть" : "нет"}. Корень: <span className="mono">{s.data.server.deploy_root}</span></p>
          </Card>
        </>
      )}
      <Card title="Журнал действий">
        <div className="table-wrap"><table><thead><tr><th>Время</th><th>Кто</th><th>Действие</th><th>Детали</th></tr></thead><tbody>
          {(audit.data ?? []).slice(0, 100).map((a) => <tr key={a.id}><td className="small">{fmtDate(a.ts)}</td><td>{a.actor}</td><td>{a.action}</td><td className="mono small">{a.detail}</td></tr>)}
        </tbody></table></div>
      </Card>
    </>
  );
}
