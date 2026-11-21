import unittest
from pathlib import Path

import psycopg2
from sqlalchemy.engine import make_url

from app.core.config import settings


class ManualReturnToWorkTemplateSqlTests(unittest.TestCase):
    def setUp(self):
        url = make_url(settings.DATABASE_URL).set(drivername="postgresql")
        self.connection = psycopg2.connect(url.render_as_string(hide_password=False))
        self.connection.autocommit = True
        self.addCleanup(self.connection.close)
        self.cursor = self.connection.cursor()
        self.addCleanup(self.cursor.close)
        self.cursor.execute(
            "CREATE TEMP TABLE notice_templates (module varchar(40) NOT NULL "
            "CONSTRAINT ck_notice_templates_module CHECK (module = 'TARDINESS'))"
        )
        self.cursor.execute("INSERT INTO pg_temp.notice_templates (module) VALUES ('TARDINESS')")
        script = (Path(__file__).resolve().parents[1] / "sql" / "manual_return_to_work_notice_templates.sql").read_text()
        self.script = script.replace("attendance.notice_templates", "pg_temp.notice_templates").replace(
            "public.alembic_version", "pg_temp.alembic_version",
        )

    def test_preserves_existing_templates_and_allows_new_module(self):
        self.cursor.execute(self.script)
        self.cursor.execute("INSERT INTO pg_temp.notice_templates (module) VALUES ('RETURN_TO_WORK')")
        self.cursor.execute("SELECT module FROM pg_temp.notice_templates ORDER BY module")
        self.assertEqual([row[0] for row in self.cursor.fetchall()], ["RETURN_TO_WORK", "TARDINESS"])
        with self.assertRaises(psycopg2.Error):
            self.cursor.execute(self.script)
        self.cursor.execute("ROLLBACK")

    def test_refuses_a_tracked_database(self):
        self.cursor.execute("CREATE TEMP TABLE alembic_version (version_num varchar(32) NOT NULL)")
        self.cursor.execute("INSERT INTO pg_temp.alembic_version VALUES ('c6f8a0b2d4e6')")
        with self.assertRaises(psycopg2.Error) as raised:
            self.cursor.execute(self.script)
        self.assertIn("Use Alembic", str(raised.exception))
        self.cursor.execute("ROLLBACK")
        self.cursor.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'pg_temp.notice_templates'::regclass AND conname = 'ck_notice_templates_module'"
        )
        self.assertEqual(self.cursor.fetchone()[0], "CHECK (((module)::text = 'TARDINESS'::text))")
