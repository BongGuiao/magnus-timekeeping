# React + TypeScript + Vite

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
