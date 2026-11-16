-- NEXUS Smart Context: машинный индекс модулей проекта (docs/context/modules.json)
ALTER TABLE projects ADD COLUMN context_index TEXT NOT NULL DEFAULT '{}'
