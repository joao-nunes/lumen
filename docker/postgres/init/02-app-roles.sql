-- Login credentials for the runtime roles (local development and CI only).
-- Migrations create these roles without LOGIN if they are missing and own all
-- their privileges and policies; this script only makes them able to connect.
-- Idempotent, so it can also be run against an existing database:
--   docker compose exec -T db psql -U lumen -d lumen < docker/postgres/init/02-app-roles.sql
DO $$
DECLARE
    role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['lumen_app', 'lumen_auth'] LOOP
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('CREATE ROLE %I NOSUPERUSER NOBYPASSRLS', role_name);
        END IF;
        -- Development passwords equal the role name; never reuse outside local/CI.
        EXECUTE format('ALTER ROLE %I LOGIN PASSWORD %L', role_name, role_name);
    END LOOP;
END
$$;
