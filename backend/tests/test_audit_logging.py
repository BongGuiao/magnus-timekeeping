import json
import logging
import os
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.core.audit_logging import log_entity_change, stamp_audit_fields
from app.core.request_logging import configure_audit_logger


@dataclass
class ExampleEntity:
    id: UUID
    name: str
    active: bool


class AuditLoggingTests(unittest.TestCase):
    def test_audit_event_is_written_as_json_ndjson(self) -> None:
        entity_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        actor_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        entity = ExampleEntity(entity_id, "Location", True)
        logger = logging.getLogger("magnus.audit")

        with tempfile.TemporaryDirectory() as directory:
            try:
                configure_audit_logger(directory)
                log_entity_change(
                    entity_name="location",
                    action="update",
                    entity_id=entity_id,
                    actor_id=actor_id,
                    before=entity,
                    after=entity,
                )

                log_path = Path(directory) / f"location-audit-{os.getpid()}.ndjson"
                event = json.loads(log_path.read_text(encoding="utf-8"))
                self.assertEqual(event["tags"], ["location"])
                self.assertEqual(event["before"]["id"], str(entity_id))
            finally:
                for handler in logger.handlers[:]:
                    logger.removeHandler(handler)
                    handler.close()

    def test_stamps_create_and_update_fields_from_actor(self) -> None:
        actor_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        create_payload: dict[str, object] = {}
        stamped_create = stamp_audit_fields(
            create_payload,
            actor_id,
            creating=True,
        )

        self.assertEqual(stamped_create["created_by"], actor_id)
        self.assertEqual(stamped_create["updated_by"], actor_id)
        self.assertEqual(stamped_create["created_at"], stamped_create["updated_at"])

        update_payload: dict[str, object] = {}
        stamped_update = stamp_audit_fields(
            update_payload,
            actor_id,
            creating=False,
        )
        self.assertNotIn("created_at", stamped_update)
        self.assertNotIn("created_by", stamped_update)
        self.assertEqual(stamped_update["updated_by"], actor_id)
        self.assertIn("updated_at", stamped_update)

    def test_logs_before_after_and_changed_fields_with_entity_tag(self) -> None:
        entity_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        actor_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        before = ExampleEntity(entity_id, "Old name", True)
        after = ExampleEntity(entity_id, "New name", True)

        with self.assertLogs("magnus.audit", level="INFO") as captured:
            log_entity_change(
                entity_name="location",
                action="update",
                entity_id=entity_id,
                actor_id=actor_id,
                before=before,
                after=after,
            )

        event = captured.records[0].msg
        self.assertIsInstance(event, dict)
        self.assertEqual(event["tags"], ["location"])
        self.assertEqual(event["event.dataset"], "magnus.location_audit")
        self.assertEqual(event["event.action"], "update")
        self.assertEqual(event["location.id"], str(entity_id))
        self.assertEqual(event["user.id"], str(actor_id))
        self.assertEqual(event["changed_fields"], ["name"])
        self.assertEqual(event["before"]["name"], "Old name")
        self.assertEqual(event["after"]["name"], "New name")

    def test_logs_create_with_all_fields_changed(self) -> None:
        entity_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        actor_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        after = ExampleEntity(entity_id, "New name", True)

        with self.assertLogs("magnus.audit", level="INFO") as captured:
            log_entity_change(
                entity_name="location",
                action="create",
                entity_id=entity_id,
                actor_id=actor_id,
                before=None,
                after=after,
            )

        event = captured.records[0].msg
        self.assertIsInstance(event, dict)
        self.assertIsNone(event["before"])
        self.assertEqual(event["changed_fields"], ["id", "name", "active"])


if __name__ == "__main__":
    unittest.main()
