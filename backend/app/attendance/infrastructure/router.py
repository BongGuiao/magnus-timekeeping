"""Attendance API: aggregates the feature routers under the /attendance prefix."""
from fastapi import APIRouter

from app.attendance.infrastructure.attendance_dashboard_router import router as attendance_dashboard_router
from app.attendance.infrastructure.attendance_review_router import router as attendance_review_router
from app.attendance.infrastructure.attendance_report_router import router as attendance_report_router
from app.attendance.infrastructure.authorized_location_router import router as authorized_location_router
from app.attendance.infrastructure.clock_router import router as clock_router
from app.attendance.infrastructure.device_challenge_router import router as device_challenge_router
from app.attendance.infrastructure.overtime_router import router as overtime_router
from app.attendance.infrastructure.offline_router import router as offline_router

router = APIRouter(prefix="/attendance", tags=["Attendance"])

for feature_router in (
    clock_router,
    offline_router,
    device_challenge_router,
    overtime_router,
    attendance_review_router,
    attendance_report_router,
    authorized_location_router,
    attendance_dashboard_router,
):
    router.include_router(feature_router)
