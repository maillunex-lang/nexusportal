CREATE TABLE IF NOT EXISTS bp_migrations(version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS bp_versions(
 id INTEGER PRIMARY KEY, project TEXT NOT NULL, document TEXT NOT NULL,
 hash TEXT NOT NULL, imported_by TEXT NOT NULL, imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 approved_by TEXT, approved_at TEXT, parent_id INTEGER);
CREATE TABLE IF NOT EXISTS bp_projects(project TEXT PRIMARY KEY, current_version INTEGER REFERENCES bp_versions(id));
CREATE TABLE IF NOT EXISTS bp_tasks(
 project TEXT NOT NULL, task TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'todo',
 executor TEXT NOT NULL DEFAULT '', scopes TEXT, reviewed INTEGER NOT NULL DEFAULT 0,
 review_note TEXT NOT NULL DEFAULT '', pr INTEGER, evidence TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(project,task));
CREATE TABLE IF NOT EXISTS bp_events(
 id INTEGER PRIMARY KEY, project TEXT NOT NULL, task TEXT, version INTEGER,
 actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TRIGGER IF NOT EXISTS bp_document_immutable BEFORE UPDATE OF document,hash,project,parent_id ON bp_versions
BEGIN SELECT RAISE(ABORT,'Blueprint is immutable'); END;
CREATE TRIGGER IF NOT EXISTS bp_approval_immutable BEFORE UPDATE OF approved_by,approved_at ON bp_versions
WHEN OLD.approved_at IS NOT NULL BEGIN SELECT RAISE(ABORT,'Approval is immutable'); END;
CREATE TRIGGER IF NOT EXISTS bp_version_no_delete BEFORE DELETE ON bp_versions
BEGIN SELECT RAISE(ABORT,'Version history is append only'); END;
CREATE TRIGGER IF NOT EXISTS bp_events_no_update BEFORE UPDATE ON bp_events
BEGIN SELECT RAISE(ABORT,'Audit is append only'); END;
CREATE TRIGGER IF NOT EXISTS bp_events_no_delete BEFORE DELETE ON bp_events
BEGIN SELECT RAISE(ABORT,'Audit is append only'); END;
INSERT OR IGNORE INTO bp_migrations VALUES(1);
CREATE TABLE IF NOT EXISTS bp_dispatches(
 id INTEGER PRIMARY KEY, project TEXT NOT NULL, task TEXT NOT NULL,
 version INTEGER NOT NULL, actor TEXT NOT NULL, prompt TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TRIGGER IF NOT EXISTS bp_dispatch_no_update BEFORE UPDATE ON bp_dispatches
BEGIN SELECT RAISE(ABORT,'Dispatch history is append only'); END;
CREATE TRIGGER IF NOT EXISTS bp_dispatch_no_delete BEFORE DELETE ON bp_dispatches
BEGIN SELECT RAISE(ABORT,'Dispatch history is append only'); END;
