from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.geofences.application.use_case import (
    CreateGeofenceUseCase,
    DeleteGeofenceUseCase,
    GetGeofenceUseCase,
    ListGeofencesUseCase,
    UpdateGeofenceUseCase,
)


def get_delete_geofence_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> DeleteGeofenceUseCase:
    return DeleteGeofenceUseCase(uow)


def get_create_geofence_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreateGeofenceUseCase:
    return CreateGeofenceUseCase(uow)


def get_update_geofence_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> UpdateGeofenceUseCase:
    return UpdateGeofenceUseCase(uow)


def get_geofence_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetGeofenceUseCase:
    return GetGeofenceUseCase(uow)


def get_list_geofences_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListGeofencesUseCase:
    return ListGeofencesUseCase(uow)
