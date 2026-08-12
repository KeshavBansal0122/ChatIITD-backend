-- OAuth metadata and invalidation support for user LLM credentials

ALTER TABLE user_llm_credentials
    ADD COLUMN IF NOT EXISTS auth_method TEXT NOT NULL DEFAULT 'manual';

ALTER TABLE user_llm_credentials
    ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS user_llm_credentials_active_idx
    ON user_llm_credentials (user_id)
    WHERE invalidated_at IS NULL;
