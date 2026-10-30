"""Seed the 2026 semi-monthly withholding tax table as a draft.

Revision ID: a6f2d9c4e781
Revises: 91d4a7c6e2b8
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a6f2d9c4e781"
down_revision: Union[str, None] = "91d4a7c6e2b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            target_schedule_id uuid;
            target_schedule_name text;
            target_source_reference text;
            target_status text;
            target_calculation_basis text;
            target_tax_exempt_benefit_limit numeric(14, 2);
            existing_bracket_count integer;
            matching_bracket_count integer;
        BEGIN
            INSERT INTO payroll.withholding_tax_schedules (
                schedule_name,
                effective_from,
                effective_to,
                tax_exempt_benefit_limit,
                calculation_basis,
                source_reference,
                status
            )
            VALUES (
                'BIR Semi-Monthly Withholding Tax Table - 2026',
                DATE '2026-01-01',
                NULL,
                90000.00,
                'SEMI_MONTHLY',
                'https://mpm.ph/bir-tax-table/',
                'DRAFT'
            )
            ON CONFLICT (effective_from) DO NOTHING;

            SELECT
                id,
                schedule_name,
                source_reference,
                status,
                calculation_basis,
                tax_exempt_benefit_limit
            INTO
                target_schedule_id,
                target_schedule_name,
                target_source_reference,
                target_status,
                target_calculation_basis,
                target_tax_exempt_benefit_limit
            FROM payroll.withholding_tax_schedules
            WHERE effective_from = DATE '2026-01-01'
            FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'Could not find or create the semi-monthly withholding-tax schedule effective January 2026.';
            END IF;

            IF target_schedule_name <> 'BIR Semi-Monthly Withholding Tax Table - 2026'
               OR target_source_reference <> 'https://mpm.ph/bir-tax-table/'
               OR target_calculation_basis <> 'SEMI_MONTHLY'
               OR target_tax_exempt_benefit_limit <> 90000.00 THEN
                RAISE EXCEPTION
                    'A different withholding-tax schedule already uses 2026-01-01; no schedule or bracket data was changed.';
            END IF;

            IF target_status <> 'DRAFT' THEN
                RAISE NOTICE
                    'The January 2026 semi-monthly withholding-tax schedule is %, preserving it without changes.',
                    target_status;
            ELSE
                SELECT COUNT(*)
                INTO existing_bracket_count
                FROM payroll.withholding_tax_brackets
                WHERE schedule_id = target_schedule_id;

                WITH seed (
                    bracket_number,
                    annual_income_min,
                    annual_income_max,
                    base_tax,
                    marginal_rate,
                    excess_over
                ) AS (
                    VALUES
                        (1, 0.00::numeric, 10416.99::numeric, 0.00::numeric, 0.00::numeric, 0.00::numeric),
                        (2, 10417.00::numeric, 16666.99::numeric, 0.00::numeric, 0.15::numeric, 10417.00::numeric),
                        (3, 16667.00::numeric, 33332.99::numeric, 937.50::numeric, 0.20::numeric, 16667.00::numeric),
                        (4, 33333.00::numeric, 83332.99::numeric, 4270.70::numeric, 0.25::numeric, 33333.00::numeric),
                        (5, 83333.00::numeric, 333332.99::numeric, 16770.70::numeric, 0.30::numeric, 83333.00::numeric),
                        (6, 333333.00::numeric, NULL::numeric, 91770.70::numeric, 0.35::numeric, 333333.00::numeric)
                )
                SELECT COUNT(*)
                INTO matching_bracket_count
                FROM payroll.withholding_tax_brackets AS bracket
                JOIN seed
                  ON seed.bracket_number = bracket.bracket_number
                WHERE bracket.schedule_id = target_schedule_id
                  AND bracket.annual_income_min = seed.annual_income_min
                  AND bracket.annual_income_max IS NOT DISTINCT FROM seed.annual_income_max
                  AND bracket.base_tax = seed.base_tax
                  AND bracket.marginal_rate = seed.marginal_rate
                  AND bracket.excess_over = seed.excess_over;

                IF existing_bracket_count <> matching_bracket_count THEN
                    RAISE EXCEPTION
                        'Existing January 2026 semi-monthly tax brackets do not match the MPM table; no brackets were changed.';
                END IF;

                IF existing_bracket_count = 0 THEN
                    WITH seed (
                        bracket_number,
                        annual_income_min,
                        annual_income_max,
                        base_tax,
                        marginal_rate,
                        excess_over
                    ) AS (
                        VALUES
                            (1, 0.00::numeric, 10416.99::numeric, 0.00::numeric, 0.00::numeric, 0.00::numeric),
                            (2, 10417.00::numeric, 16666.99::numeric, 0.00::numeric, 0.15::numeric, 10417.00::numeric),
                            (3, 16667.00::numeric, 33332.99::numeric, 937.50::numeric, 0.20::numeric, 16667.00::numeric),
                            (4, 33333.00::numeric, 83332.99::numeric, 4270.70::numeric, 0.25::numeric, 33333.00::numeric),
                            (5, 83333.00::numeric, 333332.99::numeric, 16770.70::numeric, 0.30::numeric, 83333.00::numeric),
                            (6, 333333.00::numeric, NULL::numeric, 91770.70::numeric, 0.35::numeric, 333333.00::numeric)
                    )
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
                        target_schedule_id,
                        bracket_number,
                        annual_income_min,
                        annual_income_max,
                        base_tax,
                        marginal_rate,
                        excess_over
                    FROM seed;
                END IF;

                SELECT COUNT(*)
                INTO existing_bracket_count
                FROM payroll.withholding_tax_brackets
                WHERE schedule_id = target_schedule_id;

                IF existing_bracket_count <> 6 THEN
                    RAISE EXCEPTION
                        'Expected six January 2026 semi-monthly withholding-tax brackets; found %.',
                        existing_bracket_count;
                END IF;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    raise NotImplementedError(
        "The withholding-tax schedule seed is irreversible to avoid deleting payroll reference data."
    )
