import { api } from "../api";
import { Badge, Card, Empty, ErrorText, fmtDate, useLoad } from "../components/ui";

const TONE: Record<string, string> = { info: "info", success: "ok", warning: "warn", error: "err" };

export default function Notifications() {
  const { data, error, reload } = useLoad(() => api<any[]>("/api/notifications"), []);
  const readAll = async () => { await api("/api/notifications/read-all", { method: "POST" }); reload(); };
  return (
    <>
      <div className="page-head">
        <div><h1>Уведомления</h1><p className="muted">Портал, Telegram и MAX</p></div>
        <button className="btn" onClick={readAll}>Отметить все прочитанными</button>
      </div>
      <ErrorText error={error} />
      <Card>
        {!data?.length ? <Empty>Уведомлений нет</Empty> : (
          <ul className="list">{data.map((n) => {
            let delivered: Record<string, boolean> = {};
            try { delivered = JSON.parse(n.delivered); } catch { /* ignore */ }
            return (
              <li key={n.id} style={{ opacity: n.is_read ? 0.7 : 1 }}>
                <div className="grow">
                  <div className="row gap wrap"><Badge tone={TONE[n.level]}>{n.level}</Badge><strong>{n.title}</strong>{!n.is_read && <Badge tone="info">новое</Badge>}</div>
                  {n.body && <div className="small" style={{ whiteSpace: "pre-wrap" }}>{n.body}</div>}
                  <div className="small muted">{fmtDate(n.created_at)} · {Object.entries(delivered).map(([k, v]) => `${k}: ${v ? "✓" : "✗"}`).join(", ")}</div>
                </div>
              </li>
            );
          })}</ul>
        )}
      </Card>
    </>
  );
}
