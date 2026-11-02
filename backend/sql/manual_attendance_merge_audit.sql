-- Manual PostgreSQL DDL equivalent of Alembic revision c4d5e6f7a8b9.
-- This database has no Alembic version table, so this script deliberately
-- creates only the merge tables and does not create or stamp migration state.
BEGIN;

DO $$
BEGIN
    IF to_regclass('attendance.attendance_records') IS NULL
       OR to_regclass('hr.employees') IS NULL
       OR to_regclass('schedule.schedule_templates') IS NULL
       OR to_regclass('identity.users') IS NULL THEN
        RAISE EXCEPTION 'Required application tables are missing; verify the target database';
    END IF;

    IF to_regclass('attendance.attendance_merges') IS NOT NULL
       OR to_regclass('attendance.attendance_merge_sources') IS NOT NULL THEN
        RAISE EXCEPTION 'One or both attendance merge tables already exist; inspect them before proceeding';
    END IF;
END
$$;

CREATE TABLE attendance.attendance_merges (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    canonical_attendance_id UUID NOT NULL,
    employee_id UUID NOT NULL,
    work_date DATE NOT NULL,
    schedule_template_id UUID NOT NULL,
    canonical_clock_in_at TIMESTAMP WITH TIME ZONE NOT NULL,
    canonical_clock_out_at TIMESTAMP WITH TIME ZONE NOT NULL,
    calculation_snapshot JSONB NOT NULL,
    merged_by UUID,
    merged_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    reason TEXT NOT NULL,
    CONSTRAINT pk_attendance_merges PRIMARY KEY (id),
    CONSTRAINT fk_attendance_merges_canonical
        FOREIGN KEY (canonical_attendance_id)
        REFERENCES attendance.attendance_records (id) ON DELETE RESTRICT,
    CONSTRAINT fk_attendance_merges_employee
        FOREIGN KEY (employee_id)
        REFERENCES hr.employees (id) ON DELETE RESTRICT,
    CONSTRAINT fk_attendance_merges_schedule_template
        FOREIGN KEY (schedule_template_id)
        REFERENCES schedule.schedule_templates (id) ON DELETE RESTRICT,
    CONSTRAINT fk_attendance_merges_merged_by
        FOREIGN KEY (merged_by)
        REFERENCES identity.users (id) ON DELETE SET NULL,
    CONSTRAINT uq_attendance_merges_canonical UNIQUE (canonical_attendance_id),
    CONSTRAINT uq_attendance_merges_employee_date UNIQUE (employee_id, work_date)
);

CREATE TABLE attendance.attendance_merge_sources (
    merge_id UUID NOT NULL,
    source_attendance_id UUID NOT NULL,
    source_snapshot JSONB NOT NULL,
    CONSTRAINT pk_attendance_merge_sources
        PRIMARY KEY (merge_id, source_attendance_id),
    CONSTRAINT fk_attendance_merge_sources_merge
        FOREIGN KEY (merge_id)
        REFERENCES attendance.attendance_merges (id) ON DELETE RESTRICT,
    CONSTRAINT fk_attendance_merge_sources_source
        FOREIGN KEY (source_attendance_id)
        REFERENCES attendance.attendance_records (id) ON DELETE RESTRICT,
    CONSTRAINT uq_attendance_merge_sources_source UNIQUE (source_attendance_id)
);

COMMIT;
