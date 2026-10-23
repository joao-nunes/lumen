"""app and auth roles with row-level security

Revision ID: 3d3fd70e14a1
Revises: ac1f730a0012
Create Date: 2026-10-23 17:42:51.827932

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3d3fd70e14a1"
down_revision: str | Sequence[str] | None = "ac1f730a0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Runtime roles. Roles are cluster-wide (shared by the dev and test databases),
# so they are created only if missing and never dropped by a downgrade.
# Login and passwords are infrastructure concerns (docker/postgres/init).
APP_ROLE = "lumen_app"  # user data, always through RLS
AUTH_ROLE = "lumen_auth"  # authentication only

USER_DATA_TABLES = ("checkins", "checkin_scores", "tags", "checkin_tags")


def _create_role_if_missing(role: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS;
            END IF;
        END
        $$
        """
    )


def upgrade() -> None:
    """Upgrade schema."""
    _create_role_if_missing(APP_ROLE)
    _create_role_if_missing(AUTH_ROLE)

    # The user the current transaction acts for, set by the application with
    # set_config('lumen.user_id', ..., true). NULLIF matters: once the setting
    # has existed on a connection, current_setting(..., true) returns '' rather
    # than NULL, and ''::uuid would raise instead of matching no rows.
    op.execute(
        """
        CREATE FUNCTION current_app_user_id() RETURNS uuid
        LANGUAGE sql STABLE
        AS $$ SELECT NULLIF(current_setting('lumen.user_id', true), '')::uuid $$
        """
    )

    # --- privileges: each role gets only what its component needs ------------
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}, {AUTH_ROLE}")
    op.execute(f"GRANT SELECT ON users TO {APP_ROLE}")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON checkins, checkin_scores, checkin_tags "
        f"TO {APP_ROLE}"
    )
    op.execute(f"GRANT SELECT, INSERT ON tags TO {APP_ROLE}")

    op.execute(f"GRANT SELECT, INSERT ON users TO {AUTH_ROLE}")
    op.execute("REVOKE ALL ON SCHEMA auth FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA auth TO {AUTH_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON auth.password_credentials TO {AUTH_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON auth.sessions TO {AUTH_ROLE}")

    # --- row-level security ----------------------------------------------------
    # FORCE also applies policies to the table owner, in case ownership ever
    # moves to a non-superuser role. (Superusers always bypass RLS.)
    # "(SELECT current_app_user_id())" is evaluated once per query, not per row.
    for table, owner_column in [("users", "id")] + [(t, "user_id") for t in USER_DATA_TABLES]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY user_isolation ON {table} TO {APP_ROLE}
            USING ({owner_column} = (SELECT current_app_user_id()))
            WITH CHECK ({owner_column} = (SELECT current_app_user_id()))
            """
        )

    # Login must find a user by email before anyone is "current", and
    # registration creates users: the auth role sees all users (and nothing else).
    op.execute(f"CREATE POLICY auth_service ON users TO {AUTH_ROLE} USING (true) WITH CHECK (true)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY auth_service ON users")
    for table in ("users", *USER_DATA_TABLES):
        op.execute(f"DROP POLICY user_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA auth FROM {AUTH_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA auth FROM {AUTH_ROLE}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}, {AUTH_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}, {AUTH_ROLE}")
    op.execute("DROP FUNCTION current_app_user_id()")
    # Roles are left in place: they are cluster-wide and may hold privileges in
    # other databases (dev and test share a cluster), so DROP ROLE would fail.
