-- Classgrid-compatible catalog schema (courses + instructors).
-- Instructors live inside catalog_courses.course_data JSONB
-- (fields: instructor, instructorEmail, instructors[{name,email}]).
-- Room allotments / enrollments / rosters intentionally omitted.

CREATE TABLE IF NOT EXISTS semesters (
    code                TEXT PRIMARY KEY,
    label               TEXT NOT NULL,
    classes_start       DATE NOT NULL,
    last_teaching_day   DATE NOT NULL,
    is_active           BOOLEAN NOT NULL DEFAULT false,
    academic_calendar   JSONB NOT NULL DEFAULT '{}'::jsonb,
    catalog_etag        TEXT,
    catalog_updated_at  TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT semesters_academic_calendar_is_object
        CHECK (jsonb_typeof(academic_calendar) = 'object')
);

-- Only one semester may be active at a time.
CREATE UNIQUE INDEX IF NOT EXISTS semesters_one_active
    ON semesters (is_active)
    WHERE is_active = true;

CREATE TABLE IF NOT EXISTS catalog_courses (
    semester_code   TEXT NOT NULL REFERENCES semesters (code) ON DELETE CASCADE,
    course_code     TEXT NOT NULL,
    course_data     JSONB NOT NULL,
    PRIMARY KEY (semester_code, course_code),

    CONSTRAINT catalog_courses_data_is_object
        CHECK (jsonb_typeof(course_data) = 'object')
);

CREATE INDEX IF NOT EXISTS catalog_courses_semester_idx
    ON catalog_courses (semester_code);

CREATE INDEX IF NOT EXISTS catalog_courses_code_idx
    ON catalog_courses (course_code);

-- Speed up instructor search across catalog history.
CREATE INDEX IF NOT EXISTS catalog_courses_instructor_email_idx
    ON catalog_courses (lower(course_data->>'instructorEmail'))
    WHERE course_data->>'instructorEmail' IS NOT NULL
      AND course_data->>'instructorEmail' <> '';

-- GIN index for querying instructors[] JSON array (name/email lookups).
CREATE INDEX IF NOT EXISTS catalog_courses_instructors_gin_idx
    ON catalog_courses USING GIN ((course_data->'instructors'));
