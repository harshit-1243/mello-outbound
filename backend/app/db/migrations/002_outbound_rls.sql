-- Row-Level Security for the outbound (Mello Outbound) tables — Postgres / Supabase only.
--
-- Run this AFTER the tables exist (python -m app.db.init_db against your Supabase DATABASE_URL),
-- and after 001_enable_rls.sql. Same model as 001: the backend sets
--     SELECT set_config('app.current_client_id', '<client_id>', true);
-- and these policies read it via current_client_id(). Unset → NULL → no rows (deny by default).

ALTER TABLE campaigns         ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbound_contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE call_attempts     ENABLE ROW LEVEL SECURITY;
ALTER TABLE opt_outs          ENABLE ROW LEVEL SECURITY;

ALTER TABLE campaigns         FORCE ROW LEVEL SECURITY;
ALTER TABLE outbound_contacts FORCE ROW LEVEL SECURITY;
ALTER TABLE call_attempts     FORCE ROW LEVEL SECURITY;
ALTER TABLE opt_outs          FORCE ROW LEVEL SECURITY;

-- All four carry client_id directly (current_client_id() is defined in 001_enable_rls.sql).
CREATE POLICY tenant_isolation ON campaigns         USING (client_id = current_client_id());
CREATE POLICY tenant_isolation ON outbound_contacts USING (client_id = current_client_id());
CREATE POLICY tenant_isolation ON call_attempts     USING (client_id = current_client_id());
CREATE POLICY tenant_isolation ON opt_outs          USING (client_id = current_client_id());
