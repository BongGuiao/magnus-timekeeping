INSERT INTO core.announcements (
    company_id,
    title,
    body,
    is_active,
    created_by,
    updated_by
)
SELECT
    NULL,
    seed.title,
    seed.body,
    true,
    '00000000-0000-0000-0000-000000000000'::uuid,
    '00000000-0000-0000-0000-000000000000'::uuid
FROM (
    VALUES
        (
            'TEST: Office schedule reminder',
            'This is a sample global announcement for testing the Dashboard announcements card.'
        ),
        (
            'TEST: System maintenance notice',
            'This is a second sample announcement. Replace or deactivate these test records after verification.'
        )
) AS seed(title, body)
WHERE NOT EXISTS (
    SELECT 1
    FROM core.announcements AS existing
    WHERE existing.company_id IS NULL
      AND existing.title = seed.title
);
