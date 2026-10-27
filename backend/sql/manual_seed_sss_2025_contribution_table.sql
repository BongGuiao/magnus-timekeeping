-- Seeds the official SSS schedule effective January 2025 from Circular No. 2024-006.
-- Employee and employer rates store the combined SS and MPF shares; EC is the
-- employer additional fixed amount.
BEGIN;

CREATE TEMP TABLE sss_2025_bracket_seed ON COMMIT DROP AS
SELECT
    bracket_number,
    CASE
        WHEN bracket_number = 1 THEN 0::numeric(14, 2)
        ELSE 4250.00 + 500.00 * bracket_number
    END AS compensation_min,
    CASE
        WHEN bracket_number = 61 THEN NULL::numeric(14, 2)
        ELSE 4749.99 + 500.00 * bracket_number
    END AS compensation_max,
    4500.00 + 500.00 * bracket_number AS contribution_base,
    0.05::numeric(8, 6) AS employee_rate,
    0.10::numeric(8, 6) AS employer_rate,
    0.00::numeric(14, 2) AS employee_fixed_amount,
    0.00::numeric(14, 2) AS employer_fixed_amount,
    CASE
        WHEN bracket_number <= 20 THEN 10.00
        ELSE 30.00
    END AS employer_additional_fixed_amount
FROM generate_series(1, 61) AS ranges(bracket_number);

DO $$
DECLARE
    target_schedule_id uuid;
    target_schedule_status text;
    existing_bracket_count integer;
    valid_existing_bracket_count integer;
BEGIN
    INSERT INTO payroll.statutory_contribution_schedules (
        program_code,
        schedule_name,
        effective_from,
        effective_to,
        source_reference,
        status
    )
    VALUES (
        'SSS',
        'SSS Contribution Table - Effective January 2025',
        DATE '2025-01-01',
        NULL,
        'https://www.sss.gov.ph/wp-content/uploads/2024/12/Cir-2024-006-Employers-scaled.jpg',
        'DRAFT'
    )
    ON CONFLICT (program_code, effective_from) DO NOTHING;

    SELECT id, status
    INTO target_schedule_id, target_schedule_status
    FROM payroll.statutory_contribution_schedules
    WHERE program_code = 'SSS'
      AND effective_from = DATE '2025-01-01'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Could not find or create the SSS schedule effective January 2025.';
    END IF;

    IF target_schedule_status <> 'DRAFT' THEN
        RAISE EXCEPTION
            'The January 2025 SSS schedule is %, not DRAFT; no brackets were changed.',
            target_schedule_status;
    END IF;

    SELECT COUNT(*)
    INTO existing_bracket_count
    FROM payroll.statutory_contribution_brackets
    WHERE schedule_id = target_schedule_id;

    SELECT COUNT(*)
    INTO valid_existing_bracket_count
    FROM payroll.statutory_contribution_brackets AS bracket
    JOIN pg_temp.sss_2025_bracket_seed AS seed
      ON seed.bracket_number = bracket.bracket_number
    WHERE bracket.schedule_id = target_schedule_id
      AND bracket.compensation_min = seed.compensation_min
      AND bracket.compensation_max IS NOT DISTINCT FROM seed.compensation_max
      AND bracket.contribution_base = seed.contribution_base
      AND bracket.employee_rate = seed.employee_rate
      AND bracket.employer_rate = seed.employer_rate
      AND bracket.employee_fixed_amount = seed.employee_fixed_amount
      AND bracket.employer_fixed_amount = seed.employer_fixed_amount
      AND bracket.employer_additional_fixed_amount = seed.employer_additional_fixed_amount;

    IF existing_bracket_count <> valid_existing_bracket_count THEN
        RAISE EXCEPTION
            'Existing SSS brackets do not match the official January 2025 schedule; no brackets were changed.';
    END IF;

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
        employer_additional_fixed_amount
    )
    SELECT
        target_schedule_id,
        seed.bracket_number,
        seed.compensation_min,
        seed.compensation_max,
        seed.contribution_base,
        seed.employee_rate,
        seed.employer_rate,
        seed.employee_fixed_amount,
        seed.employer_fixed_amount,
        seed.employer_additional_fixed_amount
    FROM pg_temp.sss_2025_bracket_seed AS seed
    WHERE NOT EXISTS (
        SELECT 1
        FROM payroll.statutory_contribution_brackets AS existing
        WHERE existing.schedule_id = target_schedule_id
          AND existing.bracket_number = seed.bracket_number
    );

    SELECT COUNT(*)
    INTO existing_bracket_count
    FROM payroll.statutory_contribution_brackets
    WHERE schedule_id = target_schedule_id;

    SELECT COUNT(*)
    INTO valid_existing_bracket_count
    FROM payroll.statutory_contribution_brackets AS bracket
    JOIN pg_temp.sss_2025_bracket_seed AS seed
      ON seed.bracket_number = bracket.bracket_number
    WHERE bracket.schedule_id = target_schedule_id
      AND bracket.compensation_min = seed.compensation_min
      AND bracket.compensation_max IS NOT DISTINCT FROM seed.compensation_max
      AND bracket.contribution_base = seed.contribution_base
      AND bracket.employee_rate = seed.employee_rate
      AND bracket.employer_rate = seed.employer_rate
      AND bracket.employee_fixed_amount = seed.employee_fixed_amount
      AND bracket.employer_fixed_amount = seed.employer_fixed_amount
      AND bracket.employer_additional_fixed_amount = seed.employer_additional_fixed_amount;

    IF existing_bracket_count <> 61 OR valid_existing_bracket_count <> 61 THEN
        RAISE EXCEPTION
            'Expected 61 valid January 2025 SSS brackets; found % total and % valid.',
            existing_bracket_count,
            valid_existing_bracket_count;
    END IF;

    RAISE NOTICE
        'Verified all 61 official January 2025 SSS brackets for schedule %.',
        target_schedule_id;
END;
$$;

COMMIT;
