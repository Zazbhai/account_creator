-- Neon PostgreSQL Database Schema
-- Creates all tables needed for the Account Creator application

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'user',
    expiry_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_balance NUMERIC(10, 2),
    last_capacity INTEGER,
    last_price NUMERIC(10, 2),
    wallet_balance NUMERIC(10, 2) DEFAULT 0.0
);

-- API Settings table (single row configuration)
CREATE TABLE IF NOT EXISTS api_settings (
    id SERIAL PRIMARY KEY,
    base_url TEXT,
    service TEXT,
    operator TEXT,
    country TEXT,
    default_price NUMERIC(10, 2),
    wait_for_otp INTEGER,
    wait_for_second_otp INTEGER
);

-- IMAP Config table (per-user configuration)
CREATE TABLE IF NOT EXISTS imap_config (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    host TEXT,
    port INTEGER,
    email TEXT,
    password TEXT,
    mailbox TEXT,
    api_key TEXT,
    UNIQUE(user_id)
);

-- Margin Fees table (per-user margin configuration)
CREATE TABLE IF NOT EXISTS margin_fees (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    per_account_fee NUMERIC(10, 2) DEFAULT 2.5,
    margin_balance NUMERIC(10, 2) DEFAULT 0.0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id)
);

-- Used UTRs table (payment tracking)
CREATE TABLE IF NOT EXISTS used_utrs (
    utr TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    amount NUMERIC(10, 2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_imap_config_user_id ON imap_config(user_id);
CREATE INDEX IF NOT EXISTS idx_margin_fees_user_id ON margin_fees(user_id);
CREATE INDEX IF NOT EXISTS idx_used_utrs_user_id ON used_utrs(user_id);
