-- Optimized Database Indexes for Neon PostgreSQL
-- These indexes will significantly improve query performance

-- Drop existing indexes if they exist (to recreate optimized versions)
DROP INDEX IF EXISTS idx_users_username;
DROP INDEX IF EXISTS idx_imap_config_user_id;
DROP INDEX IF EXISTS idx_margin_fees_user_id;
DROP INDEX IF EXISTS idx_used_utrs_user_id;
DROP INDEX IF EXISTS idx_used_utrs_created_at;

-- Users table indexes
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_expiry_date ON users(expiry_date) WHERE expiry_date IS NOT NULL;

-- IMAP Config indexes (for per-user lookups)
CREATE UNIQUE INDEX IF NOT EXISTS idx_imap_config_user_id ON imap_config(user_id);

-- Margin Fees indexes (for per-user lookups)
CREATE UNIQUE INDEX IF NOT EXISTS idx_margin_fees_user_id ON margin_fees(user_id);
CREATE INDEX IF NOT EXISTS idx_margin_fees_updated_at ON margin_fees(updated_at);

-- Used UTRs indexes (for payment tracking)
CREATE INDEX IF NOT EXISTS idx_used_utrs_user_id ON used_utrs(user_id);
CREATE INDEX IF NOT EXISTS idx_used_utrs_created_at ON used_utrs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_used_utrs_user_created ON used_utrs(user_id, created_at DESC);

-- API Settings - no index needed (single row table, always full scan)

-- Analyze tables to update statistics for query planner
ANALYZE users;
ANALYZE imap_config;
ANALYZE margin_fees;
ANALYZE used_utrs;
ANALYZE api_settings;
