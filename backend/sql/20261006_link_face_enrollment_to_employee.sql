BEGIN;

DO $$
DECLARE
    user_fk_name text;
BEGIN
    SELECT constraint_row.conname
    INTO user_fk_name
    FROM pg_constraint AS constraint_row
    JOIN pg_attribute AS column_info
      ON column_info.attrelid = constraint_row.conrelid
     AND column_info.attnum = ANY (constraint_row.conkey)
    WHERE constraint_row.conrelid = 'biometric.face_enrollment_data'::regclass
      AND constraint_row.contype = 'f'
      AND constraint_row.confrelid = 'core.users'::regclass
      AND column_info.attname = 'user_id'
    LIMIT 1;

    IF user_fk_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE biometric.face_enrollment_data DROP CONSTRAINT %I',
            user_fk_name
        );
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'biometric'
          AND table_name = 'face_enrollment_data'
          AND column_name = 'user_id'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'biometric'
          AND table_name = 'face_enrollment_data'
          AND column_name = 'employee_id'
    ) THEN
        ALTER TABLE biometric.face_enrollment_data RENAME COLUMN user_id TO employee_id;
    END IF;
END
$$;

UPDATE biometric.face_enrollment_data AS enrollment
SET employee_id = employee.id
FROM core.users AS account
JOIN hr.employees AS employee
  ON employee.employee_no = account.employee_code
WHERE enrollment.employee_id = account.id
  AND enrollment.employee_id <> employee.id;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM biometric.face_enrollment_data AS enrollment
        LEFT JOIN hr.employees AS employee ON employee.id = enrollment.employee_id
        WHERE employee.id IS NULL
    ) THEN
        RAISE EXCEPTION 'Cannot link face enrollment rows to employee profiles: an enrollment has no matching employee.';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'face_enrollment_data_employee_id_fkey'
          AND conrelid = 'biometric.face_enrollment_data'::regclass
    ) THEN
        ALTER TABLE biometric.face_enrollment_data
            ADD CONSTRAINT face_enrollment_data_employee_id_fkey
            FOREIGN KEY (employee_id)
            REFERENCES hr.employees(id)
            ON DELETE CASCADE;
    END IF;
END
$$;

COMMIT;
