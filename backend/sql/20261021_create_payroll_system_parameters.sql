BEGIN;

CREATE TABLE payroll.system_parameters (
    id smallint PRIMARY KEY DEFAULT 1,
    year_end_wtax_reconciliation_enabled boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by uuid REFERENCES identity.users(id),
    CONSTRAINT ck_payroll_system_parameters_singleton CHECK (id = 1)
);

INSERT INTO payroll.system_parameters (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;

COMMIT;
