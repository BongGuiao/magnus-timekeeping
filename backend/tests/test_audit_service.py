import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from app.audit.domain import AuditLogCreate
from app.audit.service import log_action, log_entity_action


class AuditServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_indexes_json_serialized_audit_log(self) -> None:
        client = AsyncMock()
        timestamp = datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc)
        log_data = AuditLogCreate(
            user_id="user-1",
            action="UPDATE",
            resource="location",
            resource_id="location-1",
            old_values={"name": "Old name"},
            new_values={"name": "New name"},
            timestamp=timestamp,
        )

        await log_action(client, log_data)

        client.index.assert_awaited_once_with(
            index="ticketing-audit-logs",
            document={
                "user_id": "user-1",
                "action": "UPDATE",
                "resource": "location",
                "resource_id": "location-1",
                "old_values": {"name": "Old name"},
                "new_values": {"name": "New name"},
                "timestamp": "2026-01-02T03:04:00Z",
            },
        )

    async def test_elasticsearch_failure_does_not_escape(self) -> None:
        client = AsyncMock()
        client.index.side_effect = RuntimeError("connection unavailable")
        log_data = AuditLogCreate(
            user_id="user-1",
            action="CREATE",
            resource="location",
            resource_id="location-1",
        )

        with self.assertLogs("magnus.audit.elasticsearch", level="ERROR"):
            await log_action(client, log_data)

    async def test_entity_audit_does_not_block_on_slow_elasticsearch(self) -> None:
        release = asyncio.Event()
        client = AsyncMock()

        async def slow_index(**_: object) -> None:
            await release.wait()

        client.index.side_effect = slow_index

        await asyncio.wait_for(
            log_entity_action(
                client,
                user_id="user-1",
                action="calculate",
                resource="payroll_cutoff",
                resource_id="cutoff-1",
                after={"status": "HOLD"},
            ),
            timeout=0.5,
        )

        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        client.index.assert_awaited_once()
        self.assertEqual(
            client.index.await_args.kwargs["document"]["action"], "CALCULATE"
        )


if __name__ == "__main__":
    unittest.main()
