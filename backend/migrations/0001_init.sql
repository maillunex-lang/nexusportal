-- NEXUS PORTAL: базовая схема
CREATE TABLE owner (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    ip TEXT,
    user_agent TEXT
);
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    project_id INTEGER,
    detail TEXT,
    ip TEXT
);
CREATE INDEX audit_log_project ON audit_log(project_id, id);
CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    template TEXT NOT NULL,
    repo_full_name TEXT,
    default_branch TEXT NOT NULL DEFAULT 'main',
    description TEXT NOT NULL DEFAULT '',
    automation_enabled INTEGER NOT NULL DEFAULT 1,
    auto_merge_enabled INTEGER NOT NULL DEFAULT 0,
    auto_publish_releases INTEGER NOT NULL DEFAULT 0,
    prod_deploy_allowed INTEGER NOT NULL DEFAULT 0,
    required_checks TEXT NOT NULL DEFAULT '[]',
    release_workflow TEXT NOT NULL DEFAULT '',
    release_artifact TEXT NOT NULL DEFAULT '',
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    stage_key TEXT NOT NULL,
    title TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    UNIQUE(project_id, stage_key)
);
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    task_key TEXT NOT NULL,
    title TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT '',
    lane TEXT NOT NULL DEFAULT 'main',
    goal TEXT NOT NULL DEFAULT '',
    context TEXT NOT NULL DEFAULT '',
    gdd_refs TEXT NOT NULL DEFAULT '[]',
    file_scope TEXT NOT NULL DEFAULT '[]',
    depends_on TEXT NOT NULL DEFAULT '[]',
    done_when TEXT NOT NULL DEFAULT '[]',
    branch TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','ready','in_progress','blocked','done')),
    pr_number INTEGER,
    ci_state TEXT NOT NULL DEFAULT '',
    blocked_reason TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_id, task_key)
);
CREATE TABLE webhook_deliveries (
    delivery_id TEXT PRIMARY KEY,
    event TEXT NOT NULL,
    repo TEXT,
    received_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'received',
    error TEXT
);
CREATE TABLE pull_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    repo TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    branch TEXT NOT NULL DEFAULT '',
    base TEXT NOT NULL DEFAULT '',
    head_sha TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'open',
    merged INTEGER NOT NULL DEFAULT 0,
    merge_sha TEXT,
    is_fork INTEGER NOT NULL DEFAULT 0,
    task_key TEXT,
    checks TEXT NOT NULL DEFAULT '{}',
    ci_state TEXT NOT NULL DEFAULT 'pending',
    html_url TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(repo, number)
);
CREATE TABLE commits (
    repo TEXT NOT NULL,
    sha TEXT NOT NULL,
    branch TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (repo, sha)
);
CREATE TABLE merge_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,
    repo TEXT NOT NULL,
    number INTEGER NOT NULL,
    head_sha TEXT NOT NULL,
    decision TEXT NOT NULL,
    reasons TEXT NOT NULL DEFAULT '[]',
    ts TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE deploy_recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    env TEXT NOT NULL CHECK (env IN ('dev','prod')),
    kind TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    script TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE deploy_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    env TEXT NOT NULL,
    action TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '',
    previous_version TEXT NOT NULL DEFAULT '',
    recipe_id INTEGER,
    status TEXT NOT NULL DEFAULT 'running',
    log TEXT NOT NULL DEFAULT '',
    backup_path TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);
CREATE TABLE releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    version_code INTEGER,
    channel TEXT NOT NULL DEFAULT 'release',
    sha TEXT NOT NULL,
    run_id INTEGER,
    artifact_name TEXT NOT NULL DEFAULT '',
    file_name TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    download_url TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    published_at TEXT,
    UNIQUE(project_id, version)
);
CREATE TABLE memory_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('decision','task','error','context','doc')),
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    ref TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX memory_project ON memory_entries(project_id, kind, id);
CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,
    level TEXT NOT NULL DEFAULT 'info',
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    is_read INTEGER NOT NULL DEFAULT 0,
    delivered TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
