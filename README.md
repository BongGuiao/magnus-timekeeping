# Magnus Timekeeping

## Docker Compose environments

The base `docker-compose.yml` defines the shared services. Combine it with
exactly one environment overlay when starting the stack: the development
overlay provides the HTTP proxy, while the production overlay configures the
production runtime, HTTPS proxy, and certificates.

```powershell
# Development: HTTP on http://localhost
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

```

Use the same pair of `-f` options with `docker compose down` to stop that
environment.

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

Start and inspect the complete production stack with:

```powershell
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
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

`backend/sql/manual_seed_sss_2025_contribution_table.sql` creates or completes
the SSS schedule published as effective January 2025 (SSS Circular No.
2024-006). It creates a DRAFT schedule, accepts only already-entered brackets
that exactly match the official table, and can be rerun safely. Review the
schedule in Payroll → Statutory Setup and verify it against the official SSS
source before activation. The official page may publish a newer schedule; this
seed does not claim to represent 2026 rates. The current payroll schema stores
combined employee/employer SSS amounts (including MPF) and the employer EC
amount; it does not report separate SS and MPF subtotals.

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

From Employees, use **Import Assignments** to upload assignments for existing
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

## Schedule approval policy

The company-level **Require schedule approval** parameter controls direct
employee schedule assignments and supervisor schedule-upload batches. It is
enabled by default. When enabled, direct assignments remain drafts and uploads
wait for an independent reviewer; when disabled, new direct assignments and
uploads are approved immediately. Changing the parameter does not automatically
approve existing drafts or pending uploads. For a batch spanning multiple
companies, approval is required if any included company requires it. Apply
`backend/sql/20261024_add_schedule_assignment_approval_parameter.sql`.

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