-- Manual statutory bracket replacement seed; this is not a schema migration.
-- Use only in a development/test database and enter values from official sources.
-- This script replaces brackets for DRAFT schedules only. ACTIVE and RETIRED
-- schedule brackets are never modified.
--
-- Before running:
-- 1. Apply all statutory schedule migrations.
-- 2. Create the target DRAFT schedule headers in the application.
-- 3. Copy their IDs with:
--    SELECT id, program_code, schedule_name, effective_from
--    FROM payroll.statutory_contribution_schedules WHERE status = 'DRAFT';
--    SELECT id, schedule_name, effective_from
--    FROM payroll.withholding_tax_schedules WHERE status = 'DRAFT';
-- 4. Insert every official bracket row into the corresponding temp seed table
--    below. Include a complete bracket set for every DRAFT schedule. Values
--    must be provided for SSS, PHILHEALTH, PAGIBIG, and withholding tax.
-- 5. Confirm official effective dates, sources, bracket ranges, and rates.
--
-- The preflight aborts before any DELETE unless every DRAFT schedule has a
-- complete, valid replacement set and all four program types are represented.

BEGIN;

CREATE TEMP TABLE statutory_contribution_bracket_seed (
    schedule_id uuid NOT NULL,
    bracket_number integer NOT NULL,
    compensation_min numeric(14, 2) NOT NULL,
    compensation_max numeric(14, 2),
    contribution_base numeric(14, 2) NOT NULL,
    employee_rate numeric(8, 6) NOT NULL,
    employer_rate numeric(8, 6) NOT NULL,
    employee_fixed_amount numeric(14, 2) NOT NULL,
    employer_fixed_amount numeric(14, 2) NOT NULL,
    employer_additional_fixed_amount numeric(14, 2) NOT NULL,
    employee_contribution_cap numeric(14, 2),
    employer_contribution_cap numeric(14, 2)
) ON COMMIT DROP;

CREATE TEMP TABLE withholding_tax_bracket_seed (
    schedule_id uuid NOT NULL,
    bracket_number integer NOT NULL,
    annual_income_min numeric(14, 2) NOT NULL,
    annual_income_max numeric(14, 2),
    base_tax numeric(14, 2) NOT NULL,
    marginal_rate numeric(8, 6) NOT NULL,
    excess_over numeric(14, 2) NOT NULL
) ON COMMIT DROP;

-- Enter official contribution rows here. Example shape only; no rates are
-- provided or implied. Supply both monthly caps for PAGIBIG; use NULL for
-- both cap fields for SSS and PHILHEALTH. For PAGIBIG, contribution_base and
-- fixed amounts are unused by its salary-percentage calculation; set them to
-- zero:
-- INSERT INTO statutory_contribution_bracket_seed VALUES
--   ('<DRAFT-SCHEDULE-UUID>', 1, 0.00, <MAX>, <BASE>, <EE_RATE>, <ER_RATE>,
--    <EE_FIXED>, <ER_FIXED>, <ER_ADDITIONAL>, <EE_MONTHLY_CAP>, <ER_MONTHLY_CAP>),
--   ('<DRAFT-SCHEDULE-UUID>', 2, <NEXT_MIN>, NULL, <BASE>, <EE_RATE>, <ER_RATE>,
--    <EE_FIXED>, <ER_FIXED>, <ER_ADDITIONAL>, <EE_MONTHLY_CAP>, <ER_MONTHLY_CAP>);
--
-- Enter official withholding-tax rows here. Example shape only; no rates are
-- provided or implied:
-- INSERT INTO withholding_tax_bracket_seed VALUES
--   ('<DRAFT-TAX-SCHEDULE-UUID>', 1, 0.00, <MAX>, <BASE_TAX>, <MARGINAL_RATE>, <EXCESS_OVER>),
--   ('<DRAFT-TAX-SCHEDULE-UUID>', 2, <NEXT_MIN>, NULL, <BASE_TAX>, <MARGINAL_RATE>, <EXCESS_OVER>);

DO $$
DECLARE
    v_program text;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_temp.statutory_contribution_bracket_seed
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_temp.withholding_tax_bracket_seed
    ) THEN
        RAISE EXCEPTION
            'No seed rows supplied. Add official replacement brackets before running; no existing brackets were deleted.';
    END IF;

    FOREACH v_program IN ARRAY ARRAY['SSS', 'PHILHEALTH', 'PAGIBIG']
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_temp.statutory_contribution_bracket_seed AS seed
            JOIN payroll.statutory_contribution_schedules AS schedule
              ON schedule.id = seed.schedule_id
            WHERE schedule.program_code = v_program
              AND schedule.status = 'DRAFT'
        ) THEN
            RAISE EXCEPTION
                'No replacement brackets supplied for a DRAFT % schedule; no existing brackets were deleted.',
                v_program;
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1
        FROM payroll.statutory_contribution_schedules AS schedule
        WHERE schedule.status = 'DRAFT'
          AND NOT EXISTS (
              SELECT 1
              FROM pg_temp.statutory_contribution_bracket_seed AS seed
              WHERE seed.schedule_id = schedule.id
          )
    ) THEN
        RAISE EXCEPTION
            'At least one DRAFT contribution schedule has no replacement bracket set; no existing brackets were deleted.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_temp.statutory_contribution_bracket_seed AS seed
        LEFT JOIN payroll.statutory_contribution_schedules AS schedule
          ON schedule.id = seed.schedule_id
         AND schedule.status = 'DRAFT'
        WHERE schedule.id IS NULL
    ) THEN
        RAISE EXCEPTION
            'A contribution seed row references a missing or non-DRAFT schedule; no existing brackets were deleted.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM payroll.withholding_tax_schedules AS schedule
        WHERE schedule.status = 'DRAFT'
          AND NOT EXISTS (
              SELECT 1
              FROM pg_temp.withholding_tax_bracket_seed AS seed
              WHERE seed.schedule_id = schedule.id
          )
    ) THEN
        RAISE EXCEPTION
            'At least one DRAFT withholding-tax schedule has no replacement bracket set; no existing brackets were deleted.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_temp.withholding_tax_bracket_seed AS seed
        LEFT JOIN payroll.withholding_tax_schedules AS schedule
          ON schedule.id = seed.schedule_id
         AND schedule.status = 'DRAFT'
        WHERE schedule.id IS NULL
    ) THEN
        RAISE EXCEPTION
            'A tax seed row references a missing or non-DRAFT schedule; no existing brackets were deleted.';
    END IF;

    IF EXISTS (
        SELECT schedule_id
        FROM pg_temp.statutory_contribution_bracket_seed
        GROUP BY schedule_id, bracket_number
        HAVING count(*) > 1
    ) OR EXISTS (
        SELECT schedule_id
        FROM pg_temp.withholding_tax_bracket_seed
        GROUP BY schedule_id, bracket_number
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'Duplicate bracket numbers found for a schedule; no existing brackets were deleted.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_temp.statutory_contribution_bracket_seed
        WHERE bracket_number < 1
           OR compensation_min < 0
           OR (compensation_max IS NOT NULL AND compensation_max < compensation_min)
           OR contribution_base < 0
           OR employee_rate NOT BETWEEN 0 AND 1
           OR employer_rate NOT BETWEEN 0 AND 1
           OR employee_fixed_amount < 0
           OR employer_fixed_amount < 0
           OR employer_additional_fixed_amount < 0
           OR (employee_contribution_cap IS NOT NULL AND employee_contribution_cap < 0)
           OR (employer_contribution_cap IS NOT NULL AND employer_contribution_cap < 0)
    ) OR EXISTS (
        SELECT 1
        FROM pg_temp.withholding_tax_bracket_seed
        WHERE bracket_number < 1
           OR annual_income_min < 0
           OR (annual_income_max IS NOT NULL AND annual_income_max < annual_income_min)
           OR base_tax < 0
           OR marginal_rate NOT BETWEEN 0 AND 1
           OR excess_over < 0
    ) THEN
        RAISE EXCEPTION
            'A seed row contains an invalid range, rate, or amount; no existing brackets were deleted.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_temp.statutory_contribution_bracket_seed AS seed
        JOIN payroll.statutory_contribution_schedules AS schedule
          ON schedule.id = seed.schedule_id
        WHERE (schedule.program_code = 'PAGIBIG'
               AND (seed.employee_contribution_cap IS NULL
                    OR seed.employer_contribution_cap IS NULL))
           OR (schedule.program_code <> 'PAGIBIG'
               AND (seed.employee_contribution_cap IS NOT NULL
                    OR seed.employer_contribution_cap IS NOT NULL))
    ) THEN
        RAISE EXCEPTION
            'Pag-IBIG rows require both monthly contribution caps; SSS and PhilHealth rows must omit them. No existing brackets were deleted.';
    END IF;

    IF EXISTS (
        WITH ordered AS (
            SELECT
                schedule_id,
                bracket_number,
                compensation_min AS lower_bound,
                compensation_max AS upper_bound,
                row_number() OVER (PARTITION BY schedule_id ORDER BY compensation_min) AS position,
                count(*) OVER (PARTITION BY schedule_id) AS bracket_count
            FROM pg_temp.statutory_contribution_bracket_seed
        ),
        invalid AS (
            SELECT schedule_id
            FROM ordered
            GROUP BY schedule_id
            HAVING min(lower_bound) <> 0
                OR count(*) FILTER (WHERE upper_bound IS NULL) <> 1
                OR bool_or(bracket_number <> position)
            UNION ALL
            SELECT current.schedule_id
            FROM ordered AS current
            JOIN ordered AS following
              ON following.schedule_id = current.schedule_id
             AND following.position = current.position + 1
            WHERE current.upper_bound IS NULL
               OR following.lower_bound <> current.upper_bound + 0.01
            UNION ALL
            SELECT schedule_id
            FROM ordered
            WHERE upper_bound IS NULL AND position <> bracket_count
        )
        SELECT 1 FROM invalid
    ) OR EXISTS (
        WITH ordered AS (
            SELECT
                schedule_id,
                bracket_number,
                annual_income_min AS lower_bound,
                annual_income_max AS upper_bound,
                row_number() OVER (PARTITION BY schedule_id ORDER BY annual_income_min) AS position,
                count(*) OVER (PARTITION BY schedule_id) AS bracket_count
            FROM pg_temp.withholding_tax_bracket_seed
        ),
        invalid AS (
            SELECT schedule_id
            FROM ordered
            GROUP BY schedule_id
            HAVING min(lower_bound) <> 0
                OR count(*) FILTER (WHERE upper_bound IS NULL) <> 1
                OR bool_or(bracket_number <> position)
            UNION ALL
            SELECT current.schedule_id
            FROM ordered AS current
            JOIN ordered AS following
              ON following.schedule_id = current.schedule_id
             AND following.position = current.position + 1
            WHERE current.upper_bound IS NULL
               OR following.lower_bound <> current.upper_bound + 0.01
            UNION ALL
            SELECT schedule_id
            FROM ordered
            WHERE upper_bound IS NULL AND position <> bracket_count
        )
        SELECT 1 FROM invalid
    ) THEN
        RAISE EXCEPTION
            'Bracket ranges must start at zero, have sequential numbers, be contiguous, and end with one open-ended bracket; no existing brackets were deleted.';
    END IF;
END
$$;

-- Preflight passed: replace bracket rows only for DRAFT schedule headers.
DELETE FROM payroll.statutory_contribution_brackets AS bracket
USING payroll.statutory_contribution_schedules AS schedule
WHERE bracket.schedule_id = schedule.id
  AND schedule.status = 'DRAFT';

DELETE FROM payroll.withholding_tax_brackets AS bracket
USING payroll.withholding_tax_schedules AS schedule
WHERE bracket.schedule_id = schedule.id
  AND schedule.status = 'DRAFT';

INSERT INTO payroll.statutory_contribution_brackets (
    schedule_id,
    bracket_number,
    compensation_min,
    compensation_max,
    contribution_base,
    employee_rate,
    employer_rate,
    employee_fixed_amount,
    employer_fixed_amount,
    employer_additional_fixed_amount,
    employee_contribution_cap,
    employer_contribution_cap
)
SELECT
    schedule_id,
    bracket_number,
    compensation_min,
    compensation_max,
    contribution_base,
    employee_rate,
    employer_rate,
    employee_fixed_amount,
    employer_fixed_amount,
    employer_additional_fixed_amount,
    employee_contribution_cap,
    employer_contribution_cap
FROM pg_temp.statutory_contribution_bracket_seed;

INSERT INTO payroll.withholding_tax_brackets (
    schedule_id,
    bracket_number,
    annual_income_min,
    annual_income_max,
    base_tax,
    marginal_rate,
    excess_over
)
SELECT
    schedule_id,
    bracket_number,
    annual_income_min,
    annual_income_max,
    base_tax,
    marginal_rate,
    excess_over
FROM pg_temp.withholding_tax_bracket_seed;

COMMIT;
