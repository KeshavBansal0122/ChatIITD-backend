-- Allow users to keep saved LLM credentials while temporarily falling back
-- to the shared provider.

ALTER TABLE user_llm_credentials
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE;

DROP INDEX IF EXISTS user_llm_credentials_active_idx;

CREATE INDEX IF NOT EXISTS user_llm_credentials_active_idx
    ON user_llm_credentials (user_id)
    WHERE invalidated_at IS NULL AND enabled = TRUE;
