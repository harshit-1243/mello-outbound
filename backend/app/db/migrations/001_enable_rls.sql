-- Row-Level Security for multi-tenant isolation (Postgres / Supabase only).
--
-- Run this AFTER the tables are created (python -m app.db.init_db against your Supabase
-- DATABASE_URL). The booking engine already filters every query by client_id in application code;
-- RLS is defense-in-depth so a bug or a direct query can never cross tenants.
--
-- Enforcement model: the backend sets a per-transaction GUC before running tenant queries:
--     SELECT set_config('app.current_client_id', '<client_id>', true);
-- Policies below read that value. Unset → NULL → no rows (deny by default).
-- (Wiring set_config into the SQLAlchemy session is an M6 hardening task. The Next.js dashboard
--  connects through Supabase Auth and is governed by separate auth.uid()/JWT policies.)

ALTER TABLE clients       ENABLE ROW LEVEL SECURITY;
ALTER TABLE facilities    ENABLE ROW LEVEL SECURITY;
ALTER TABLE sports        ENABLE ROW LEVEL SECURITY;
ALTER TABLE courts        ENABLE ROW LEVEL SECURITY;
ALTER TABLE sections      ENABLE ROW LEVEL SECURITY;
ALTER TABLE offerings     ENABLE ROW LEVEL SECURITY;
ALTER TABLE slots         ENABLE ROW LEVEL SECURITY;
ALTER TABLE bookings      ENABLE ROW LEVEL SECURITY;
ALTER TABLE members       ENABLE ROW LEVEL SECURITY;
ALTER TABLE groups        ENABLE ROW LEVEL SECURITY;
ALTER TABLE group_members ENABLE ROW LEVEL SECURITY;

-- Force RLS even for the table owner the backend connects as.
ALTER TABLE clients       FORCE ROW LEVEL SECURITY;
ALTER TABLE facilities    FORCE ROW LEVEL SECURITY;
ALTER TABLE sports        FORCE ROW LEVEL SECURITY;
ALTER TABLE courts        FORCE ROW LEVEL SECURITY;
ALTER TABLE sections      FORCE ROW LEVEL SECURITY;
ALTER TABLE offerings     FORCE ROW LEVEL SECURITY;
ALTER TABLE slots         FORCE ROW LEVEL SECURITY;
ALTER TABLE bookings      FORCE ROW LEVEL SECURITY;
ALTER TABLE members       FORCE ROW LEVEL SECURITY;
ALTER TABLE groups        FORCE ROW LEVEL SECURITY;
ALTER TABLE group_members FORCE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION current_client_id() RETURNS integer
  LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.current_client_id', true), '')::integer
$$;

-- clients: the tenant's own row (keyed by id).
CREATE POLICY tenant_isolation ON clients
  USING (id = current_client_id());

-- Tables carrying client_id directly.
CREATE POLICY tenant_isolation ON facilities USING (client_id = current_client_id());
CREATE POLICY tenant_isolation ON sports     USING (client_id = current_client_id());
CREATE POLICY tenant_isolation ON courts     USING (client_id = current_client_id());
CREATE POLICY tenant_isolation ON sections   USING (client_id = current_client_id());
CREATE POLICY tenant_isolation ON offerings  USING (client_id = current_client_id());
CREATE POLICY tenant_isolation ON slots      USING (client_id = current_client_id());
CREATE POLICY tenant_isolation ON bookings   USING (client_id = current_client_id());
CREATE POLICY tenant_isolation ON members    USING (client_id = current_client_id());
CREATE POLICY tenant_isolation ON groups     USING (client_id = current_client_id());

-- group_members: isolate via its parent group.
CREATE POLICY tenant_isolation ON group_members
  USING (EXISTS (
    SELECT 1 FROM groups g
    WHERE g.id = group_members.group_id AND g.client_id = current_client_id()
  ));
