BEGIN;

CREATE TABLE IF NOT EXISTS schedule.rest_day_patterns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern_code varchar(30) NOT NULL UNIQUE,
    pattern_name varchar(100) NOT NULL,
    cycle_length_days integer NOT NULL CHECK (
        cycle_length_days BETWEEN 1 AND 366
    ),
    description text,
    is_active boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS schedule.rest_day_pattern_days (
    pattern_id uuid NOT NULL
        REFERENCES schedule.rest_day_patterns(id) ON DELETE CASCADE,
    cycle_day_no integer NOT NULL,
    is_workday boolean NOT NULL,
    schedule_template_id uuid
        REFERENCES schedule.schedule_templates(id),
    PRIMARY KEY (pattern_id, cycle_day_no)
);

COMMIT;
