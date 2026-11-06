-- Manual PostgreSQL equivalent of Alembic revision f4a6b8c0d2e4.
-- REVIEW ONLY until a backup, baseline review, and coordinated outage are approved.
-- This applies only the approval-routing revision, not earlier migrations.
-- Stop ALL API, worker, scheduler, and integration writers before execution.
-- After commit, start only the matching new application version.
-- Run with psql ON_ERROR_STOP=1. No Alembic state is created or stamped.
-- Existing requests retain LEGACY routing; no org-unit approvers are assigned here.
BEGIN;

SET LOCAL lock_timeout = '10s';

DO $$
DECLARE
    required_table TEXT;
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'alembic_version'
    ) THEN
        RAISE EXCEPTION 'Alembic tracking exists; use a reviewed Alembic upgrade instead';
    END IF;

    FOREACH required_table IN ARRAY ARRAY[
        'core.companies',
        'core.org_units',
        'hr.employees',
        'identity.users',
        'leave_mgmt.leave_applications',
        'attendance.overtime_applications',
        'attendance.official_business_requests',
        'attendance.correction_requests',
        'schedule.emergency_schedule_requests',
        'schedule.schedule_upload_batches',
        'schedule.schedule_upload_batch_rows',
        'attendance.attendance_records',
        'attendance.attendance_merges',
        'attendance.attendance_merge_sources'
    ] LOOP
        IF to_regclass(required_table) IS NULL THEN
            RAISE EXCEPTION 'Required table % is missing; reconcile the existing baseline first', required_table;
        END IF;
    END LOOP;

    IF to_regclass('core.approval_routes') IS NOT NULL
       OR EXISTS (
           SELECT 1
           FROM information_schema.columns
           WHERE table_schema = 'schedule'
             AND table_name = 'schedule_upload_batch_rows'
             AND column_name = 'company_id'
       ) THEN
        RAISE EXCEPTION 'Approval routing is already installed or partially applied; inspect before proceeding';
    END IF;
END
$$;

-- Prevent source rows changing during the legacy backfill. This does not
-- replace stopping old writers: they must remain stopped after commit.
LOCK TABLE
    leave_mgmt.leave_applications,
    attendance.overtime_applications,
    attendance.official_business_requests,
    attendance.correction_requests,
    schedule.emergency_schedule_requests,
    schedule.schedule_upload_batches,
    schedule.schedule_upload_batch_rows,
    attendance.attendance_records
IN SHARE ROW EXCLUSIVE MODE;

ALTER TABLE schedule.schedule_upload_batch_rows
    ADD COLUMN company_id UUID REFERENCES core.companies (id);

CREATE TABLE core.approval_routes (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id UUID NOT NULL,
    routing_mode VARCHAR(20) NOT NULL,
    employee_id UUID,
    source_org_unit_id UUID,
    approver_org_unit_id UUID,
    approver_employee_id UUID,
    assigned_by UUID,
    routing_error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    is_current BOOLEAN DEFAULT true NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_approval_routes_mode
        CHECK (routing_mode IN ('LEGACY', 'ORG_UNIT', 'UNRESOLVED')),
    CONSTRAINT ck_approval_routes_approver
        CHECK (
            (routing_mode = 'ORG_UNIT' AND approver_employee_id IS NOT NULL)
            OR (routing_mode IN ('LEGACY', 'UNRESOLVED') AND approver_employee_id IS NULL)
        ),
    CONSTRAINT ck_approval_routes_unresolved
        CHECK (
            routing_mode <> 'UNRESOLVED'
            OR (employee_id IS NOT NULL AND routing_error IS NOT NULL)
        ),
    FOREIGN KEY (employee_id) REFERENCES hr.employees (id),
    FOREIGN KEY (source_org_unit_id) REFERENCES core.org_units (id),
    FOREIGN KEY (approver_org_unit_id) REFERENCES core.org_units (id),
    FOREIGN KEY (approver_employee_id) REFERENCES hr.employees (id),
    FOREIGN KEY (assigned_by) REFERENCES identity.users (id)
);

CREATE UNIQUE INDEX uq_approval_routes_current
    ON core.approval_routes (resource_type, resource_id)
    WHERE is_current;

CREATE INDEX ix_approval_routes_approver
    ON core.approval_routes (approver_employee_id, resource_type)
    WHERE is_current AND routing_mode = 'ORG_UNIT';

INSERT INTO core.approval_routes (resource_type, resource_id, routing_mode)
SELECT 'leave_application', id, 'LEGACY'
FROM leave_mgmt.leave_applications
WHERE status = 'PENDING' AND is_active;

INSERT INTO core.approval_routes (resource_type, resource_id, routing_mode)
SELECT 'overtime_application', id, 'LEGACY'
FROM attendance.overtime_applications
WHERE status = 'PENDING' AND is_active;

INSERT INTO core.approval_routes (resource_type, resource_id, routing_mode)
SELECT 'official_business_request', id, 'LEGACY'
FROM attendance.official_business_requests
WHERE status = 'PENDING' AND is_active;

INSERT INTO core.approval_routes (resource_type, resource_id, routing_mode)
SELECT 'attendance_correction', id, 'LEGACY'
FROM attendance.correction_requests
WHERE status = 'PENDING';

INSERT INTO core.approval_routes (resource_type, resource_id, routing_mode)
SELECT 'emergency_schedule_request', id, 'LEGACY'
FROM schedule.emergency_schedule_requests
WHERE status = 'PENDING_APPROVAL';

INSERT INTO core.approval_routes (resource_type, resource_id, routing_mode)
SELECT 'schedule_upload_batch', id, 'LEGACY'
FROM schedule.schedule_upload_batches;

INSERT INTO core.approval_routes (resource_type, resource_id, routing_mode)
SELECT 'invalid_attendance', id, 'LEGACY'
FROM attendance.attendance_records
WHERE record_status = 'INVALID';

COMMIT;

SELECT resource_type, COUNT(*) AS legacy_routes
FROM core.approval_routes
WHERE routing_mode = 'LEGACY'
GROUP BY resource_type
ORDER BY resource_type;
