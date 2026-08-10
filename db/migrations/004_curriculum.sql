-- Curriculum / programme structures (legacy ≤2024 entry vs 2025+ entry)
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS programme (
    code            TEXT NOT NULL,
    generation      TEXT NOT NULL CHECK (generation IN ('legacy', '2025')),
    name            TEXT,
    degree_type     TEXT,
    department      TEXT,
    dual            BOOLEAN NOT NULL DEFAULT FALSE,
    source_url      TEXT,
    raw             JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (code, generation)
);

CREATE TABLE IF NOT EXISTS programme_credit_req (
    id              SERIAL PRIMARY KEY,
    programme_code  TEXT NOT NULL,
    generation      TEXT NOT NULL,
    category        TEXT NOT NULL,
    label           TEXT,
    credits_or_units DOUBLE PRECISION,
    kind            TEXT NOT NULL DEFAULT 'graded'
                    CHECK (kind IN ('graded', 'ngu')),
    UNIQUE (programme_code, generation, category, kind),
    FOREIGN KEY (programme_code, generation)
        REFERENCES programme (code, generation) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS programme_basket (
    id              SERIAL PRIMARY KEY,
    programme_code  TEXT NOT NULL,
    generation      TEXT NOT NULL,
    basket_id       TEXT NOT NULL,
    name            TEXT,
    min_credits     DOUBLE PRECISION,
    min_tracks      INTEGER,
    rules_text      TEXT,
    UNIQUE (programme_code, generation, basket_id),
    FOREIGN KEY (programme_code, generation)
        REFERENCES programme (code, generation) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS programme_course (
    id              SERIAL PRIMARY KEY,
    programme_code  TEXT NOT NULL,
    generation      TEXT NOT NULL,
    course_code     TEXT NOT NULL,
    category        TEXT NOT NULL,
    basket_id       TEXT,
    is_core         BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (programme_code, generation, course_code, category, basket_id),
    FOREIGN KEY (programme_code, generation)
        REFERENCES programme (code, generation) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_programme_course_code
    ON programme_course (course_code);

CREATE TABLE IF NOT EXISTS programme_semester (
    programme_code  TEXT NOT NULL,
    generation      TEXT NOT NULL,
    semester        INTEGER NOT NULL,
    entries         JSONB NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (programme_code, generation, semester),
    FOREIGN KEY (programme_code, generation)
        REFERENCES programme (code, generation) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS programme_outcome (
    id              SERIAL PRIMARY KEY,
    programme_code  TEXT NOT NULL,
    generation      TEXT NOT NULL,
    outcome_id      TEXT NOT NULL,
    text            TEXT NOT NULL,
    UNIQUE (programme_code, generation, outcome_id),
    FOREIGN KEY (programme_code, generation)
        REFERENCES programme (code, generation) ON DELETE CASCADE
);

-- Extend course catalogue for dual-generation support
ALTER TABLE course ADD COLUMN IF NOT EXISTS generation TEXT DEFAULT 'legacy';
ALTER TABLE course ADD COLUMN IF NOT EXISTS academic_unit TEXT;
ALTER TABLE course ADD COLUMN IF NOT EXISTS learning_outcomes JSONB;
ALTER TABLE course ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE course ADD COLUMN IF NOT EXISTS source_url TEXT;

CREATE INDEX IF NOT EXISTS idx_course_generation ON course (generation);
