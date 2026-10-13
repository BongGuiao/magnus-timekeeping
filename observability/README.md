# Location request monitoring and audit events

The location router keeps its existing authentication, database operations, and
response envelopes. Opt-in ASGI middleware records one ECS-compatible JSON event
per HTTP request under `/locations`, including handled 400/401/422/500 responses.
It records the route template (not location IDs), status, response size, completion,
duration in nanoseconds, and a generated request ID. Responses started inside the
middleware include `X-Request-ID`; errors handled by FastAPI's outer server-error
middleware may not include that header.

Request events omit tokens, cookies, query strings, request/response bodies,
client IPs, user IDs, and exception messages. Unmatched paths are redacted.
Location create/update operations also write structured audit events to a
separate per-worker NDJSON file. Those events include the `location` tag, actor
and location IDs, changed fields, and full before/after values. Treat these
values as sensitive business data and restrict Kibana access accordingly.

## Architecture

`FastAPI -> per-worker rotating NDJSON files -> Filebeat disk queue -> Elasticsearch -> Kibana`

No Elasticsearch calls run inside API requests. Filebeat retries independently,
and the web service no longer depends on Elasticsearch availability. Files and
Filebeat registry/queue survive container recreation in named volumes.
Filesystem write failures are reported to stderr without breaking API responses;
failure to create the log directory prevents middleware startup explicitly.

Elasticsearch and Kibana keep matching 8.11.3 versions; Filebeat uses the same
version. This reuses the repository's existing stack; it is not a recommendation
to deploy this older version to production.

## Start and verify

From the project root:

```powershell
docker compose config --quiet
docker compose up -d elasticsearch kibana filebeat web
docker compose logs --tail 50 filebeat
```

Make authenticated calls through your existing frontend or API client to
`/locations/list` and other location endpoints. Check `X-Request-ID` in response
headers. The backend exposes this header through CORS when monitoring is enabled
so cross-origin browser clients can read it in JavaScript.

Open http://localhost:5601. In **Stack Management -> Data Views**, create a data
view named `Magnus logs`, with pattern `filebeat-*` and time field
`@timestamp`. In **Discover**, use:

```text
event.dataset : "magnus.requests" and service.name : "magnus-timekeeping"
```

To find location create/update audit events, use:

```text
tags : "location" and event.dataset : "magnus.location_audit"
```

Expand `before`, `after`, and `changed_fields` in Discover to inspect the
record values and fields changed by each operation.

Useful filters:

```text
http.response.status_code >= 500
http.response.status_code : 401
event.outcome : "failure"
http.request.id : "<X-Request-ID value>"
```

Use Kibana Lens to create a dashboard with:

- Request count over time.
- Counts grouped by `http.response.status_code` and `url.path`.
- p50/p95/p99 of `event.duration`, divided by 1,000,000 for milliseconds.
- A failure-rate formula: failed requests divided by total requests.

The stack ships raw events; it does not automatically create a saved dashboard.
Duration covers application handling through the final response body send,
not browser/network latency. Incomplete responses are marked as failures even
when response headers already had a 200 status.

## Configuration and retention

Compose enables `REQUEST_LOGGING_ENABLED=true` and writes request and location
audit logs to `/var/log/magnus`.
Outside Compose, request monitoring defaults to disabled. Location audit events
are still written to `REQUEST_LOG_DIRECTORY` (default `logs`) when the app starts;
make sure Filebeat watches that directory if you want to ingest them into
Elasticsearch.

Each worker keeps a 10 MiB current file plus five backups (about 60 MiB per worker).
Filebeat has a persistent 1 GiB disk queue. Elasticsearch's
`magnus-request-logs` ILM policy rolls indices daily or at 10 GiB per primary
shard and deletes rolled indices after 14 days. Deletion age is relative to
rollover, not individual event timestamps.

This is bounded buffering, not guaranteed lossless delivery: sufficiently long
outages can exhaust the queue and allow rotation to remove unread events.
Alert on Filebeat output errors, queue usage, and volume disk space. Per-worker
filenames prevent unsafe cross-process rotation; retired workers' files persist
and require operational cleanup after ingestion. Never delete active worker logs
or Filebeat registry/queue data. Registry loss can cause duplicate ingestion.

## Production requirements

The existing single-node stack has security disabled. Ports are now bound to
localhost, but this remains a **development configuration**, not production-ready.
Before production:

- Upgrade all three Elastic components together to a supported, tested version.
- Enable Elasticsearch/Kibana authentication and TLS, including internal traffic.
- Give Filebeat a least-privilege ingestion API key; manage ILM/templates using
  separate provisioning credentials. Inject secrets via your secret manager.
- Restrict Kibana to authenticated administrators behind HTTPS; do not publish
  Elasticsearch directly.
- Set `service.environment` appropriately, size queues/retention, provision log
  cleanup, and configure monitoring of the monitoring pipeline.
- Use appropriately sized nodes, replicas, backups, and resource limits.

Filebeat disables strict config-file permission checks for Windows bind-mount
compatibility; the mounted configurations are read-only. On production Linux,
use correctly owned configuration files and re-enable strict permission checking.

## Focused tests

Using the existing backend image (no database required):

```powershell
docker compose run --rm --no-deps web python -m unittest discover -s backend/tests -p test_request_logging.py -v
```
