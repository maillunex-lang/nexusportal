import { useState } from "react";
import { api, Project } from "../api";
import { Badge, Card, Empty, ErrorText, fmtDate, fmtSize, ProjectPicker, statusTone, Toggle, useCurrentProject, useLoad } from "../components/ui";

export function ReleaseList({ rows, onRollback }: { rows: any[]; onRollback?: (r: any) => void }) {
  if (!rows.length) return <Empty>Релизов пока нет</Empty>;
  return (
    <div className="table-wrap"><table>
      <thead><tr><th>Версия</th><th>Код</th><th>Файл</th><th>SHA</th><th>Статус</th><th>Опубликован</th><th></th></tr></thead>
      <tbody>{rows.map((r) => (
        <tr key={r.id}>
          <td><b>{r.version}</b>{r.project_name && <div className="small muted">{r.project_name}</div>}</td>
          <td>{r.version_code ?? "—"}</td>
          <td>{r.download_url ? <a href={r.download_url}>{r.file_name}</a> : r.file_name}<div className="small muted">{fmtSize(r.size)}</div></td>
          <td className="mono small">{r.sha.slice(0, 10)}<div title={r.sha256}>sha256 {r.sha256.slice(0, 12)}</div></td>
          <td><Badge tone={statusTone(r.status)}>{r.status}</Badge>{r.error && <div className="small error">{r.error}</div>}</td>
          <td className="small">{fmtDate(r.published_at)}</td>
          <td>{onRollback && r.status === "superseded" && <button className="btn btn-sm" onClick={() => onRollback(r)}>Откатить на эту</button>}</td>
        </tr>
      ))}</tbody>
    </table></div>
  );
}

export default function Releases() {
  const cp = useCurrentProject();
  const p = cp.current;
  const rel = useLoad(() => (p ? api<any[]>(`/api/projects/${p.id}/releases`) : Promise.resolve([])), [p?.id]);
  const [runId, setRunId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const patch = async (body: Partial<Project>) => {
    setError(null);
    try { await api(`/api/projects/${p!.id}`, { method: "PATCH", body }); cp.reload(); } catch (e: any) { setError(e.message); }
  };
  const process = async () => {
    setError(null); setMsg(null);
    try { const r = await api(`/api/projects/${p!.id}/releases/process`, { body: { run_id: Number(runId) } }); setMsg(`Релиз ${r.version}: ${r.status}`); rel.reload(); } catch (e: any) { setError(e.message); }
  };
  const rollback = async (r: any) => {
    setError(null);
    try { await api(`/api/projects/${p!.id}/releases/${encodeURIComponent(r.version)}/rollback`, { method: "POST" }); setMsg(`Актуальная версия: ${r.version}`); rel.reload(); } catch (e: any) { setError(e.message); }
  };

  return (
    <>
      <div className="page-head">
        <div><h1>Релизы</h1><p className="muted">Публикация после успешного релизного CI, история и откат</p></div>
        <ProjectPicker {...cp} />
      </div>
      <ErrorText error={error ?? rel.error} />
      {msg && <p className="ok-box small">{msg}</p>}
      {p && (
        <Card title="Настройки релизов">
          <div className="form-grid">
            <label>Имя релизного workflow<input defaultValue={p.release_workflow} placeholder="Release" onBlur={(e) => e.target.value !== p.release_workflow && patch({ release_workflow: e.target.value })} /></label>
            <label>Имя артефакта<input defaultValue={p.release_artifact} placeholder="release" onBlur={(e) => e.target.value !== p.release_artifact && patch({ release_artifact: e.target.value })} /></label>
          </div>
          <Toggle label="Автоматически публиковать после каждого успешного релизного CI" hint="Без дополнительного подтверждения. Публикуются только сборки канала release с проверенной подписью, SHA-256 и актуальным SHA." checked={p.auto_publish_releases} onChange={(v) => patch({ auto_publish_releases: v })} />
          <p className="muted small">Артефакт должен содержать <span className="mono">release.json</span>, <span className="mono">SHA256SUMS</span> и файл сборки. Тестовые и неподписанные сборки отклоняются.</p>
        </Card>
      )}
      {p && (
        <Card title="Обработать запуск вручную">
          <div className="row gap wrap">
            <input style={{ maxWidth: 220 }} inputMode="numeric" placeholder="ID запуска Actions" value={runId} onChange={(e) => setRunId(e.target.value.replace(/\D/g, ""))} aria-label="ID запуска" />
            <button className="btn btn-primary" onClick={process} disabled={!runId}>Проверить и опубликовать</button>
          </div>
        </Card>
      )}
      <Card title="История версий"><ReleaseList rows={rel.data ?? []} onRollback={rollback} /></Card>
    </>
  );
}
