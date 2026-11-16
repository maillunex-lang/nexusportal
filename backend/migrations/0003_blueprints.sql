-- NEXUS Project Blueprint: версии документа архитектора и история задач
CREATE TABLE blueprints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    doc_version TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','superseded','rejected')),
    content TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    source_format TEXT NOT NULL DEFAULT 'nexus-blueprint/1',
    validation TEXT NOT NULL DEFAULT '{}',
    changes TEXT NOT NULL DEFAULT '{}',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    approved_at TEXT,
    UNIQUE(project_id, version)
);
CREATE TABLE blueprint_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    blueprint_version INTEGER,
    task_id TEXT,
    event TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    ts TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX blueprint_events_task ON blueprint_events(project_id, task_id, id)
