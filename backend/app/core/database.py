# app/core/database.py
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

# 1. Define the Base class for your models
class Base(DeclarativeBase):
    pass
def init_db_models():
    from app.auth.infrastructure.db_model import RoleModel, UserModel, UserRoleModel  # noqa: F401
    from app.filemaintenance.roles.infrastructure.permission_db_model import PermissionModel  # noqa: F401
    from app.filemaintenance.roles.infrastructure.role_permission_db_model import (  # noqa: F401
        RolePermissionModel,
    )
    from app.enrollment.infrastructure.db_model import FaceEnrollmentModel  # noqa: F401
    from app.attendance.infrastructure.db_model import (  # noqa: F401
        AttendanceModel,
        PunchExceptionModel,
        OfficialBusinessRequestModel,
        OvertimeApplicationModel,
    )
    from app.attendance.infrastructure.offline_models import OfflinePermitModel, OfflinePunchEventModel  # noqa: F401
    from app.filemaintenance.companies.infrastructure.db_model import CompanyModel  # noqa: F401
    from app.filemaintenance.org_unit.infrastructure.db_model import OrgUnit  # noqa: F401
    from app.filemaintenance.org_unit.infrastructure.org_unit_type_db_model import OrgUnitType  # noqa: F401
    from app.filemaintenance.operational_groups.infrastructure.db_model import OperationalGroupModel  # noqa: F401
    from app.filemaintenance.holidays.calendar.infrastructure.db_model import (  # noqa: F401
        HolidayCalendarModel,
    )
    from app.filemaintenance.holidays.holiday.infrastructure.db_model import HolidayModel  # noqa: F401
    from app.filemaintenance.announcements.infrastructure.db_model import AnnouncementModel  # noqa: F401
    from app.filemaintenance.leaves.infrastructure.db_model import LeaveTypeModel  # noqa: F401
    from app.filemaintenance.leaves.infrastructure.leave_records_db_model import (  # noqa: F401
        EmployeeEntitlementModel,
        LeaveApplicationDateModel,
        LeaveApplicationModel,
        LeaveLedgerModel,
    )
    from app.filemaintenance.payroll_groups.infrastructure.db_model import (  # noqa: F401
        PayrollGroupModel,
    )
    from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import (  # noqa: F401
        PayrollCutoffModel,
    )
    from app.filemaintenance.payroll_cutoffs.infrastructure.employee_cutoff_result_db_model import (  # noqa: F401
        EmployeeCutoffResultModel,
    )
    from app.payroll.infrastructure.db_model import (  # noqa: F401
        EmployeeCompensationModel,
        BenefitTypeModel,
        CutoffBenefitModel,
        GlobalPayrollSystemParametersModel,
        GrossPayResultModel,
        GrossPayRunModel,
        PayrollEarningRuleModel,
        PayrollOpeningYtdBalanceModel,
        StatutoryContributionBracketModel,
        StatutoryContributionScheduleModel,
        WithholdingTaxBracketModel,
        WithholdingTaxScheduleModel,
    )
    from app.payroll.infrastructure.loan_db_model import (  # noqa: F401
        EmployeeLoanModel,
        EmployeeLoanRepaymentModel,
    )
    from app.filemaintenance.schedule.infrastructure.db_model import (  # noqa: F401
        EmployeeScheduleAssignmentModel,
        RestDayPatternDayModel,
        RestDayPatternModel,
        ScheduleSegmentModel,
        ScheduleTemplateModel,
    )
    from app.filemaintenance.schedule.infrastructure.emergency_schedule_db_model import (  # noqa: F401
        EmergencyScheduleRequestModel,
    )
    from app.filemaintenance.schedule.infrastructure.schedule_upload_db_model import (  # noqa: F401
        ScheduleUploadBatchModel,
        ScheduleUploadBatchRowModel,
    )
    from app.filemaintenance.location.infrastructure.db_model import Location  # noqa: F401
    from app.filemaintenance.geofences.infrastructure.db_model import Geofence  # noqa: F401
    from app.filemaintenance.employees.infrastructure.db_model import (  # noqa: F401
        EmployeeModel,
        EmployeeSkillModel,
        EmploymentAssignmentModel,
        EmployeeWfhLocationModel,
    )
    from app.filemaintenance.devices.infrastructure.db_model import (  # noqa: F401
        DeviceChallengeModel,
        DeviceCredentialModel,
        DeviceModel,
    )

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/dbname")

SQL_ECHO = os.getenv("SQL_ECHO", "").strip().lower() in {"1", "true", "yes", "on"}
engine = create_async_engine(DATABASE_URL, echo=SQL_ECHO, future=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
