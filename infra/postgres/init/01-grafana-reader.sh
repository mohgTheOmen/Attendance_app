#!/bin/sh
set -eu

: "${GRAFANA_DB_PASSWORD:?Set GRAFANA_DB_PASSWORD before initializing PostgreSQL}"
psql -v ON_ERROR_STOP=1 -v reader_password="$GRAFANA_DB_PASSWORD" \
  --host "${POSTGRES_HOST:-/var/run/postgresql}" \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
SELECT format('CREATE ROLE grafana_reader LOGIN PASSWORD %L', :'reader_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_reader') \gexec
ALTER ROLE grafana_reader WITH LOGIN PASSWORD :'reader_password';
GRANT CONNECT ON DATABASE attendance TO grafana_reader;
GRANT USAGE ON SCHEMA public TO grafana_reader;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM grafana_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE attendance IN SCHEMA public REVOKE SELECT ON TABLES FROM grafana_reader;
GRANT SELECT (id, full_name, email, role, is_active) ON users TO grafana_reader;
GRANT SELECT (id, title, starts_at, ends_at) ON events TO grafana_reader;
GRANT SELECT (id, name) ON groups TO grafana_reader;
GRANT SELECT (event_id, group_id) ON event_groups TO grafana_reader;
GRANT SELECT (user_id, group_id) ON group_members TO grafana_reader;
GRANT SELECT (id, event_id, user_id, status, is_late, submitted_at, source)
  ON attendances TO grafana_reader;
SQL
