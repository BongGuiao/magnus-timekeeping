from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from elasticsearch import AsyncElasticsearch
from sqlalchemy import text
from app.core.config import settings
from app.core.request_logging import RequestLoggingMiddleware, configure_audit_logger
from app.core.database import engine, Base, init_db_models
from app.core.exception_handlers import register_exception_handlers
from app.auth.infrastructure.router import router as auth_router
from app.enrollment.infrastructure.router import router as enrollment_router
from app.attendance.infrastructure.router import router as attendance_router
from app.attendance.infrastructure.official_business_router import router as official_business_router
from app.filemaintenance.companies.infrastructure.router import router as companies_router
from app.filemaintenance.org_unit.infrastructure.router import router as org_units_router
from app.filemaintenance.holidays.calendar.infrastructure.router import router as holiday_calendars_router
from app.filemaintenance.holidays.holiday.infrastructure.router import router as holidays_router
from app.filemaintenance.leaves.infrastructure.router import router as leave_types_router
from app.filemaintenance.leaves.infrastructure.leave_records_router import (
    applications_router as leave_applications_router,
    entitlements_router as employee_entitlements_router,
    ledger_router as leave_ledger_router,
)
from app.filemaintenance.location.infrastructure.router import router as locations_router
from app.filemaintenance.geofences.infrastructure.router import router as geofences_router
from app.filemaintenance.employees.infrastructure.router import router as employees_router
from app.filemaintenance.employees.infrastructure.related_router import assignments_router, skills_router
from app.filemaintenance.devices.infrastructure.router import router as devices_router
from app.filemaintenance.payroll_groups.infrastructure.router import router as payroll_groups_router
from app.filemaintenance.payroll_cutoffs.infrastructure.router import router as payroll_cutoffs_router
from app.filemaintenance.schedule.infrastructure.router import router as schedule_templates_router
from app.filemaintenance.schedule.infrastructure.employee_schedule_assignment_router import (
    router as employee_schedule_assignments_router,
)
from app.filemaintenance.schedule.infrastructure.rest_day_pattern_router import (
    router as rest_day_patterns_router,
)
from app.psgc.infrastructure.router import router as psgc_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_audit_logger(settings.REQUEST_LOG_DIRECTORY)
    init_db_models()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS payroll"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS schedule"))
        await conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_type AS t
                        JOIN pg_namespace AS ns ON ns.oid = t.typnamespace
                        WHERE ns.nspname = 'core'
                          AND t.typname = 'positive_minutes'
                          AND t.typtype = 'd'
                    ) THEN
                        CREATE DOMAIN core.positive_minutes AS integer
                        CHECK (VALUE >= 0);
                    END IF;
                END
                $$;
                """
            )
        )
        await conn.run_sync(Base.metadata.create_all)
    audit_es_client = (
        AsyncElasticsearch(settings.ELASTICSEARCH_URL)
        if settings.ELASTICSEARCH_URL
        else None
    )
    app.state.audit_es_client = audit_es_client
    try:
        yield
    finally:
        if audit_es_client is not None:
            await audit_es_client.close()

app = FastAPI(
    title="Magnus Time Keeping",
    lifespan=lifespan,
    # Configure root path if Nginx serves the API under a prefix (e.g. /api/v1)
    # root_path="/api/v1" 
)

# CORS configuration for Nginx reverse proxy setups
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"] if settings.REQUEST_LOGGING_ENABLED else [],
)

if settings.REQUEST_LOGGING_ENABLED:
    app.add_middleware(
        RequestLoggingMiddleware,
        log_directory=settings.REQUEST_LOG_DIRECTORY,
    )

app.include_router(auth_router)
app.include_router(enrollment_router)
app.include_router(official_business_router)
app.include_router(attendance_router)
app.include_router(companies_router)
app.include_router(org_units_router)
app.include_router(holiday_calendars_router)
app.include_router(holidays_router)
app.include_router(leave_types_router)
app.include_router(employee_entitlements_router)
app.include_router(leave_applications_router)
app.include_router(leave_ledger_router)
app.include_router(locations_router)
app.include_router(geofences_router)
app.include_router(employees_router)
app.include_router(assignments_router)
app.include_router(skills_router)
app.include_router(devices_router)
app.include_router(payroll_groups_router)
app.include_router(payroll_cutoffs_router)
app.include_router(schedule_templates_router)
app.include_router(rest_day_patterns_router)
app.include_router(employee_schedule_assignments_router)
app.include_router(psgc_router)
register_exception_handlers(app)