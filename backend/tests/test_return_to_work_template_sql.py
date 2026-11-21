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


class ManualCreateNoticeTemplatesSqlTests(unittest.TestCase):
    def setUp(self):
        url = make_url(settings.DATABASE_URL).set(drivername="postgresql")
        if url.database != "notice_template_test":
            self.skipTest("Requires a disposable notice_template_test database.")
        self.connection = psycopg2.connect(url.render_as_string(hide_password=False))
        self.connection.autocommit = True
        self.addCleanup(self.connection.close)
        self.cursor = self.connection.cursor()
        self.addCleanup(self.cursor.close)
        self.cursor.execute("CREATE TEMP TABLE users (id uuid PRIMARY KEY)")
        script = (Path(__file__).resolve().parents[1] / "sql" / "manual_create_notice_templates.sql").read_text()
        self.script = (
            script.replace("attendance.notice_templates", "pg_temp.notice_templates")
            .replace("identity.users", "pg_temp.users")
            .replace("public.alembic_version", "pg_temp.alembic_version")
            .replace("to_regnamespace('attendance')", "pg_my_temp_schema()")
        )

    def test_creates_template_storage_with_required_constraints(self):
        self.cursor.execute(self.script)
        self.cursor.execute("INSERT INTO pg_temp.users VALUES ('00000000-0000-0000-0000-000000000001')")
        insert = (
            "INSERT INTO pg_temp.notice_templates (name, module, sanitized_html, is_active, created_by) "
            "VALUES ('Test', %s, 'test', %s, '00000000-0000-0000-0000-000000000001')"
        )
        self.cursor.execute(insert, ("TARDINESS", True))
        self.cursor.execute(insert, ("RETURN_TO_WORK", True))
        self.cursor.execute(insert, ("RETURN_TO_WORK", False))
        for module, active in (("INVALID", False), ("RETURN_TO_WORK", True)):
            with self.subTest(module=module), self.assertRaises(psycopg2.Error):
                self.cursor.execute(insert, (module, active))
        with self.assertRaises(psycopg2.Error):
            self.cursor.execute(self.script)
        self.cursor.execute("ROLLBACK")
        self.cursor.execute("SELECT COUNT(*) FROM pg_temp.notice_templates")
        self.assertEqual(self.cursor.fetchone()[0], 3)

    def test_refuses_a_tracked_database_without_creating_a_table(self):
        self.cursor.execute("CREATE TEMP TABLE alembic_version (version_num varchar(32) NOT NULL)")
        self.cursor.execute("INSERT INTO pg_temp.alembic_version VALUES ('c6f8a0b2d4e6')")
        with self.assertRaises(psycopg2.Error) as raised:
            self.cursor.execute(self.script)
        self.assertIn("Use Alembic", str(raised.exception))
        self.cursor.execute("ROLLBACK")
        self.cursor.execute("SELECT to_regclass('pg_temp.notice_templates')")
        self.assertIsNone(self.cursor.fetchone()[0])

    def test_refuses_missing_users_without_creating_a_table(self):
        self.cursor.execute("DROP TABLE pg_temp.users")
        with self.assertRaises(psycopg2.Error) as raised:
            self.cursor.execute(self.script)
        self.assertIn("users table is missing", str(raised.exception))
        self.cursor.execute("ROLLBACK")
        self.cursor.execute("SELECT to_regclass('pg_temp.notice_templates')")
        self.assertIsNone(self.cursor.fetchone()[0])
