# React + TypeScript + Vite

## Editing employee role assignments

Under an employee's **Role** tab, **Edit assignment** allows changing org-unit
scope, effective-from date, and expiration date. Role and company remain fixed.
Org-unit choices are active units within the existing role assignment's company,
not the employee's latest employment-assignment company. **All org units** clears
the org-unit scope to company-wide. Changed scope and dates are checked for
overlapping assignments before saving; the backend repeats the overlap checks.
Existing unavailable/inactive scopes may be retained when changing dates only.
Global assignments without a company keep their scope and allow date edits only.
This does not change the employee's organizational placement or employment
assignment. Existing role-management permissions and backend audit logging apply.

## Employee CSV export

In Employee Records, **Export CSV** downloads all employee profiles (including
archived/disabled records) with bank account, SSS, Pag-IBIG, PhilHealth, TIN,
civil status, complete address components, and PSGC codes. Employees without
saved personal details are included with empty cells. Authentication, face
encodings, employment assignments, and audit internals are not exported.

Only accounts currently assigned the exact `HR_ADMIN` role, with
`employees.manage` permission and `HR_ADMIN` dashboard mode, may export.
`GET /employees/export?dashboard_role_code=HR_ADMIN` independently checks the
current database authorization; a generic administrator role is insufficient.
Export auditing records the actor and row count, not the exported personal data.
Responses use `Cache-Control: no-store`.

The UTF-8 CSV preserves saved address text and identifier strings; import
identifier, postal-code, and PSGC columns **as Text** in spreadsheet software
to retain leading zeroes. Formula-like cells receive an apostrophe prefix for
spreadsheet safety, without modifying saved employee values. The file contains
confidential personal information and must be stored securely.
No migration is required; deploy the frontend and reload the backend together.

## Organizational chart

In **Company Setup > Org Units**, select a company and switch from **Table** to
**Org chart**. The viewer uses existing parent org unit and manager assignments;
it needs no database migration or additional dependencies and retains the
existing `company.setup` permission.

Compact unit and employee cards with tighter branch spacing keep more of the
hierarchy visible at 100% zoom; zoom and **Fit** remain available for larger charts.

The manager toggle shows the unit's name/description (`org_unit_name`) in bold,
without repeating it as a heading above the manager box.
Click a unit's manager to show or hide employee cards for **that org unit only**.
Child units retain their own managers and separate member branches. Units without
a manager also have a member toggle. The manager is not repeated as a member card.
Membership comes from active employment assignments effective today in Philippine
time, including the effective-to and separation date, excluding inactive or
archived employees. Duplicate assignments within a unit yield one employee card.
Unavailable employee records are labeled, not silently omitted.

Expand or collapse individual unit branches, use **Expand all** / **Collapse all**
to expand or collapse both units and people,
zoom, or **Fit** the chart. Drag or scroll to pan (swipe on touch screens);
keyboard users can focus the canvas and scroll with arrow keys.
**New org unit** and each card's **Edit unit** open the existing forms. Saving
updates the chart; **Refresh** reloads current data. Employment assignment changes
in other open panels refresh membership automatically. Loading and permission
errors are shown explicitly and disable member expansion until a successful retry.

The chart includes every non-deleted unit in the selected company, including
draft, inactive, disabled, and future-effective units. Deleted units remain
available only in the table's **Show deleted** view. Unassigned or unavailable
managers are labeled explicitly. Missing parents and circular relationships
produce warnings and separate display roots without modifying saved data.
Purple lines represent unit hierarchy; dashed green lines represent membership,
not employee supervisor or approval routes. Employee visibility uses the existing
employee API permissions; this viewer does not grant additional employee access.

## HR team schedule uploads

Team Schedule Upload offers an HR CSV format only when the account has the exact
`HR_ADMIN` role and the selected dashboard role is `HR_ADMIN`. The existing
`schedule.upload_team` permission is still required. Template, preview, and
submission use the `/schedule-uploads/hr-admin` endpoints with
`dashboard_role_code=HR_ADMIN`; the backend checks the user's current assigned
roles, rather than trusting a browser role or JWT role label alone.

The HR template adds the required `supervisor_employee_code` column. Each row
must specify an active supervisor employee number, and the employee must already
be an active direct report of that supervisor. This upload does not change
employment assignments or reporting relationships. HR uploaders do not need an
employee profile linked to their own account.

A file may contain several supervisors. Preview shows supervisor codes and
original CSV row numbers. Submission revalidates the entire file, then creates
one batch per supervisor in one transaction, retaining the HR user as uploader.
Any invalid row or persistence/application failure rejects the entire file;
overlapping rows for an employee are checked across supervisor groups too.
Existing per-company approval settings still apply to each batch: batches wait
for an independent reviewer when required, or are auto-approved and applied when
that setting is disabled. The UI displays the returned status for every batch.
My uploads shows the supervisor for each batch.

Ordinary supervisor uploads retain their current CSV format and own-team scope.
Changing between HR and other dashboard modes clears the selected file and
preview so a file cannot accidentally be submitted using the other mode.
Role selectors in all open workspace modules stay synchronized with the selected
dashboard mode, including accounts assigned both HR_ADMIN and SUPERVISOR.
No database migration is needed; deploy backend and frontend together.

## Operational groups

Deploy the updated Nginx configuration with the frontend and backend:
`operational-groups` must be included in the backend API routing allowlist.
Test the configuration inside `nginx_proxy` with `nginx -t`, then reload it
with `nginx -s reload`. An unauthenticated request to
`/operational-groups/list?company_id=00000000-0000-0000-0000-000000000000`
should receive an authentication error from the API, not HTTP 200 with HTML.
HTML means the request is falling through to the frontend. The lookup reports
an explicit response error instead of passing invalid data to the table.

Under Company Setup, Operational Groups manages company-specific group codes,
display names, sort order, and active status using the existing `company.setup`
permission. Codes are immutable and remain reserved after deletion.
Delete is a soft delete: the record, deletion timestamp and deleting user are
retained, and existing employee assignments keep their original group code.
Deleted groups are excluded from normal lookups and cannot be newly assigned.
Editing an existing assignment can retain the same deleted group in the same
company. Use **Show deleted** to view deleted groups and **Restore** to recover
one. Restored groups are inactive until explicitly reactivated through Edit.
Delete, Restore, and metadata updates use the existing `company.setup`
permission and audit logging.
New companies start with no groups; add the groups they need in this page.

### Deploying soft delete to an existing installation

Back up the database first. After the original operational groups migration,
apply `backend/sql/20261030_soft_delete_operational_groups.sql` **once**, or use
Alembic revision `d9a0123e4f56` instead (not both). Do not rerun the original
table-creation script. The new migration only adds nullable deletion metadata;
it does not delete groups or change employment assignments.

On the production Linux server, from the project directory:

```bash
docker cp ./backend/sql/20261030_soft_delete_operational_groups.sql postgres_db:/tmp/soft_delete_operational_groups.sql &&
docker exec postgres_db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /tmp/soft_delete_operational_groups.sql'
```

Confirm `COMMIT`, then deploy the updated backend and frontend together.

Employment Assignments loads its dropdown from `GET /operational-groups/list`
for the selected company. Inactive groups cannot be newly assigned, but an
existing assignment can keep its inactive group while other fields are edited.
Changing company clears the selection. `None` remains a nullable group.
Loading failures are displayed with a Retry action and block assignment saves.
Saving a group refreshes lookups in open assignment panels. CSV imports also
resolve active group codes through the API, rather than a fixed frontend list.
Payroll review continues filtering the codes recorded on assignment results.

Deploy backend and frontend together **after** applying the operational groups
migration, and reload/recreate Nginx with the updated API proxy configuration.
Alembic-managed installations use revision `c8f9012d3e45` via
`alembic -c alembic.ini upgrade head`. Existing installations without a reviewed
Alembic baseline can instead apply
[`20261030_create_operational_groups.sql`](../backend/sql/20261030_create_operational_groups.sql)
once using `psql -v ON_ERROR_STOP=1 -f ...`; do not run both migration paths.
Do not run the fresh-install Alembic baseline or blindly stamp an existing
database. Back up first and pause assignment/group writes during the migration.
The migration seeds the nine existing choices for every current company and
preserves existing non-null assignment codes before replacing the fixed-list
constraint with a company-and-code foreign key. No assignment codes are renamed.
Downgrade refuses to proceed while custom group codes exist.
Installations without the legacy named check constraint are supported.
If an attempt fails inside the script's transaction, run `ROLLBACK;` on the same
connection before rerunning the complete corrected script, not just its remaining
statements. The script is a one-time migration, not a general rerunnable installer.

## Attendance actions

The web attendance page uses **Clock In** and **Clock Out**, matching the native
mobile app. Both actions still require face verification. The punch controls show
available break actions, not the completed-break history panel. After the meal
break ends, configured shifts offer **Start Second Break** alongside **Clock Out**
within its configured window. Completing the meal
break also hides an unstarted first break, even when configured windows overlap.
This controls the web page's available actions; server-side configured-window
validation is unchanged. Recorded break punches are preserved.

Break controls require paid or unpaid break segments in the attendance record's
schedule snapshot. If there are no such segments (or no break rules), all break
options, including overtime breaks, are hidden. Clock In and Clock Out remain
available as usual. Defined regular breaks respect their configured slots and
windows; no legacy default breaks are offered when rules are absent.

When Clock Out is earlier than the attendance record's scheduled end, the
confirmation warns that the scheduled time out is later than the current time.
**No** dismisses the dialog without recording attendance; **Yes** continues
through face verification and the existing server validations. Other clock and
break confirmations are unchanged. The comparison includes the scheduled date
for overnight shifts and uses Philippine time for timestamps without an offset.

Before a browser attendance or break punch captures and submits its face image,
the employee must look toward the camera and blink once. Blink detection runs
locally in the browser; the image is still sent to the backend for the existing
face match and punch validation. The vision runtime and model are downloaded
from the pinned MediaPipe CDN and Google model host when first needed, so a
connection to those hosts is required for browser punches. This client-side
check is a liveness prompt, not server-verified anti-spoof protection. The
mobile app does not use this blink gate.

Both browser face-enrollment screens also require a live-camera blink before
capturing a photo. Uploaded images are not offered as an enrollment alternative.
Starting another capture clears the previous photo; cancelling, switching
employees, or leaving the screen cancels an in-progress blink check. The admin
must still verify the employee in person. This is a client-side prompt only:
the enrollment API does not independently verify the blink, and recorded video
or a modified client can bypass it. Enrollment requires HTTPS (or localhost)
camera access and connectivity to the model hosts above.

### Reviewing and correcting face enrollment

Employee Records > Face Enrollment shows the actual saved samples to HR Admins
with `employees.manage`. The backend verifies the currently assigned `HR_ADMIN`
role, not just cached browser roles. Saved photos are fetched through authenticated
requests; templates/face encodings are never returned by the review API. A missing
reference photo is explicitly shown and does not mean the employee is unenrolled.
The profile picture represents only the first saved sample unless changed separately.

A capture within `FACE_MATCH_THRESHOLD` of another employee is blocked even if
its own employee's sample is closer. The message shows the similar employee
number, the closest distance and the limit. Do not lower the threshold or reset
correct enrollments to bypass this protection.

If HR has verified in person that they are different people, an HR Admin (with
employee-management permission) can use **Approve and save face**: enter a reason
and tick the confirmation. The server re-checks the similar employees; if they
changed, a fresh approval is required. The sample and its approval are saved in
one transaction in `biometric.face_enrollment_similarity_overrides` (employee,
similar employee IDs/numbers, closest distance, limit, reason, approver, time).
If that record cannot be saved, neither the sample nor its image is kept.

Because approved faces can be close to another employee, every face punch
(kiosk, clock and break) now also requires a clear winner: if the second-closest
employee is within `FACE_MATCH_MARGIN` (default `0.05`) of the closest, the punch
is rejected as "Face not recognized" and the employee should retry. This only
adds rejections; it never accepts a face that was previously rejected.

For confirmed incorrect enrollment, use **Remove all face samples** for that employee.
HR must type the employee number, give a reason, and confirm the warning. The
server requires the exact reviewed sample IDs and serializes reset with enrollment;
changed records require a fresh review. Reset deletes only the selected employee's
samples, clears their profile reference only if linked to those samples, and audits
the actor, employee, sample IDs/count, and reason without images or templates.
Attendance records are not deleted. Face punches will fail until the correct
employee is re-enrolled in person.

Reset auditing is stored in PostgreSQL in `biometric.face_enrollment_resets`, in
the same transaction as the reset. It records the timestamp, actor and employee
identifiers, employee number, removed sample IDs/count, reason, and whether the
linked profile photo was cleared. It never stores photos, image paths, face
encodings, or similarity scores. It works with Elasticsearch disabled; an
Elasticsearch event, when configured, is only an optional best-effort copy.
If the database audit cannot be saved, the reset fails and the samples, profile
photo, and files remain intact. Database commit failure rolls back both records.
Employee/account deletion does not cascade-delete audit history.

**Deployment prerequisite:** back up the production database and uploaded files,
then apply the additive
[`20261113_add_face_enrollment_reset_audit.sql`](../backend/sql/20261113_add_face_enrollment_reset_audit.sql)
to the application's database before deploying this backend and frontend together.
It only creates the reset audit table/index and can safely be rerun. For a database
already correctly tracked by Alembic, use revision `f2a3b4c5d6e7` (after
`e1f2a3b4c5d6`) instead. Do not initialize or stamp an existing production database
just to apply this change. A code rollback should retain the audit table; Alembic
refuses to drop it once audit records exist. No production Elasticsearch service
or logging configuration change is needed.

Then apply
[`20261113_add_face_enrollment_similarity_overrides.sql`](../backend/sql/20261113_add_face_enrollment_similarity_overrides.sql)
(Alembic `f3a4b5c6d7e8`, after `f2a3b4c5d6e7`). It is additive and rerunnable.
Without it, approvals fail safely and nothing is saved. Inspect approvals with:

```sql
SELECT approved_at, approved_by, employee_no, conflicting_employee_nos,
       closest_distance, threshold, reason
FROM biometric.face_enrollment_similarity_overrides
ORDER BY approved_at DESC
LIMIT 50;
```

Authorized database administrators can inspect recent resets with:

```sql
SELECT reset_at, reset_by, employee_id, employee_no, sample_count,
       reason, profile_photo_cleared
FROM biometric.face_enrollment_resets
ORDER BY reset_at DESC
LIMIT 50;
```

Unreferenced sample images are removed after the database commit; files shared by
another profile/sample are preserved. Cleanup failures are reported explicitly,
and orphaned image URLs are no longer served. Unsupported legacy photo references
require manual storage cleanup. Neither employee is reset automatically when a
similarity conflict occurs. Late capture/save/reset responses cannot update a
different employee after navigating away.

### Diagnosing a face similarity conflict

The backend uses dlib's 128-component descriptors and Euclidean distance, not
pgvector cosine/inner-product similarity. Lower distance means closer; a conflict
requires distance <= `FACE_MATCH_THRESHOLD`. Do not normalize existing descriptors
or change the threshold to diagnose a failure.

Captured descriptors and vectors used for comparison must have exactly 128 finite
components and a finite, non-zero norm. Invalid data fails explicitly, including
when an HR override is requested; it is not silently replaced or treated as a match.

On a conflict, the backend emits a `FACE_ENROLLMENT_CONFLICT` warning with the
requested employee ID, matched employee ID/number and nearest sample ID, unrounded
distance, effective threshold, both vector norms, and whether approval was requested.
`FACE_ENCODING_INVALID` identifies rejected malformed vectors. These warnings work
without Elasticsearch. They contain no photos or embedding arrays; restrict access
to the logs because employee identifiers are present.

After one failed attempt, inspect the backend container logs (`docker logs --since
10m app_backend`). To check the affected stored records, run this read-only query
against the application's production database, replacing the two employee numbers:

```sql
BEGIN READ ONLY;
WITH inspected AS (
    SELECT e.employee_no, f.id AS sample_id, f.status,
           array_ndims(f.face_encoding) AS array_dimensions,
           cardinality(f.face_encoding) AS components,
           stats.invalid_components, stats.squared_norm
    FROM hr.employees e
    LEFT JOIN biometric.face_enrollment_data f ON f.employee_id = e.id
    LEFT JOIN LATERAL (
        SELECT count(*) FILTER (
                   WHERE v IS NULL OR v::text IN ('NaN', 'Infinity', '-Infinity')
               ) AS invalid_components,
               sum(v::numeric * v::numeric) FILTER (
                   WHERE v IS NOT NULL AND v::text NOT IN ('NaN', 'Infinity', '-Infinity')
               ) AS squared_norm
        FROM unnest(f.face_encoding) AS values_(v)
    ) stats ON true
    WHERE e.employee_no IN ('0128', '0201')
)
SELECT employee_no, sample_id, status, components, invalid_components,
       CASE WHEN invalid_components = 0 THEN sqrt(squared_norm) END AS norm,
       CASE WHEN sample_id IS NULL THEN 'no_sample'
            WHEN array_dimensions IS DISTINCT FROM 1 OR components IS DISTINCT FROM 128
                 OR invalid_components > 0 OR squared_norm = 0
                 OR sqrt(squared_norm) > 1.7976931348623157e308::numeric THEN 'invalid_encoding'
            ELSE 'valid_encoding' END AS encoding_check
FROM inspected
ORDER BY employee_no, sample_id;
ROLLBACK;
```

The failed capture is not saved, so comparing only stored rows cannot explain its
failure. Correlate this report with the conflict log from that same attempt. An
exact zero distance does not by itself prove a reused photo, and a non-zero
distance below the limit does not prove that the employees are the same person.
The HR override is an operational exception, not evidence of the root cause.

## Dashboard worked hours

Administrator weekly totals, employee weekly summaries, and Recent Attendance
use net worked minutes: completed corrected punches (when present), otherwise
recorded punches, minus saved nonpayable break minutes. Paid breaks are retained.
The formula is actual clock-out minus actual clock-in, minus the existing
attendance break-policy deductions: actual unpaid breaks, missing auto-deducted
unpaid allowances, and only the excess over paid-break allowances. An unpaid
break's excess is not deducted again; recorded unpaid punches replace, rather
than add to, an auto-deduct allowance. Late/undertime and approved overtime are
not separately subtracted/added to elapsed time, which would double-count them.
Missing or reversed punches do not contribute to weekly totals. Totals are summed
in integer minutes before formatting, avoiding drift from rounded decimal hours.

This week means Monday through today in Philippine time, based on the attendance
work date, including overnight shifts. Recent Attendance remains the latest five
valid records in the current payroll cutoff; it is not the complete weekly list.
Employee dashboard refreshes load a live snapshot. Deploy backend and frontend
together and restart the Celery worker; versioned attendance cache keys prevent
older snapshots from serving inconsistent hours. No database migration is needed.

## Supervisor punch locations

Supervisors with `attendance.read_team` can search the dashboard by employee code
and work date to view the employee's recorded clock-in and clock-out GPS points.
The backend derives the supervisor identity from the authenticated token and
resolves the employee's active company assignment; it returns locations only for
an active direct report. The form does not accept supervisor or company IDs.
Map pins use OpenStreetMap tiles; each pin can open its coordinates in Google
Street View when coverage is available. GPS coordinates are reported evidence,
not proof of the employee's physical location. No database migration is needed.

## Overtime application periods

Application types are hard-coded to `REGULAR_OVERTIME`,
`NIGHT_DIFFERENTIAL_OVERTIME`, and `NIGHT_DIFFERENTIAL`, matching backend
calculations. The page shows all three options and disables types with no
calculated minutes or an existing pending/approved application.

Completed attendance is loaded from `/attendance/overtime-attendance-options`
without the dashboard's five-record limit. Only valid completed records within
the current payroll cutoff (inclusive work dates) are offered. The cutoff
contains today's Philippine date and belongs to the employee's currently active
payroll-group assignment. When overlapping cutoffs exist, the latest start/end
dates take precedence, matching dashboard selection. Missing assignment/cutoff
is an explicit error, not a fallback to older records. Submission rechecks the
current cutoff, so a stale form cannot submit
attendance from a previous period. Application history remains visible.

The overtime application page exposes
`requested_start_at` and `requested_end_at` as editable date/time fields in
Philippine time (UTC+08:00), including dates for overnight attendance. Defaults
use post-shift overtime, otherwise pre-shift overtime, or the complete attendance
interval for night differential. Employees may adjust the period within effective
attendance punches; corrected punches take precedence over raw punches.
Requested minutes are read-only and automatically equal the selected period's
whole-minute duration (requested end minus requested start). Changing either
timestamp updates the minutes immediately. Periods exceeding the existing
calculated maximum for the selected type cannot be submitted; shorten the period
instead of manually reducing minutes. Recent Attendance shows application status
only; apply through the dedicated Overtime Application page. Changing the period
does not recalculate the attendance record's overtime classification.

The API accepts both timezone-aware timestamps together and persists them to
`attendance.overtime_applications`; partial, reversed, out-of-attendance periods
and excessive minutes are rejected. Older clients omitting both timestamps retain
server-derived periods. No database migration is required; restart the backend
when deploying this API change.

## Rejected punches and location tracing

Deploy `backend/sql/20261012_create_punch_exceptions.sql` to create
`attendance.punch_exceptions`. Rejections raised during clock/break endpoint
execution are saved in a separate committed transaction, then returned as the
original error. Successful attendance, rejected attempts and payroll remain
separate. Technical server failures are not classified as validation rejections.
Requests rejected before endpoint execution (invalid form fields or dependency
failures) and attempts that never reach the server are not recorded in this table.

`punch_metadata.location_report` contains reported latitude, longitude, GPS
accuracy, server receipt time, and REPORTED/UNAVAILABLE status. Client GPS is
unverified evidence, not proof of location. Metadata also includes the existing
clock policy (channel and client IP) and native/browser source; raw photos,
biometric data, tokens, and signatures are not stored in exceptions.
Optional location failures produce a warning but do not prevent submission.
Kiosks retain their existing exemption: no new GPS permission prompt or GPS
validation. Their exception metadata records the kiosk channel/IP and unavailable
coordinates. Mobile clock geofence requirements are unchanged; breaks request
GPS for tracing but allow missing location. Successful break metadata also
preserves its location report.

Early-clock-in exceptions use `CLOCK_IN_TOO_EARLY` with scheduled start,
earliest permitted start and allowance in `validation_context`. Other validation
errors use `PUNCH_VALIDATION_FAILED`. `identity_verified` is true for the
post-face-match early-clock-in check, otherwise unknown (null). `requested_user_id`
identifies the selected account, not a verified identity; no foreign key prevents
logging attempts against nonexistent accounts. Review fields are stored for a
future review workflow; no exception review UI is introduced here.

## Early clock-in allowance

The WORK segment's `flex_start_minutes` is labeled **Early clock-in allowance
(minutes)**. For assigned schedules, the first WORK segment sets the earliest
permitted shift punch: scheduled start minus the allowance. A 09:00 start with
30 minutes permits punches from 08:30; earlier attempts return a server error
on both web and mobile. Zero permits no early punches. Later punches still use
the existing grace/lateness rule. Scheduled start/end and pre-shift overtime
eligibility are unchanged. Break segments do not use this field.

The allowance is recorded in the clock-in schedule snapshot. Early punches
before midnight for the following day's shift use that day's schedule when
the current day's scheduled shift has ended. Unassigned employees retain the
existing default-schedule behavior; rest days without scheduled times do not
have an early-punch restriction. No database migration is required.

## Flexible attendance breaks

Apply `backend/sql/20261012_add_flexible_break_rules.sql` before deploying this
version. In the schedule editor, each PAID_BREAK or UNPAID_BREAK is assigned to
the first, meal, or second attendance break and a WORK segment. Its time range
is inherited from that WORK segment, including overnight end-day offsets.
Configure `break_minutes` separately from the WORK segment's `paid_minutes`.
Break starts must fall within the inherited window; a late return remains
recordable so excess duration can be computed.

Each paid break has its own allowance. Each unpaid break has its own required
duration. Completed actual break punches determine duration; only minutes above
the configured amount are added to undertime, in addition to early departure.
An unpaid duration remains unpaid; its excess is classified as undertime, not
a second deduction. Paid excess intervals are excluded from overtime and night
differential calculations. An unpaid break without punches uses configured
minutes only with Auto deduct enabled; otherwise clock-out requires the punches.
An unused paid break adds no undertime.
Weekly worked hours exclude the actual unpaid intervals, paid-break excess, and
any configured unpunched automatic deduction, without subtracting undertime a
second time. An unpunched automatic deduction has no assumed time interval and
therefore cannot be assigned to a particular night-differential or overtime window.

Break rules are snapshotted at clock-in in attendance punch metadata. Editing a
schedule does not change an open shift's rules. Existing unconfigured segments
and existing attendance retain their legacy behavior; assign break rules in the
editor to activate this policy for future shifts. The existing overtime dinner
break remains separate from these regular WORK-window breaks.

## Employee overtime applications

The employee dashboard's **My Overtime Applications** card opens the self-service
application page. It is not a shared navigation item; other dashboard roles cannot
open it, and administrator employee-preview mode is read-only.

The page uses completed records from the recent-attendance snapshot, with calculated
regular overtime, night overtime, or night differential minutes. Requests go directly
to `PENDING` for the existing supervisor approval workflow. Pending or approved
applications block another request of the same type; rejected applications may be
requested again. History shows approved and final payable minutes.

Existing backend APIs are reused: `GET /attendance/recent`,
`GET /attendance/overtime-applications`, and
`POST /attendance/overtime-applications/{attendance_id}`. The existing table includes
`attendance_record_id` in addition to the application fields, preserving attendance
validation and supervisor/payroll integration. No new migration is required if the
existing overtime table is already deployed.

## Official business requests

The employee dashboard's **My Official Business** card opens the self-service page
(employee dashboard only; administrator employee-preview mode is read-only). Employees
enter start/end times in Philippine time (sent with a `+08:00` offset), destination,
purpose, and optional client, job order reference, geofence, and company vehicle.
Requested minutes default to the full period and may be reduced. Requests can be saved
as `DRAFT` (editable) or submitted as `PENDING`; drafts and pending requests can be
cancelled. Overlapping draft, pending, or approved requests are rejected by the API.

Supervisors, managers, and administrators review pending requests from the
**Official Business** card on their dashboard. Reviewers can approve the full or a
reduced number of minutes, or reject. Self-approval is blocked, and supervisors only see
employees whose active assignment names them as supervisor.

Backend API (`/attendance/official-business`): `GET /options`, `GET ""`, `POST ""`
(`submit` flag), `PUT /{id}`, `POST /{id}/submit`, `POST /{id}/cancel`, `GET /pending`,
and `POST /{id}/decision`. Writes use `row_version` for optimistic concurrency. The
`attendance.official_business_requests` table is created or completed by
`backend/sql/20261011_create_official_business_requests.sql`, which also adds the
employee/pending indexes. `workflow_instance_id` is currently left empty.

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.
