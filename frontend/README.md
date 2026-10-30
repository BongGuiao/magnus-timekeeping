# React + TypeScript + Vite

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

Under Company Setup, Operational Groups manages company-specific group codes,
display names, sort order, and active status using the existing `company.setup`
permission. Codes are immutable; deactivate rather than delete a group.
New companies start with no groups; add the groups they need in this page.

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
