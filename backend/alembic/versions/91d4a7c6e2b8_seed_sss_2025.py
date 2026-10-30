"""Seed the existing SSS January 2025 schedule as a draft.

Revision ID: 91d4a7c6e2b8
Revises: fc8ce0a5a09f
"""
from typing import Sequence, Union

from alembic import op

revision: str = "91d4a7c6e2b8"
down_revision: Union[str, None] = "fc8ce0a5a09f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            target_schedule_id uuid;
            target_schedule_status text;
            existing_bracket_count integer;
            matching_bracket_count integer;
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
                RAISE NOTICE
                    'The January 2025 SSS schedule is %, not DRAFT; preserving it without changes.',
                    target_schedule_status;
            ELSE

            SELECT COUNT(*)
            INTO existing_bracket_count
            FROM payroll.statutory_contribution_brackets
            WHERE schedule_id = target_schedule_id;

            WITH seed AS (
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
                FROM generate_series(1, 61) AS ranges(bracket_number)
            )
            SELECT COUNT(*)
            INTO matching_bracket_count
            FROM payroll.statutory_contribution_brackets AS bracket
            JOIN seed
              ON seed.bracket_number = bracket.bracket_number
            WHERE bracket.schedule_id = target_schedule_id
              AND bracket.compensation_min = seed.compensation_min
              AND bracket.compensation_max IS NOT DISTINCT FROM seed.compensation_max
              AND bracket.contribution_base = seed.contribution_base
              AND bracket.employee_rate = seed.employee_rate
              AND bracket.employer_rate = seed.employer_rate
              AND bracket.employee_fixed_amount = seed.employee_fixed_amount
              AND bracket.employer_fixed_amount = seed.employer_fixed_amount
              AND bracket.employer_additional_fixed_amount = seed.employer_additional_fixed_amount
              AND bracket.employee_contribution_cap IS NULL
              AND bracket.employer_contribution_cap IS NULL;

            IF existing_bracket_count <> matching_bracket_count THEN
                RAISE EXCEPTION
                    'Existing SSS brackets do not match the official January 2025 schedule; no brackets were changed.';
            END IF;

            WITH seed AS (
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
                FROM generate_series(1, 61) AS ranges(bracket_number)
            )
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
            FROM seed
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
            INTO matching_bracket_count
            FROM payroll.statutory_contribution_brackets AS bracket
            WHERE bracket.schedule_id = target_schedule_id
              AND bracket.bracket_number BETWEEN 1 AND 61
              AND bracket.compensation_min = CASE
                    WHEN bracket.bracket_number = 1 THEN 0
                    ELSE 4250.00 + 500.00 * bracket.bracket_number
                  END
              AND bracket.compensation_max IS NOT DISTINCT FROM CASE
                    WHEN bracket.bracket_number = 61 THEN NULL::numeric
                    ELSE 4749.99 + 500.00 * bracket.bracket_number
                  END
              AND bracket.contribution_base = 4500.00 + 500.00 * bracket.bracket_number
              AND bracket.employee_rate = 0.05
              AND bracket.employer_rate = 0.10
              AND bracket.employee_fixed_amount = 0
              AND bracket.employer_fixed_amount = 0
              AND bracket.employer_additional_fixed_amount = CASE
                    WHEN bracket.bracket_number <= 20 THEN 10.00
                    ELSE 30.00
                  END
              AND bracket.employee_contribution_cap IS NULL
              AND bracket.employer_contribution_cap IS NULL;

            IF existing_bracket_count <> 61 OR matching_bracket_count <> 61 THEN
                RAISE EXCEPTION
                    'Expected 61 valid January 2025 SSS brackets; found % total and % valid.',
                    existing_bracket_count,
                    matching_bracket_count;
            END IF;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    raise NotImplementedError(
        "The SSS schedule seed is irreversible to avoid deleting payroll reference data."
    )
