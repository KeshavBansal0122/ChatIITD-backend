-- Student enrollments + course rosters (Classgrid-compatible).
-- Sourced from IITD LDAP (ldapweb.iitd.ac.in), not catalog CSVs.
-- Optional students.hostel overlay from OAuth/hostel CSV.

CREATE TABLE IF NOT EXISTS student_enrollments (
    semester_code   TEXT NOT NULL REFERENCES semesters (code) ON DELETE CASCADE,
    kerberos        VARCHAR(64) NOT NULL,
    course_code     TEXT NOT NULL,
    PRIMARY KEY (semester_code, kerberos, course_code)
);

CREATE INDEX IF NOT EXISTS student_enrollments_kerberos_idx
    ON student_enrollments (semester_code, kerberos);

CREATE INDEX IF NOT EXISTS student_enrollments_course_idx
    ON student_enrollments (semester_code, course_code);

CREATE INDEX IF NOT EXISTS student_enrollments_kerberos_only_idx
    ON student_enrollments (lower(kerberos));

CREATE TABLE IF NOT EXISTS course_rosters (
    semester_code       TEXT NOT NULL REFERENCES semesters (code) ON DELETE CASCADE,
    course_code         TEXT NOT NULL,
    student_kerberos    VARCHAR(64) NOT NULL,
    student_name        TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (semester_code, course_code, student_kerberos)
);

CREATE INDEX IF NOT EXISTS course_rosters_course_idx
    ON course_rosters (semester_code, course_code);

CREATE INDEX IF NOT EXISTS course_rosters_student_kerberos_lower_idx
    ON course_rosters (lower(student_kerberos));

CREATE TABLE IF NOT EXISTS students (
    kerberos    VARCHAR(64) PRIMARY KEY,
    hostel      TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
