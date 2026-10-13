from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.devices.application.use_case import (
    CreateDeviceUseCase,
    GetDeviceUseCase,
    ListDevicesUseCase,
    UpdateDeviceUseCase,
)


def get_create_device_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> CreateDeviceUseCase:
    return CreateDeviceUseCase(uow)


def get_update_device_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> UpdateDeviceUseCase:
    return UpdateDeviceUseCase(uow)


def get_device_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> GetDeviceUseCase:
    return GetDeviceUseCase(uow)


def get_list_devices_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> ListDevicesUseCase:
    return ListDevicesUseCase(uow)
