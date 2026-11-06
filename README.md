# Magnus Timekeeping

## Docker Compose environments

The base `docker-compose.yml` defines the shared services. Combine it with
exactly one environment overlay when starting the stack: the development
overlay provides the HTTP proxy, while the production overlay configures the
production runtime, HTTPS proxy, and certificates.

For a new database, apply the migrations before starting the application as
described in [Database migrations](#database-migrations). Do not apply the
fresh-install baseline to an existing database.

```powershell
# Development: HTTP on http://localhost
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

```

Use the same pair of `-f` options with `docker compose down` to stop that
environment.

### Celery dependency compatibility

Keep the Celery, Kombu, and Redis Python client pins in `requirements.txt`
together. Celery 5.3.6 permits newer Kombu releases whose Redis transport is
incompatible with the pinned Redis 5.0.1 client. Kombu is pinned to 5.3.7 to
prevent workers from crash-looping with `kombu.exceptions.VersionMismatch`.
The Python client version is separate from the Redis server image.

After changing these dependencies, rebuild the backend services using the same
environment overlay as the running stack:

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build web celery_worker celery_beat
docker exec -w /app/backend celery_worker celery -A celery_app:app inspect ping --timeout 10
```

### Uploading leave entitlements

Users with `leave.manage` can download a CSV template and upload balances from
either the Entitlements tab of an employee record or the Employee Entitlements
page. A file can include multiple employees, including employees other than the
one currently open. Save it as UTF-8 or Excel CSV; format employee numbers as
text in Excel so leading zeroes are preserved.

Each row requires an employee number, leave code, entitlement year (1900-2200),
and all nine balance amounts. Enter `0` rather than leaving an amount blank.
The columns are:

```csv
employee_no,leave_code,entitlement_year,opening_balance,granted,accrued,carryover,adjustment,used,reserved,expired,converted
0001,VL,2026,0,12,0,0,0,1,0,0,0
E002,SL,2026,0,5,0,0,0,0,0,0,0
```

The employee numbers and leave codes above are examples and must match records
in the system. Amounts use the unit configured for each employee's leave type:
days, hours, or minutes (one day is eight hours). Minute values must be whole;
day and hour values are rounded to the nearest minute. Only opening balance
and adjustment can be negative. Available balance is calculated automatically.

Check the file and review the create/update preview before applying it.
Matching employee, leave type, and year records are **replaced with the
supplied amounts**, including used and reserved balances. This does not change
existing leave ledger entries. Employees must have an active employment
assignment and satisfy the same company, active leave type, and service
eligibility rules as a manual entitlement. A file is limited to 1 MB and 1,000
rows; any error rejects the entire file. If an existing balance changes after
the preview, check the file again before applying it. If an entitlement already
uses an older leave-type record with the same code and year, resolve that
record first; the upload will not silently create a duplicate.

The optional PostgreSQL upload tests require `ENTITLEMENT_UPLOAD_TEST_DATABASE_URL`
to point to an **empty, disposable** database named `entitlement_upload_test_*`.
They create and remove test schemas and must never target the application database.
HTTP endpoint tests also require the optional `httpx` test dependency.

### Database migrations

Alembic migrations run as an explicit deployment step; the API does not create
or alter tables during startup. For a new database, apply the initial schema
and seed catalog before starting the application:

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --build --rm web alembic -c alembic.ini upgrade head
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

This creates the current model schema, the initial system roles and
role-permission grants, company setup types, payroll parameter defaults, and
one `XYZ Company` record. Seed inserts use `ON CONFLICT DO NOTHING`, so they
do not overwrite existing company, role, permission, or grant records.

For production, build the release image, run the migration explicitly, then
start the release:

```powershell
docker compose -f docker-compose.yml -f docker-compose.prod.yml build web
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm web alembic -c alembic.ini upgrade head
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Always take a database backup before a production migration. The initial
baseline is for a new, empty database and must not be run against an existing
production database. Existing installations need a separately reviewed
baseline for their current schema and seed state before Alembic is used there.
Do not run the initial `upgrade head` or blindly use `alembic stamp head`
against an existing installation; stamping records a revision but does not
apply or verify its changes.

For the organization-approval routing migration, stop **all application
writers** (API instances, workers, scheduled jobs, and integrations) before
running the migration. Start only the matching new application version after
the migration completes; do not run old and new writers together. An old
writer running after the backfill can create a pending request without a
routing record, which the new application deliberately refuses to approve.
Back up the database first. The migration cannot be downgraded after
organization-assigned or unresolved routes have been recorded.

For an existing installation **without Alembic tracking**, review
[manual_org_unit_approval_routes.sql](backend/sql/manual_org_unit_approval_routes.sql)
against its actual baseline before authorizing execution. This transactional
script applies only revision `f4a6b8c0d2e4`, adds the schedule-row company snapshot,
and preserves existing request routing as `LEGACY`. It does not create or stamp
Alembic state, assign org-unit approvers to old requests, or reconcile earlier
schema differences. It refuses tracked databases, missing prerequisite tables
(including the prior attendance merge-audit tables), and existing or partially
installed routing schema. Run with `psql`'s `ON_ERROR_STOP=1` only after a backup
and stopping every writer as described above; a lock timeout aborts the upgrade
rather than waiting indefinitely. Restart only the matching release after
commit. Do not remove the routing schema after new routes have been recorded.

For an untracked installation, also review
[manual_revoke_supervisor_approval_permissions.sql](backend/sql/manual_revoke_supervisor_approval_permissions.sql)
and apply it after the routing script, while writers remain stopped. It mirrors
revision `a7b9c1d3e5f7`: the SUPERVISOR role alone no longer grants team approval
permissions; active org-unit managers receive them through the application.
Neither manual script should be applied to an Alembic-managed installation.

For each schema change, update the SQLAlchemy model, generate and review a
revision, and then apply it:

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm web alembic -c alembic.ini revision --autogenerate -m "describe schema change"
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm web alembic -c alembic.ini upgrade head
```

Autogenerated revisions must be reviewed and adjusted for data migrations,
custom PostgreSQL objects, and any destructive operation before deployment.
Do not delete the PostgreSQL Docker volume when applying migrations.

### Attendance concurrency checks

Clock-in/out and break punches serialize changes for the same account using a
PostgreSQL row lock; different employees do not share that lock. An overlapping
clock request is rejected if another request closed the shift while it was
waiting, instead of accidentally starting a new shift. This is not a general
idempotency guarantee for later retries; clients should refresh attendance after
an uncertain response before resubmitting.

Attendance face extraction runs outside the API event loop, with at most one
extraction per API worker. Excess requests wait rather than starting an
unbounded number of CPU-heavy jobs. Punch dashboard-refresh publishing also
runs outside the event loop. Attendance is committed before the refresh/audit
steps; a dashboard refresh is not proof of persistence.

Run the focused checks with the existing backend container:

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T web python -m unittest backend.tests.test_attendance_concurrency backend.tests.test_punch_use_cases backend.tests.test_early_clock_in backend.tests.test_flexible_break_rules backend.tests.test_face_matching_rules -q
```

Database concurrency tests are skipped unless
`ATTENDANCE_LOAD_TEST_DATABASE_URL` points to a separately migrated, disposable
PostGIS database named `attendance_load_test_*`. Never use the application or
production database. These tests create synthetic fixtures and a temporary
delay trigger for an overlapping-insert test, then clean them up. They verify
100 simultaneous mixed punches (50 in, 50 out), committed record counts, and
overlapping punches for one account. Image extraction is stubbed; face matching,
attendance rules, SQLAlchemy sessions, and PostgreSQL writes are real.

These are persistence/concurrency checks, not a production capacity guarantee.
Before rollout, load-test the complete HTTP endpoint with representative images,
enrollment counts, geofences, device proofs, network conditions, and production
hardware. Include upload, face-processing, queue, and audit latency; a successful
database-only test does not measure those stages.

### Production deployment

The production overlay builds the frontend as static assets served by Nginx,
removes application source-code bind mounts, keeps PostgreSQL and Redis
unpublished, waits for those services to become healthy, and disables the
development Elasticsearch logging stack by default. The `static` directory
remains mounted for employee face images. Protect it and the `.env` file on
the production host, and back up the database and uploaded files regularly.

On the production host, configure `.env` with unique production credentials
and application settings. Do not commit this file. Ensure DNS for
`mbsione.com` and `www.mbsione.com` points to the host and that inbound ports
80 and 443 are allowed. The TLS-enabled Nginx configuration requires a
certificate to exist before the stack can start; issue the initial
Let's Encrypt certificate using the HTTP-01 webroot challenge before starting
the production stack. The Certbot service renews existing certificates; it
does not issue the first one.

For a new, empty production database, apply the initial migration before
starting the application. Do not run this baseline against an existing
production database; establish its baseline separately as described above.

```powershell
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --build --rm web alembic -c alembic.ini upgrade head
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

Use the same Compose files and order to view logs or stop the stack:

```powershell
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
```

Elasticsearch, Kibana, and Filebeat are excluded by default in production
because the base configuration is intended for development. Do not enable the
`observability` profile in production until Elasticsearch authentication,
network access, and log collection have been configured securely. Back up the
database before applying reviewed migrations.

### Local holiday date scopes

Apply `backend/sql/20261027_add_local_holiday_geographic_scope.sql` before
deploying this change. A calendar is a shared company/year container; enter
each holiday date once. When a date is assigned type `LOCAL`, select its
applicable region and province in the location modal. For NCR, select one of
the four districts (1st through 4th) instead; assign each NCR location its
district in Location maintenance. No city-to-district mapping is assumed.
Leave municipality blank to cover **all municipalities in the selected
province or NCR district**; select a municipality to narrow the holiday to
that one municipality. If a fiesta applies to only
several municipalities, add a separate LOCAL date record for each municipality
using the same date and holiday name. Other holiday types remain nationwide.
Existing calendar-level scopes are transferred to their local holiday dates by
the migration.

Employees may be assigned multiple locations where they can punch. Set one of
those as the assignment's primary work location; local holiday eligibility
uses that primary location, not the location where the employee punched.
Choose the primary location in the assignment form or provide
`primary_location_code` in an employment-assignment CSV (it must also appear in
`location_codes`). If omitted from a CSV, the first location remains the
backward-compatible default. Existing attendance records are not automatically
reclassified; the new primary-location rule applies when attendance day types
are determined going forward.

Declared local holidays are non-working days for attendance and absence
calculations. If worked, their minutes are classified as special-day work and
paid using the payroll group's `SPECIAL_DAY` earning rule; overtime uses
`SPECIAL_DAY_OT`. These are configurable full-rate multipliers per payroll
group (for example, `1.30` means 130% of the base rate). Confirm the applicable
rates in Earning Multipliers for every production payroll group.

### Regular holiday pay attendance rule

Apply `backend/sql/20261101_holiday_pay_attendance_rule.sql` (Alembic revision
`e1b2c3d4f5a6`) before deploying this change. An employee who does not work on
a regular (`RH`) or double (`DBL`) holiday is paid for it only when present, on
paid leave, on approved official business, or schedule-credited on the workday
immediately before the holiday. Rest days and other non-working days are
skipped when locating that workday (up to 14 days), and work performed on a
skipped day, such as the first of two successive regular holidays, counts as
presence. Days that have not happened yet, or fall before the employee's
employment, never disqualify.

Set the rule per company in **Company Parameters → Regular holiday pay
attendance**: `BEFORE_ONLY` (default, the DOLE rule) or `BEFORE_AND_AFTER`
(company policy or CBA that also requires the following workday). Recalculate
open cutoffs after changing it.

Daily- and hourly-rated groups are paid unworked holidays through the
`UNWORKED_HOLIDAY` (default `1.00`) and `UNWORKED_DOUBLE_HOLIDAY` (default
`2.00`) earning rules, crediting the payroll group's standard minutes per day.
The migration seeds both rules for every payroll group that already has earning
rules; configure them for new groups. Monthly-rated salaries already include
unworked holidays, so a disqualified holiday is instead deducted through
`UNPAID_TIME_DEDUCTION`. Cutoff results expose `unworked_holiday_minutes`,
`unworked_double_holiday_minutes`, and `disqualified_holiday_minutes`.

## Statutory contribution and tax schedules

Before deploying the program-specific schedule calculations, apply
`backend/sql/20261021_add_program_specific_statutory_calculation_fields.sql`.
New withholding-tax schedules use taxable pay for each payroll period; for a
semi-monthly schedule, the semi-monthly tax brackets are applied on every
calculated cutoff without requiring a second cutoff record to exist first.
Legacy schedules retain annual year-to-date calculation. Pag-IBIG brackets use
monthly basic salary rates and separate employee/employer monthly caps. Verify
all bracket values against the applicable official source before activating a
schedule.
Existing Pag-IBIG brackets do not receive assumed caps during migration; create
and activate a draft with the verified caps before using the new calculation.

The Alembic seed creates the SSS schedule published as effective January 2025
(SSS Circular No. 2024-006) as a DRAFT and inserts its 61 brackets only when
they are absent. It never replaces existing brackets; if an existing draft
does not match the official table, the migration fails rather than altering
the data. Review the schedule in Payroll → Statutory Setup and verify it
against the official SSS source before activation. The official page may
publish a newer schedule; this seed does not claim to represent 2026 rates.
The current payroll schema stores combined employee/employer SSS amounts
(including MPF) and the employer EC amount; it does not report separate SS
and MPF subtotals. PhilHealth and Pag-IBIG bracket tables are not seeded until
their official datasets are provided and verified.

The Alembic seed also creates the semi-monthly withholding-tax schedule
effective 2026-01-01 as a DRAFT using the six bands and rates listed at
[MPM's BIR tax table](https://mpm.ph/bir-tax-table/). It must be reviewed
against the applicable BIR issuance before activation. The bracket amounts
are per semi-monthly payroll period; the schedule uses the repository's
₱90,000 annual shared exemption for qualifying 13th-month and other benefits.

`backend/sql/manual_seed_sss_2025_contribution_table.sql` remains available
for manually creating or completing that same DRAFT schedule in installations
that are not yet using the Alembic seed revision.

The optional year-end WTAX reconciliation is controlled from Payroll → 
Statutory Setup → Company Parameters for the selected company. It defaults to off.
When enabled, the final active December cutoff calculates annual liability
using the active semi-monthly table at 24 periods per year, then compares that
amount with year-to-date withholding. A positive difference is withheld; a
negative difference is returned as a refund. Recalculate prior payroll cutoffs
before the final December cutoff so the year-to-date figures include all
earlier payroll results. Apply
`backend/sql/20261021_create_payroll_system_parameters.sql` before deploying
this feature.

Payroll → Statutory Setup provides a company-specific statutory contribution
deduction timing alongside the SSS, PhilHealth, and Pag-IBIG schedules.
For semimonthly payroll with "Every payroll cutoff", First Half selects each
program's bracket using half-month compensation and saves the full bracket
result (base times rate plus fixed amounts). Monthly-rated employees use
monthly base salary / 2; daily-rated employees use daily base rate times the
payroll group's annual divisor / 24. Second Half selects the bracket using
monthly compensation (monthly base salary, or daily base rate times the annual
divisor / 12), then subtracts the latest current READY First Half contribution
for that employee in the same payroll group whose cutoff ends before the
Second Half cutoff starts. This follows the explicit First Half/Second Half
designation even across calendar months; the latest eligible First Half is
used rather than summing older cutoffs. Employee and
employer shares are reconciled separately. First Half ignores earlier amounts
without deleting historical payroll; if no READY First Half contribution exists,
Second Half subtracts zero and charges the full monthly amount.

"Final cutoff of each month only" charges zero on First Half and the full monthly
bracket result on Second Half, without subtracting prior contributions. The
cutoff's explicit First Half/Second Half designation controls these rules;
missing designations place payroll on HOLD. Other payroll frequencies retain
their frequency-based allocation for every-cutoff timing.

Pag-IBIG retains its salary-times-rate calculation and configured monthly caps.
The cap applies to the First Half bracket result too, so reaching the monthly
cap in First Half can leave zero for Second Half. Absences do not change the
salary basis. Deductions exceeding available cash pay still place payroll on
HOLD, as do saved First Half contributions exceeding the new monthly total.
Recalculate First Half before Second Half after changing compensation,
brackets, or timing; saved later payroll results are not automatically updated.
Existing companies default to every cutoff.

Taxable one-time bonus types can separately use either pay-period withholding
or year-end settlement. Year-end-settled bonuses remain part of payroll taxable
income and year-to-date taxable totals, but their withholding is deferred until
the final December reconciliation. This option requires the year-end WTAX
setting enabled and a semi-monthly tax schedule; otherwise payroll holds when
such a bonus is present. Existing benefit types default to withholding in the
pay period. Apply
`backend/sql/20261021_add_bonus_tax_withholding_timing.sql` before deploying
this option.

Per-cutoff employee benefits can be imported from the benefits page using a CSV
template. Each row identifies an employee by employee number and an active
benefit type by code, with amount and optional notes. The upload is atomic:
unknown employees, benefit types, duplicate rows, or invalid amounts reject
the whole file. Matching existing employee/type entries are updated, and
missing entries are created. Recalculate payroll for the cutoff after import.

13th-month pay can be enabled in Payroll → Statutory Setup → Company Parameters for the selected
company. Its
separate calculation run uses current READY payroll results for the selected
tax year and computes eligible regular/basic and paid-leave earnings divided
by 12. It includes employees with year earnings even if they are no longer
active. Lates, undertime, and unpaid absences reduce the benefit only when
they already reduce the recorded basic earnings. Overtime, night differential,
allowances, reimbursements, and other benefit lines are excluded from the
calculation base. The taxable portion is the amount exceeding the remaining
shared benefit exemption on the active tax schedule; the recommended setting
is ₱90,000 for the calendar year, shared with other qualifying benefits
(Presidential Decree No. 851 and National Internal Revenue Code
Section 32(B)(7)(e), as amended). The calculation is based only on current
READY payroll results, so confirm all applicable cutoffs are calculated before
relying on the output. Recalculate the 13th-month run after fixing source
payroll results, then recalculate the final December cutoff so taxable excess
is included in the WTAX true-up for employees with a current result in that
cutoff. The separate 13th-month calculation does not itself post payment or
withholding; employees who left before the final December cutoff need their
final-pay tax reconciliation handled separately. Apply
`backend/sql/20261021_add_thirteenth_month_calculation.sql` before deploying
this feature, then apply
`backend/sql/20261022_company_payroll_system_parameters.sql`. The company-scoped
migration copies the existing WTAX and 13th-month switches to each existing
company. Apply
`backend/sql/20261022_add_thirteenth_month_cutoff_coverage.sql` to save the
company's selected From/To payroll cutoff dates on each 13th-month run. For each
tax year, enter the date range of the last payroll cutoff to include; completed
payroll results through that cutoff are used. This lets companies releasing
13th-month pay by December 15 use a November cutoff, or select a December cutoff
when December earnings should be included. Also apply
`backend/sql/20261022_add_company_payroll_parameters_permission.sql` to add
`payroll.company_parameters.manage`. This dedicated permission is granted by
default to HR Admin and System Admin, but not Supervisor or Manager roles.
Company-scoped role assignments can manage only their assigned company; global
System Admin assignments can manage any company. The System Parameters company
selector lists only companies available to the user's active permission
assignments.

## Employment assignment CSV import

Employee form lookup dropdowns support searching by code or name, mouse selection,
and arrow-key/Enter selection. Escape closes the options without changing the
selected value. Simple fixed choices and the read-only role company remain unchanged.

From Employees, open an employee form and select the **Assignments** tab.
Use **Import Assignments** in the tab header to upload assignments for existing
employees. Download the CSV template for the supported columns. Required
columns are `employee_no`, `company_code`, `employment_type`,
`employee_category`, `hire_date`, and `effective_from`. Optional references
use company-scoped codes for `org_unit_code`, `payroll_group_code`, and
semicolon-separated `location_codes`; supervisors are identified by
`supervisor_employee_no`. Dates use `YYYY-MM-DD`.

The importer validates the complete file before saving. Duplicate
employee/company pairs in the file, an existing assignment for that
employee/company, or any other invalid row rejects the entire upload. The
server creates all accepted rows in one database transaction, with a maximum
of 500 rows per file.

# During deployement include runing the 
# nginx in the dev and prod env. 

## Payroll salary basis

For a `MONTHLY` rate type, payroll pays the monthly base according to pay
frequency: monthly salary divided by 2 for semimonthly, by 1 for monthly, by
26/12 for biweekly, or by 52/12 for weekly. Monthly-rated cutoff pay is reduced
by unpaid scheduled minutes (including absences, unpaid leave, lateness, and
undertime) at the daily equivalent derived from the annual divisor and standard
minutes per day. Paid leave and approved official business count as covered
scheduled time. The calculation breakdown shows the monthly cutoff base and
unpaid-time deduction separately. Daily and hourly rates continue to be
calculated from approved time minutes.

## Payroll approval

Payroll can be approved only after a current calculation exists, every employee
result is READY, and the source time results remain acknowledged. Approval
records the approver and locks the cutoff against recalculation and edits.
Administrators with `system.manage` can unlock a cutoff for corrections; both
approval and unlock actions are audited. Apply
`backend/sql/20261023_add_payroll_cutoff_approval_permission.sql` to add
`payroll.approve` and grant it to HR and system administrator roles.

## Organization-based employee approvals

New leave, overtime, official-business, attendance-correction, emergency
schedule, schedule-upload, and invalid-attendance approvals use the manager
of the employee's currently effective org unit. Ordinary members use their
own-unit manager. A manager's own request uses only the immediate parent-unit
manager. This is a single approval, not a chain up to the President.
A manager cannot approve their own request.
For a schedule batch uploaded by its manager, the uploader is excluded and
only the immediate parent is considered. A missing, inactive, or non-independent
manager holds the request unresolved; the system does not search higher ancestors.

Each employee must have one current company/org-unit assignment, and the
hierarchy must contain active units in the same company without cycles. The
selected manager needs an active employee-linked account. Being the active
manager of an org unit grants the team approval permissions
`leave.approve_team`, `overtime.approve_team`,
`official_business.approve_team`, `attendance.approve_corrections_team`,
`schedule.approve_emergency`, `schedule.approve` (schedule upload batches),
and `attendance.read_team` (invalid attendance); no role grant is needed.
The `SUPERVISOR` role alone does not authorize new approvals. Existing role-based
team read access and legacy pending-request scope are preserved.
The optional Position ID does not grant approval authority. A configured
manager who lacks an active account or a required role permission is a
configuration error; the system does not silently skip them for another
manager.

The approver is saved when the request is submitted and does not change when
the org chart changes. Requests that were already pending before the migration
continue using their previous supervisor-based scope, but self-approval is blocked.
An organization-routed leave cannot be approved through the generic
leave-update endpoint; use its
assigned approval queue. If an approver's account is linked to a different
employee or their roles change, their current account and permissions govern
access; sign in again after an employee-link change.

Changing an org-unit manager does not reassign existing pending requests. If the
saved approver becomes inactive or loses the required permission, restore their
access or cancel and resubmit the request where supported. There is currently
no reassignment control for an already assigned route; plan manager transitions
accordingly. Recovery applies only to currently unresolved, still-pending requests;
it never replaces an already assigned organization or legacy approver.

When an org approver cannot be found, new requests are saved pending with
`UNRESOLVED` routing, rather than choosing an unrelated supervisor. Attendance
punches are still recorded. Requesters see a dashboard alert directing them to HR.
Users with `employees.manage` see unresolved requests across all seven resource
types (up to the latest 100 per type), with **Retry routing** after correcting the
configuration. Alternatively, HR can select an independent active org-unit manager
and supply an audit reason. The selected manager must have an active employee-linked
account and manage an active unit in each affected company. The requester, schedule
uploader, and assigning HR employee cannot be selected. This assigns one reviewer,
not an approval; the usual approval queues remain in use. Failed recovery retains
the alert and displays the routing error. Existing invalid-attendance HR endpoints
remain available for compatibility.

An **Approval routing alerts unavailable** message means the lookup failed;
it does not confirm that requests lack an approver. A missing endpoint (HTTP 404)
indicates that the running backend does not provide the new routing API. Complete
the reviewed database upgrade and deploy the matching backend version together;
do not restart the new backend against the old schema. Use **Retry loading
alerts** after resolving the deployment or connection problem.

These rules apply to new submissions only. Payroll approval rules are unchanged.

The optional PostgreSQL routing tests require
`APPROVAL_ROUTING_TEST_DATABASE_URL` to point to a separately migrated,
disposable database named `approval_routing_test*`. They roll back their
synthetic fixtures and must never target the application database. When running
them alongside other database tests, also set `DATABASE_URL` to that same
disposable database.

## Schedule approval policy

Team Schedule Upload is available from the Timekeeping menu and an employee
form's **Schedule** tab. In team mode, employees must belong to org units
managed by the uploader. In HR_ADMIN mode, the existing
`supervisor_employee_code` CSV column must contain each employee's org-unit
manager; one batch is created per specified manager. If a batch would require
more than one approver, split it into separate uploads. Schedule upload
approvals are available from the Timekeeping menu to users with
`schedule.approve`. A saved batch keeps its assigned approver if the org chart
changes, but must be rejected and reuploaded if an employee changes company.

The company-level **Require schedule approval** parameter controls direct
employee schedule assignments and supervisor schedule-upload batches. It is
enabled by default. When enabled, direct assignments remain drafts and uploads
wait for an independent reviewer; when disabled, new direct assignments and
uploads are approved immediately and do not require a manager's linked account
or approval permission. Changing the parameter does not automatically
approve existing drafts or pending uploads. For a batch spanning multiple
companies, approval is required if any included company requires it. Apply
`backend/sql/20261024_add_schedule_assignment_approval_parameter.sql`.

## Schedule-credited attendance

Employee schedule assignments support an **Attendance mode** setting:
**Punch required** remains the default, while **Schedule credited** credits
scheduled work time without clock punches. For schedule-credited days, approved
paid/unpaid leave and approved official business are counted separately and
reduce the remaining scheduled-work minutes, preventing those minutes from
being counted twice. Lateness, undertime, and absence caused only by missing
punches are not recorded for this mode. Actual punch timestamps, when present,
remain actual timestamps and are not fabricated for no-punch days.

The mode is effective over the schedule assignment's existing date range.
Changes remain subject to the configured schedule-approval policy and are
audited. Existing assignments retain **Punch required** after applying
`backend/sql/20261028_add_schedule_credited_attendance_mode.sql`.

## Payroll cutoff designation

For a two-cutoff payroll group, explicitly mark each cutoff as **First cutoff**
or **Second cutoff** in Payroll Cutoffs. The designation follows the payroll
cycle and does not depend on the dates being inside one calendar month; for
example, the first cutoff can run from September 25 through October 10 and the
second from October 11 through October 26. Recurring benefits, employee
deductions, and loan repayments configured for the first or second cutoff use
this designation. Every-cutoff schedules do not require it.
Existing cutoffs are left undesignated by the migration and must be assigned
before calculating payroll when a first-half or second-half schedule applies.
Apply `backend/sql/20261023_add_payroll_cutoff_half_designation.sql`.

## Attendance finalization before payroll

Payroll Cutoffs has an **Employee filing deadline** and an **Approval
deadline** (the existing `attendance_deadline`). Both must be timezone-aware and
after the last cutoff day ends in Philippine time. Approval must be on or after
filing; setting a filing deadline requires an approval deadline.

After filing closes, employees cannot create, edit, submit, or cancel OT,
leave, or official business requests covered by that cutoff. Emergency schedule
requests and employee attendance recalculation also respect the filing window.
Assigned approvers can still approve or reject submitted requests until approval closes.
The exact deadline instant remains allowed. Finalized attendance or locked
payroll closes both windows. Requests spanning cutoffs must satisfy every
applicable cutoff. Dates without a matching employee cutoff retain the existing
unrestricted deadline behavior.

Existing cutoffs with no separate filing deadline use `attendance_deadline`
for both stages. Leave filing, previously missing the cutoff deadline check,
now follows this policy too. Employee application screens and approval review
screens display the applicable deadlines in Philippine time. Reviewers see
deadlines for their direct reports and employees with pending requests assigned
to them through org-unit routing.

**Production schema prerequisite:** apply
`backend/sql/20261101_employee_filing_deadline.sql` to update **payroll.cutoffs**
before deploying this backend. Alternatively, for Alembic-managed installations,
upgrade through revision `f2c3d4e5a6b7`; do not apply both migration paths blindly.
If the holiday-pay change has not yet been deployed, also apply
`backend/sql/20261101_holiday_pay_attendance_rule.sql`, which updates
**payroll.company_system_parameters**, **payroll.employee_cutoff_results**,
and **payroll.earning_rules**. The deadline migration leaves existing filing
deadlines NULL; HR can set separate dates through Payroll Cutoffs.

Attendance for a payroll cutoff must be calculated and reviewed in Attendance
Detail before an HR administrator can finalize it. Finalization is available
only after the cutoff's attendance deadline and requires the `attendance.finalize`
permission. The finalization action records the actor and time; attendance changes
and recalculation are then blocked, and payroll calculation remains unavailable
until the cutoff is finalized. Payroll approval remains a separate action that
locks the completed payroll. Apply
`backend/sql/20261028_add_attendance_finalization_workflow.sql` before deploying.
The migration treats cutoffs already locked or past their attendance deadline as
finalized to preserve existing cutoff behavior.

## Missing-punch attendance corrections

### Manual database backups

**Account options (three dots) → Database Backup** is available only to
SYSTEM_ADMIN / SYSTEM_ADMINISTRATOR accounts. The backend checks the user's
current active roles in PostgreSQL on every request; HR_ADMIN and a cached
administrator token alone do not grant access. No new permission tables or
database migration are needed.

Click **Create & download backup**, keep the tab open, and save the browser
download to your computer. The custom-format `.dump` contains the configured
PostgreSQL database's schema and data, including all companies. It does not
contain uploaded files, Elasticsearch data, or cluster-wide role definitions.
Downloads are unencrypted: protect them with encrypted local storage and restricted
access, and keep another copy on separate/off-site storage. They are not public files.

The backend runs PostgreSQL 16 `pg_dump` (matching the Compose database version)
without putting the database password in command arguments. It uses a private
temporary directory and removes the archive after response delivery, or on failure.
Only one dump generation runs at a time across workers, enforced by a PostgreSQL
transaction advisory lock. The five-minute generation limit is for manual backups;
larger databases require an operational backup job. Dumps are consistent snapshots,
but consume server CPU, I/O and temporary disk space. A killed container can leave
temporary files until its filesystem is removed; administrators should monitor
private temporary storage and clean only inactive backup directories.

**Deployment:** rebuild the backend image to install `pg_dump` / `pg_restore`
and their runtime libraries, then recreate the web service. Deploy the updated
frontend and Nginx configuration; the exact `/auth/database-backup` location
allows a 360-second response timeout without changing other API timeouts.
No Docker socket mount is required. The PostgreSQL client must be upgraded
alongside any future server major-version upgrade.

Test backups in a separate database, never by overwriting production:

```text
pg_restore --list magnus-database-YYYYMMDDTHHMMSSZ.dump
pg_restore --exit-on-error --dbname=<separate-test-database> <backup-file.dump>
```

Provision the test server's roles/extensions first when required by the archive.
This feature does not restore production or schedule automatic backups. Browser
download initiation is not proof the user saved the file; verify local file size
and test recovery. PostgreSQL backup failure returns an error, not a partial file.

Employees with `attendance.correct_own` can file **Missing-Punch Corrections**
from their Employee Dashboard using **Apply for Attendance Correction** in
**My actions & records**, next to **Apply for Leave**. The correction action is
also available directly below **Apply for Leave** inside My Leave Requests.
The button opens the correction detail panel. Load the work date, enter the actual missing
clock-in and/or clock-out, provide a reason, and optionally supply a ticket,
job-order, or other evidence reference. Reference text is stored; this feature
does not upload attachments. No scheduled clock-out is automatically credited.
At least one existing clock-in or clock-out is required on that work date.
Both punches missing, including dates without an attendance row, must be
handled by HR outside this missing-punch workflow.

Requests are limited to scheduled, punch-required working days after the shift
ends. Enter times in Philippine time; clock-in must be on the selected work
date, clock-out may be on the next day, and the interval cannot exceed 24 hours
or extend into the future. Existing punches and recorded break intervals are
preserved. Schedule-credited days do not need corrections. Locked or invalid
attendance must first be resolved through the existing HR/review process.

**Supervisor/Manager Dashboard → Team overview → Review queue → Attendance corrections** shows the
pending request count when the role has team approval rights. Click the button to open or hide **Attendance Correction
Approvals**, which shows pending requests assigned to the reviewer, original and requested times, reason, and supporting
reference. `attendance.approve_corrections_team` permits Approve/Reject with
mandatory review notes. Self-approval, duplicate pending requests, stale
versions, and approval after punches have changed are rejected. Employees
can view their request history and refile a rejected request within the filing
window.

Supervisor and Manager dashboards use compact, color-accented attendance metrics and a grouped,
permission-filtered review queue. Opening a review category closes the previous
review list and Team Hours; opening Team Hours closes any active review list.
The entire Team Hours card is hidden until the top Hours metric is selected.
Supervisor punch locations use a colored Review queue button, with the full
panel hidden until selected; switching categories also hides this panel.
The existing supervisor role and team attendance permission requirements remain;
the duplicate team leave summary is removed.

All dashboard roles share the standard full-width compact, colored overview
with a prominent personalized Welcome heading instead of a separate hero banner.
The compact header retains a purple Today card displaying the Philippine date.
Administrator metrics and reviews use the same presentation and exclusive panel
behavior; offline attendance review is opened from its Review queue button.
Existing permissions remain required. Approval queues follow the org-unit
routing above; other dashboard data retains its existing scope.
Dashboard navigation actions use an arrow icon; expandable records use a
chevron. Unloaded counts say **Not loaded** instead of a dash, and positive
pending counts are emphasized without changing their order. Failed approval-list
loads show an error rather than a misleading zero/empty state. Approval buttons
use green, rejection buttons soft red, and filing buttons indigo, with visible
keyboard focus and disabled states.

The Employee dashboard uses the same full-width, color-accented overview with
compact live attendance and leave metrics. **My actions & records** groups
permission-gated Leave, Attendance Correction, OT, OB, and Payroll Review actions.
Leave balances, leave requests, recent attendance, work hours, corrections, and
holidays/announcements open one detail panel at a time; clicking the selected
record again hides it. Attendance opens expanded so a second click is not needed.
The team **Recorded absences** metric counts attendance records marked absent
this month, excluding leave days and shifts before their expected clock-in time;
dates without an attendance record are not
included. It is not a count of clock-out-only records.
Records without an expected clock-in time retain the existing absence treatment.
**Missing clock-out** excludes shifts before their expected clock-out time and
retains the existing six-hour grace period after that time before flagging an
incomplete clocked-in record.

Filing follows the employee filing deadline; decisions follow the supervisor
approval deadline. Finalization and payroll locking close both windows.
Approval fills only missing corrected-punch fields, leaves raw punches intact,
records the reviewer/time, and recalculates lateness, undertime, worked hours,
night differential, and potential overtime using the saved schedule and break
policy. It does not approve overtime; existing non-rejected OT applications
must be resolved first. Approval invalidates the applicable cutoff attendance
calculation and resets the affected employee's confirmations and payroll status
to PENDING/HOLD. HR must recalculate and review cutoff attendance before
finalization, and recalculate payroll if necessary.

Attendance finalization now rejects pending correction requests and incomplete
punch-required attendance records. Explicit absence records and
schedule-credited days are excluded from the incomplete-punch check. A day
with no attendance row and no correction request is not automatically assumed
to be a missing-punch case. If a deadline expires before resolution, authorized
HR must extend the appropriate deadline on the still-unfinalized cutoff;
there is no silent late-approval or locked-payroll bypass.

**Production prerequisite:** apply
`backend/sql/20261101_attendance_correction_requests.sql` before restarting the
backend. It creates **attendance.correction_requests** and updates
**identity.permissions** and **identity.role_permissions**. No existing punches
are backfilled. Alternatively, Alembic-managed installations can upgrade through
revision `a3d4e5f6b7c8` instead. Employee filing is granted by default to EMPLOYEE
and SUPERVISOR roles; team approval is granted only to SUPERVISOR. Other roles
need explicit grants and still cannot bypass direct-report scoping. Refresh
authorization (sign out/in if necessary) to show the new dashboard panels.

## Employee loans

Payroll management includes employee loans with a manually assigned, unique
reference number, principal, installment amount, and deduction schedule. Choose
the first cutoff, second cutoff, or both cutoffs. Loan installments are included
in payroll calculation and capped at the outstanding balance. A saved payroll
calculation records one repayment per loan and cutoff; recalculating that cutoff
replaces its repayment rather than counting it twice.

Retiring a loan stops future deductions and preserves its balance and payment
history. Restructuring retires the current loan and creates a linked replacement
record whose principal is the old loan's unpaid balance plus any additional
principal. Apply `backend/sql/20261023_create_employee_loans.sql` before
deploying the feature.

Recurring employee benefits are assigned per employee with an amount per
occurrence, effective dates, and a schedule of first cutoff, second cutoff, or
every cutoff. Existing benefit entitlements keep their prior benefit-type
schedule when upgraded. Apply
`backend/sql/20261023_add_schedule_to_employee_benefit_entitlements.sql` to
store the cadence on each employee entitlement.
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build