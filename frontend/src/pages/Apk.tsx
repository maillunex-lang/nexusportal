import { api } from "../api";
import { Card, ErrorText, useLoad } from "../components/ui";
import { ReleaseList } from "./Releases";

export default function Apk() {
  const { data, error } = useLoad(() => api<any[]>("/api/releases"), []);
  const apks = (data ?? []).filter((r) => r.file_name.toLowerCase().endsWith(".apk"));
  const latest = new Map<string, any>();
  apks.filter((r) => r.status === "published").forEach((r) => latest.has(r.project_name) || latest.set(r.project_name, r));
  return (
    <>
      <div className="page-head"><div><h1>APK</h1><p className="muted">Подписанные сборки Android, номера версий и ссылки на скачивание</p></div></div>
      <ErrorText error={error} />
      <div className="grid" style={{ marginBottom: 16 }}>
        {[...latest.values()].map((r) => (
          <Card key={r.id} title={r.project_name}>
            <p>Актуальная версия <b>{r.version}</b> (код {r.version_code ?? "—"})</p>
            {r.download_url ? <a className="btn btn-primary" href={r.download_url}>Скачать APK</a> : <p className="muted small">Публичный адрес загрузки не настроен (NEXUS_PUBLIC_DOWNLOAD_BASE)</p>}
          </Card>
        ))}
      </div>
      <Card title="История APK"><ReleaseList rows={apks} /></Card>
    </>
  );
}
