BEGIN;

CREATE TABLE IF NOT EXISTS schedule.employee_schedule_assignments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES hr.employees(id),
    schedule_template_id uuid NOT NULL
        REFERENCES schedule.schedule_templates(id),
    rest_day_pattern_id uuid
        REFERENCES schedule.rest_day_patterns(id),
    assignment_type varchar(30) NOT NULL,
    effective_from date NOT NULL,
    effective_to date,
    reason text,
    approved_by uuid REFERENCES identity.users(id),
    approved_at timestamptz,
    status varchar(20) NOT NULL DEFAULT 'DRAFT',
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid,
    row_version integer NOT NULL DEFAULT 1,
    is_active boolean NOT NULL DEFAULT true,
    CONSTRAINT ck_employee_schedule_assignments_effective_dates CHECK (
        effective_to IS NULL OR effective_to >= effective_from
    )
);

CREATE INDEX IF NOT EXISTS ix_employee_schedule_assignments_employee_effective
    ON schedule.employee_schedule_assignments (employee_id, effective_from DESC);

CREATE INDEX IF NOT EXISTS ix_employee_schedule_assignments_template
    ON schedule.employee_schedule_assignments (schedule_template_id);

CREATE INDEX IF NOT EXISTS ix_employee_schedule_assignments_rest_day_pattern
    ON schedule.employee_schedule_assignments (rest_day_pattern_id);

COMMIT;
