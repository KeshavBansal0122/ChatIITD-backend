-- LLM usage accounting + per-user BYOK credentials

CREATE TABLE IF NOT EXISTS llm_usage (
    id               BIGSERIAL PRIMARY KEY,
    user_id          INTEGER,
    device_fingerprint TEXT,
    provider         TEXT NOT NULL,
    model            TEXT,
    prompt_tokens    INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens     INTEGER NOT NULL DEFAULT 0,
    chat_id          INTEGER,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS llm_usage_user_window_idx
    ON llm_usage (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS llm_usage_device_window_idx
    ON llm_usage (device_fingerprint, created_at DESC);

CREATE TABLE IF NOT EXISTS user_llm_credentials (
    user_id            INTEGER PRIMARY KEY,
    provider           TEXT NOT NULL,
    base_url           TEXT NOT NULL,
    model              TEXT,
    api_key_ciphertext BYTEA NOT NULL,
    api_key_nonce      BYTEA NOT NULL,
    key_fingerprint    TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
