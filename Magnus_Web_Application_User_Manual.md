# Magnus Timekeeping

*Web Application User Manual*

For employees, approvers, HR administrators and payroll staff

Prepared 26 November 2026 | Based on the application source in this workspace

> This guide describes available application behavior, not the current configuration of your organization or proof of a deployed release. Menu visibility depends on permissions, assigned roles, selected company and system version. Verify payroll policy, statutory rates and implementation details with authorized HR and payroll personnel before processing live payroll.

## Contents

- 1. Getting started and navigation

- 2. Employee self-service

- 3. Approver workflows

- 4. Initial configuration sequence

- 5. Company and organization setup

- 6. Locations, geofences and kiosks

- 7. Employees, accounts and assignments

- 8. Schedule and rest-day setup

- 9. Leave and holiday setup

- 10. Payroll groups and cutoffs

- 11. Compensation and earning rules

- 12. Benefits, deductions and loans

- 13. Statutory schedules and company parameters

- 14. Period-end attendance and time totals

- 15. Gross-to-net payroll calculation and approval

- 16. 13th-month and off-cycle payroll

- 17. Reports, exports and security

- 18. Troubleshooting and operational checklist

## 1. Getting started and navigation

Use the web address supplied by your organization. Sign in with your account credentials. Change your password when prompted, and sign out using the account menu when finished. Contact your administrator for account or password issues.

The top navigation contains Dashboard, Timekeeping, Reports, People, Settings and Payroll. Individual actions appear only when your account has access. A View as selector may appear when multiple dashboard roles are available; it changes the dashboard view, not the permissions granted by the server.

For company-scoped setup and payroll, select the intended company in the top navigation. In payroll management, also select the payroll group. Confirm these selections before saving or calculating. Open modules appear as workspace tabs; Dashboard stays available.

> Times may be displayed in Philippine time. Payroll cutoff deadline inputs use the browser’s local time: verify your computer time zone and the displayed deadlines before saving.

## 2. Employee self-service

### 2.1 Review attendance and schedule

1. On Dashboard, open attendance, weekly hours, leave balances or recent requests as available. Use Reports > Attendance Detail for the detailed report within your permitted scope.

   Select **Recorded absences this month** to see your recorded absence dates from the first of the calendar month through today in Philippine time. This is not the payroll cutoff; recent attendance uses the current cutoff.

2. Use Timekeeping > Emergency CWS to view My Schedule and, when needed, request an emergency schedule change for a work date. Select the eligible replacement schedule and provide the reason.

3. Confirm an emergency request is submitted and check its status. An approved change applies to the specified day, not the permanent assignment. Past-date requests are restricted by the filing window and eligibility rules.

### 2.2 Record attendance at a shared kiosk

1. At an approved kiosk provided by the organization, open the kiosk address. Enter your employee number, select Time In or Time Out, and follow the face-verification prompts.

2. Use available break actions for break out and break in. Read any confirmation, including an early time-out warning, and verify that the punch was recorded.

> The web attendance page states that browser punches are available only from an administrator-approved attendance kiosk at its assigned location. A kiosk must be registered and paired before use; see section 6. Mobile attendance is a separate workflow.

### 2.3 Apply for overtime

1. On Dashboard choose Apply for Overtime. Choose a completed attendance date and an available overtime type.

2. Review the effective clock-in and clock-out, enter the requested start and end within those punches, and check the automatically calculated requested minutes against the displayed maximum.

3. Enter the reason and optional work accomplished, then select Submit for approval. Note the application number and check My Overtime Applications for status.

Regular and night overtime are separate options when available. Night differential within a regular shift does not require a separate overtime filing. Pending or approved applications cannot be duplicated for the same type.

### 2.4 File rest-day work

1. After both punches, select File Rest-Day Work on Dashboard. Select Completed rest-day attendance.

2. Enter the reason and optionally work accomplished. Select Submit for approval and check My rest-day applications.

The request covers the complete clock-in-to-clock-out interval without break deductions. Approved minutes begin at clock-in: the first 480 minutes are rest-day work and the remainder is rest-day overtime. Only one pending or approved rest-day application per employee and date is allowed. Only approved rest-day work is included in recalculated cutoff totals.

### 2.5 Apply for leave

1. On Dashboard choose + Apply for Leave. Select the leave type and enter the start and end, reason and optional contact information.

   The duration is calculated from approved schedules, excluding rest days and non-working holidays. It uses published company calendars and the assigned work location; missing calendar or location information is treated as an ordinary workday. A missing schedule prevents filing. The period is limited to 93 days and cannot cross entitlement years. A period with no scheduled work cannot be filed.

   Enter the full shift's start and end times, including the meal-break period. Leave is limited to 480 minutes (8 hours, or 1 leave day) per scheduled workday: a 9:00 AM to 6:00 PM full-shift request counts as 480 minutes, not 540. Configured unpaid breaks are deducted when the entire shift is covered, then the daily limit is applied. Shorter durations remain based on the covered scheduled work; multiple workdays are calculated separately and added together.

   For an overnight shift, the shift's work/start date determines its daily limit, holiday and rest-day status. The calculated duration is checked again on submission and approval; if a previously filed duration differs from the current calculation, the application may need to be updated or refiled. Existing approved applications and leave charges are not automatically rewritten.

2. Select Save draft. In My Leave Applications, locate the DRAFT and select Submit for approval. Saving the draft alone does not submit it.

   **My Leave Applications** always lists only the signed-in employee's requests, including when that account also has HR Admin rights. Organization-wide records remain separate from this personal list.

3. Check the application status and, once approved, its paid/unpaid breakdown. Leave balance is deducted only on approval; available paid balance is allocated to the earliest leave days first. Contact HR if the leave type or balance is missing.

### 2.6 File official business

1. Choose File Official Business on Dashboard. Enter the start and end, destination and purpose. Add client, job order, geofence or vehicle details if applicable.

2. Check requested minutes. Choose Save as draft to finish later or Submit for approval to send it. Submit a saved draft from My Official Business Requests.

3. Track the request status. Overlapping draft, pending or approved requests are not allowed.

### 2.7 Request a missing-punch correction

1. On Dashboard choose + Apply for Attendance Correction. Select the work date, load the attendance and review the existing recorded punches.

2. Supply the actual missing punch, reason and any requested supporting reference. Submit and check the confirmation and subsequent review status.

Corrections are subject to schedule, attendance and cutoff eligibility. Existing punches are protected; if your situation cannot be filed or an existing punch needs changing, contact HR.

> Filing deadlines matter. A submitted request is not an approval. Check the application number and status, and follow up before the cutoff’s applicable deadlines.

### 2.8 HR Admin regularization candidates

In the HR Admin dashboard view, **Regularization candidates** appears in the review queue only when there are eligible active non-regular assignments. Select it to see employees, companies, org units, hire dates, six-month dates and days remaining or overdue. All non-regular employment types are included; the list is for HR review and does not change employment status.

Select a column heading to sort the candidate list; select it again to reverse the order.

An assignment appears starting 15 calendar days before its six-month date and remains until its employment type is changed to `REGULAR` or it is no longer active and current. Use **Refresh** after updating an assignment. The six-month date uses calendar months, with month-end dates adjusted to the last day of the target month.

Each HR Admin sees one in-app reminder per Philippine calendar day when candidates exist and they open or refresh the dashboard. Select **Dismiss reminder** to hide that day's reminder; the candidate list stays available. A dashboard left open refreshes on a new day and window focus. There is no email or push notification when the dashboard is closed.

### 2.9 Return an approved leave application

In the HR Admin or Supervisor dashboard review queue, open **Return approved leave for approval**, choose a date range and search. Select the application, enter the reason, then confirm **Return for approval**. HR Admin can return any employee's approved leave except their own. A Supervisor can retrieve and return only applications they personally approved, even if the employee is an HR Admin. Current team membership or a saved reviewer assignment alone does not grant return rights. Nobody can return their own application.

Select a column heading to sort the results across all pages. Changing the sort returns the list to its first page.

The application returns to pending and is assigned to the current eligible org-unit approver. If routing cannot be resolved, the return is blocked until HR corrects the organization setup. The paid leave charge is restored and the reason and reversal are recorded in the leave ledger. A new approval recalculates and charges the eligible paid amount again.

The action is blocked for payroll-posted leave, closed approval deadlines, finalized or locked cutoffs, or inconsistent leave ledger/entitlement records. If payroll or attendance results were already calculated but remain open, recalculate them after the return. Older applications with missing or inconsistent charge records require HR review rather than automatic reversal.

### 2.10 Return an approved overtime application

In the HR Admin or Supervisor dashboard review queue, open **Return approved overtime for approval**, choose the work-date range and search. This includes regular overtime, night overtime, night differential and rest-day work. Sort by selecting a column heading; sorting applies across all pages. HR Admin can return any employee's approved application except their own; a Supervisor can retrieve and return only applications they personally approved.

Select an application, enter a reason and confirm **Return for approval**. The application returns to pending and is assigned to the current eligible org-unit approver. Its approved payable minutes are cleared and attendance totals are recalculated without removing other approved overtime types. The return reason, actor and previous approved and payable minutes are recorded. Another HR Admin or the Supervisor who personally approved it must return an HR Admin's own application.

The action is blocked when routing or the employee's payroll cutoff cannot be resolved, another open application conflicts, attendance is locked or invalid, payroll is posted or exported, or the approval deadline or cutoff is closed. Recalculate affected payroll results if they were previously calculated and remain open.

For both modules, approvals made before per-application approver tracking was deployed remain HR Admin-only when the actual approver is unknown. The system does not guess from the last editor or current org chart. After a return and a new approval, only the new actual approver has Supervisor return rights.

Deployment: apply `backend/sql/2026_application_original_approvers.sql` or Alembic revision `c2e4a6b8d0f1` before deploying the updated backend. This adds nullable `approved_by_id` columns and indexes to leave and overtime applications; it does not backfill unverified historical approvers.

## 3. Approver workflows

### 3.1 Who receives a request

New employee requests use the employee’s current org-unit hierarchy to select one independent eligible manager. The manager’s own request moves to an eligible ancestor instead of self-approval. Units with approval disabled and excluded descendant branches are skipped. The chosen manager needs an active employee-linked account. A supervisor title alone does not assign approval authority.

The selected reviewer is saved at submission. Later org-chart changes do not automatically reassign existing pending requests. Older legacy-routed requests may use supervisor-based scope. If routing cannot find an approver, the request remains pending and unresolved; HR should correct the setup and use the routing alert recovery controls. A submission confirmation does not guarantee that routing was resolved.

### 3.2 Review requests

1. Sign in with the assigned approver account. On Dashboard, open the relevant team review: Leave, Overtime, Official business, Attendance corrections or Invalid attendance, as available.

2. Review the employee, date, request, reason and supporting information. For overtime and rest-day work, open Overtime; the panel identifies Rest-day work and allows an approved amount up to the requested amount or rejection.

3. Select the appropriate approval or rejection action and save. A rejection reason is required for leave, overtime, rest-day work and official business. Attendance corrections require review notes; emergency schedule and schedule-upload rejections also require remarks. Employees can see the reviewer's reason in their application history on the web and, for their mobile filing workflows, in the mobile app. Existing rejected applications may have no recorded reason.

Deployment for rejection reasons: tracked databases require Alembic revision `f6a8c0e2b4d6`. For an untracked database, back up and review the schema first, then use `backend/sql/manual_application_rejection_reasons.sql` with `psql -v ON_ERROR_STOP=1`; do not stamp or run Alembic against an untracked database without a separately reviewed migration plan. Apply the schema before deploying the backend and worker, then deploy the web and mobile updates.

4. For schedule batches use Timekeeping > Schedule Upload Approvals. Review the batch before deciding. Follow up on unresolved routing or errors with HR.

Approvers must finish before the approval deadline. Payroll approval is a separate role-controlled step and is not the employee’s org-unit request approval.

## 4. Initial configuration sequence

Complete the following in a test or controlled environment before the first live period. Effective dates, active status, company context and permissions must align. Not every optional setup applies to every company.

1. Create company, org-unit types, units, parent hierarchy and independent managers; configure approval settings and exclusions.

2. Configure locations, geofences and the holiday calendar; create payroll groups and the applicable work schedule templates and rest-day patterns.

3. Create employees and linked accounts; establish active employment assignments, organizational placement, payroll group, work locations, roles, face enrollment and schedules.

4. Configure leave types and employee entitlements. Create cutoff periods and filing/approval deadlines.

5. Enter employee compensation, earning rules, applicable benefits, deductions, loans and opening balances. Verify and activate the applicable statutory schedules and company parameters.

6. Run a small representative test with approved schedules, punches, filings, reviews, time totals and payroll. Compare results with an independently checked calculation before live processing.

## 5. Company and organization setup

### 5.1 Company and hierarchy

1. Navigate to Settings > Company Setup > Organization > Companies and create or update the company using its correct identifying information and active status.

2. Under Org Units, configure Org Unit Types and Operational Groups as needed. Create the company’s units, parent-child relationships, effective dates and manager employee.

3. On each unit review Manager is an approver and Excluded org units. Exclusions apply to the selected descendant branch for that manager; they do not disable the descendant manager. Save new units before adding exclusions.

4. Use Org chart to check hierarchy and manager placement. Verify that employee assignments point to the intended unit and that managers have active linked accounts.

> Missing managers, inactive units, invalid assignments or inactive manager accounts can leave requests unresolved. Do not assume an unrelated supervisor or administrator automatically receives a newly organization-routed request. HR can use Dashboard routing alerts to retry routing or assign an eligible independent manager after correction.

## 6. Locations, geofences and kiosks

1. Under Settings > Company Setup > Organization, create Location Types and Locations for the selected company. Configure each location’s required details and active status.

2. Under Geofences, configure the location boundary and permitted GPS accuracy according to company policy. Assign employees to appropriate locations through their employment assignment.

3. Enroll each employee’s face using the employee record’s Face Enrollment tab, subject to permissions and consent/policy.

4. For a shared browser kiosk, open the organization’s HTTPS kiosk address, enter a station name and request registration. A system administrator opens Settings > Kiosk Devices on another trusted browser, enters the pairing code, confirms the station and selects its active location.

5. On the station select Check approval, allow the camera and test identification and a punch using an authorized test employee. The pairing code expires after 15 minutes and can be renewed on the station.

Kiosk use requires an active employee and account, an effective assignment to the kiosk’s company and location, and successful face verification. Handle biometric data and kiosk access according to organizational policy.

## 7. Employees, accounts and assignments

1. Open People > Employees and add the employee’s identity and contact details. The normal creation flow creates an initial employee account; a personal email is required. Review Enabled for use and record status.

2. Open the saved employee and maintain their employment assignment: company, org unit, effective dates, payroll group, supervisor and primary or additional locations as applicable. Avoid missing or ambiguous current assignments.

3. Use the Role tab, where permitted, to assign or maintain access. Role scope and dates do not replace the employment assignment or org-unit manager configuration.

4. Use Face Enrollment and Schedule tabs to complete attendance setup. Add leave entitlements and compensation separately where applicable.

HR administrators with the required permissions can use the account menu on Employees to import or export CSVs. Download the appropriate template, preview and fix errors before confirming. Profile imports skip existing employees; assignment and entitlement imports can replace matching records, while personal-information imports fill empty fields only. Review each import’s on-screen rules and protect exported personal information.

## 8. Schedule and rest-day setup

### 8.1 Build templates and patterns

1. Navigate to Settings > Company Setup > Work Rules > Schedule Templates and choose New template. Enter code, name, schedule type, required work minutes, grace rules, minimum overtime and effective dates.

2. Configure overnight and overtime settings as appropriate. Add and expand schedule segments to specify work and paid or unpaid breaks, their times, day offsets and allowances. Save an active template after review.

3. Open Rest Day Patterns, create a code and name, set cycle length, and designate each cycle day as workday or rest day. Workdays may reference a template; rest days cannot. Save the active pattern.

### 8.2 Assign or upload schedules

1. In People > Employees, open the employee’s Schedule tab and add the assignment, effective dates, template, rest pattern and attendance mode where applicable. Review whether the assignment must be approved.

2. For bulk changes use Timekeeping > Schedule Uploads. Download template, populate the CSV and choose Check file. Correct all errors, review the preview and choose Submit schedules.

3. Check My uploads for batch status. In HR_ADMIN mode, enter the relevant active org-unit manager in supervisor_employee_code; the system creates batches per manager. If a batch would require multiple approvers, split the upload.

Company Parameters controls whether new direct assignments and upload batches require approval. If enabled, an independent eligible reviewer approves; if disabled, new assignments or uploads are automatically approved. Changing the setting does not approve existing pending items. Schedule credited mode credits scheduled time without punches; Punch required remains the default.

## 9. Leave and holiday setup

1. Under Settings > Company Setup > Work Rules > Leave Management, maintain the company’s active leave types, duration units, effective dates and relevant leave policy settings.

2. Add the appropriate employee leave entitlements through the employee/entitlement workflow, or use the permitted CSV import. Check balances and effective periods.

3. Under Settings > Company Setup > Payroll Setup > Calendar, maintain the applicable holiday calendar and dates. Link the intended calendar to the payroll group and schedule template where appropriate.

Verify holiday classifications, leave units and paid/unpaid treatment with HR before the period is calculated. Calendar and policy changes can affect time and payroll results.

Non-working holidays and rest days are excluded for every leave type; the legacy per-type exclusion settings no longer control this calculation. Older pending applications whose saved duration or daily breakdown differs from the current calculation must be reviewed and refiled before approval. Under Employee Entitlements, HR can open the read-only holiday leave review for potentially affected approved leave. It uses currently published calendars and assignments and cannot reconstruct missing historical data; review each result before any adjustment.

## 10. Payroll groups and cutoffs

### 10.1 Create a payroll group

1. Select the company, then open Payroll > Payroll Groups and add a payroll group.

2. Enter the code, name, pay frequency and rate type. Set standard minutes per day, annual divisor where applicable, rounding minutes and the holiday calendar. Review status and Active, then save.

The annual divisor is used to derive a daily equivalent for monthly-rated salary deductions. Confirm the value and rate basis against the company’s approved policy rather than copying an example.

### 10.2 Create a cutoff

1. Open Payroll > Payroll Cutoffs and select New cutoff. Choose the group; All Groups creates a separate matching cutoff for every active group in the selected company.

2. Enter or review cutoff code, period start, period end, pay date, status and Active. Explicitly choose First cutoff or Second cutoff when half-specific benefits, deductions, loans or statutory timing apply.

3. Set an employee filing deadline and approval deadline after the last cutoff day ends in Philippine time. Approval must be on or after filing; a filing deadline requires an approval deadline. If filing is blank, the approval deadline also applies to filing.

4. Save, review the displayed period and deadlines, and communicate them. Do not fill optional calculation version or export batch ID without an authorized operational reason.

> The exact deadline instant is still allowed; finalization requires the approval deadline to have passed. Finalized attendance and locked payroll close filing and approval windows.

## 11. Compensation and earning rules

1. Open Payroll > Management, select the company and payroll group, then choose Compensation.

2. Select an employee assigned to the group, enter the base rate, three-letter currency and effective dates, then choose Add base rate. Rates use the group’s monthly, daily or hourly basis and must cover the full cutoff; compensation dates must be covered by exactly one assignment.

3. Choose Earning rules. Enter and save the approved multiplier for each applicable component, including regular, overtime, holiday, rest-day and combined holiday/rest-day components.

Day and overtime multipliers represent the full pay rate. Night differential multipliers are premium-only additions: 0.10 represents a 10% differential, not a full rate of 1.10. Missing applicable combined rates can put payroll on HOLD. Have payroll review rates against current law and approved policy.

## 12. Benefits, deductions and loans

1. Define applicable Benefit Types and Deduction Types under Settings > Company Setup > Payroll Setup for the selected payroll group. Review category, tax treatment and other type settings.

2. In Payroll > Management, choose Benefits or Deductions. Set recurring employee entitlements or deductions, effective dates and cutoff timing, and enter any authorized per-cutoff items. Review employee, type and amount before saving.

3. Use Employee loans to maintain loan balances and repayment schedules when applicable. Check the employee, payment amount, start and cutoff timing; review restructure or retire actions carefully.

4. Maintain required tax-year opening balances when prior payroll or benefit information must be carried into the system. Reconcile amounts to approved source records.

For first/second cutoff timing, the cutoff designation must be set explicitly. Never infer the designation from calendar dates alone. Protect compensation and bank information.

## 13. Statutory schedules and company parameters

1. Open Settings > Statutory Setup > Contribution & Tax Schedules and select the company. Review SSS, PhilHealth, Pag-IBIG and withholding tax schedules and the contribution deduction timing.

2. Create or edit draft schedules and brackets with their effective dates and official source reference. Check all brackets, shares, caps, pay frequency and timing against current official issuances and organizational policy before activation.

3. Open Settings > Statutory Setup > Company Parameters. Review schedule assignment approval, regular-holiday attendance, 13th-month calculation and optional year-end withholding-tax reconciliation.

4. Save only after authorized review. Confirm the activated schedules cover the payroll dates and frequency. Review the selected company before changing any setting.

> Seeded schedules, where present, may be drafts or outdated. Do not assume seeded amounts are legally current. Employer contributions are shown separately and are not deducted from employee net pay.

## 14. Period-end attendance and time totals

1. Before the filing deadline, ask employees to complete punches and submit leave, overtime, rest-day work, official business and correction requests. Resolve missing or duplicate attendance through authorized workflows.

2. Before the approval deadline, have assigned reviewers decide pending items. HR should resolve routing alerts, invalid punches and appropriate schedule or attendance issues.

3. Open Payroll > Payroll Cutoffs for the correct company and group. On the applicable cutoff choose Calculate or Recalculate to create employee attendance/time totals. Open Results to review scheduled and paid time, exceptions, leave, overtime, holidays and rest-day categories.

4. Open Reports > Attendance Detail, select the cutoff, and review the underlying records and cutoff status. The Leave, Overtime & OB column includes leave applications even when separate daily leave records are unavailable; in that case, the displayed daily minutes are prorated estimates. Make necessary corrections and recalculate time totals before finalization. A cutoff results CSV contains time totals, not monetary payroll.

5. After the approval deadline has passed, an authorized HR user with attendance finalization permission selects Finalize attendance in Attendance Detail. The cutoff must have calculated attendance results. Confirm the finalization notice.

> Finalized attendance cannot be changed or recalculated through the normal workflow. Payroll calculation uses saved finalized cutoff results; it does not recalculate attendance. Escalate errors after finalization to authorized administrators rather than assuming a payroll unlock alone reopens attendance.

## 15. Gross-to-net payroll calculation and approval

### 15.1 Calculate and review

1. Open Payroll > Management, select the company and payroll group, and choose Payroll calculation. Select the finalized cutoff.

2. Choose Calculate payroll. If a prior run exists and the cutoff is not locked, choose Recalculate payroll after authorized payroll setup corrections.

3. Review each employee’s gross pay, cash benefits, deductions, net pay, status and Calculation details. Reconcile a representative sample against approved time, compensation, rates, contributions and tax.

4. Investigate every HOLD message. Typical causes include missing full-period compensation, applicable earning rules, effective statutory schedules, tax-year opening balances, approved worked minutes or required cutoff designation. Correct the actual cause and recalculate, then verify every result is READY.

Monthly-rated base pay is allocated according to frequency; unpaid scheduled time can reduce it using the configured daily equivalent and standard minutes. Paid leave and approved official business count as covered scheduled time. Daily and hourly rates use approved time minutes. Calculations depend on the configured rules and the particular employee’s facts.

### 15.2 Independent approval and lock

1. Ensure the approval deadline has passed, attendance is finalized, a current payroll calculation exists, the source time results remain valid, and every employee result is READY.

2. A separate authorized HR administrator, not the person who calculated the current payroll run, reviews the results and selects Approve and lock payroll. Confirm the prompt and the locked status.

3. Retain the approved review and follow the organization’s separate payment and accounting procedures. Do not assume a calculation or lock transfers money.

Approval locks the cutoff against recalculation and editing. An authorized administrator with system.manage may use Unlock for correction when necessary; this is audited. Follow the organization’s controlled correction process and review finalization and downstream effects before making changes.

## 16. 13th-month and off-cycle payroll

### 16.1 Calculate 13th-month pay

1. Open Payroll > 13th-Month Calculation and select the company. Ensure eligible current READY payroll results exist.

2. Enter the tax year and the From and To dates of the last cutoff to include, then choose Calculate. Review the employee-level basic earned, 13th-month, exempt and taxable amounts.

The calculation includes eligible regular and paid-leave basic earnings; it excludes benefits, overtime, night differential and reimbursements. It creates or replaces the current calculation run and does not itself post payment.

### 16.2 Prepare and release off-cycle payroll

1. Open Payroll > Off-Cycle Payroll and select the company. Choose Incentive upload (CSV) or 13th-month pay, payroll group, eligible benefit type, proposed release date and optional notes.

2. For incentives, download the template and upload employee_no, amount and notes; review the rows and total. For 13th-month, select an available unpaid calculation. Create draft.

3. Open the run, review lines, tax and net amounts, and recalculate if appropriate. Submit for approval. An authorized reviewer approves or rejects with a reason.

4. After the actual release has occurred and is confirmed according to company controls, enter the actual release date and choose Mark as paid. Paid amounts then count toward year-to-date tax.

> Off-cycle 13th-month requires an active eligible one-time bonus benefit type with limited-exempt tax treatment. Review tax settings and benefit caps with payroll.

## 17. Reports, exports and security

- Reports > Attendance Detail: inspect detailed records within your authorized scope and, with permission, finalize a cutoff after review.

- Reports > Attendance Summary by Org Unit: review organization totals where authorized. Reports > Payroll Calculation Review: review cutoff results within the permitted scope.

- Payroll Cutoffs > Results > Download CSV exports confidential employee time totals only, not monetary payroll. Employee CSV and other settings downloads are also permission-controlled and may contain sensitive information.

- Tardiness Review is an HR_ADMIN preview; it does not automatically create or issue notices. Notice Templates can be uploaded and reviewed, but template activation alone does not issue a notice.

- System administrators can create a database backup from the account menu. Database downloads are unencrypted and cover the configured database, not uploaded files or other services. Use approved encrypted storage and an independent restore plan.

Use least-privilege access, avoid sharing accounts, verify recipients before distributing reports, and store payroll, employee and biometric information securely under company policy.

## 18. Troubleshooting and operational checklist

- A menu is missing: check the assigned permission, dashboard role, selected company and deployed version. Role preview does not grant access.

- A request has no approver: HR checks the current employee assignment, active org hierarchy, approver setting, exclusions and manager account, then retries routing from the alert. Already assigned pending routes do not automatically change after a manager change.

- No eligible attendance is shown: verify completed punches, schedule/rest-day classification, active cutoff and deadlines, and whether an open application already exists.

- An employee is missing from payroll: check active employment assignment, company, payroll group, effective dates, schedule and cutoff time results.

- Payroll is on HOLD: inspect the employee calculation details and correct the specific missing setup or source data before recalculation. Do not treat HOLD as a payable result.

- Calculate payroll is unavailable: check that attendance results were calculated, reviewed and finalized and that the cutoff is not locked.

- Approval is unavailable: check the deadline, attendance finalization, all READY results, approval permission and independent approver. Payroll cannot be approved by the person who calculated the current run.

- Unexpected result after finalization: stop and escalate. Preserve the audit trail and follow the authorized correction process; do not bypass locks or directly edit database records.

Period-end checklist: company and group confirmed; cutoff and deadlines confirmed; employee filings and approvals completed; routing alerts and exceptions resolved; time totals calculated and reviewed; attendance finalized; payroll calculated and all HOLDs cleared; independent approval obtained; outputs handled securely.
