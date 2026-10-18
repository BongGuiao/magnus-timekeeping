from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_

from app.auth.application.password_ports import AuditTrail
from app.auth.application.accounts import (
    DEFAULT_EMPLOYEE_PASSWORD,
    create_user_account,
    employee_display_name,
    get_app_role,
    is_login_allowed,
)
from app.auth.domain.entities.user import (
    DEFAULT_SIGNUP_ROLE_CODE,
    AccountStatus,
    Role,
    UserEntity,
)
from app.auth.infrastructure.db_model import UserModel
from app.core.config import settings
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.employees.domain.entities.employee import EmployeeEntity
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel

INVALID_CREDENTIALS_MESSAGE = "Invalid email or password"


def _build_token_payload(user: UserEntity, role: Role, role_codes: list[str]) -> dict:
    return {
        "sub": str(user.id),
        "email": user.email or user.username,
        "role": role.value,
        "roles": role_codes,
        "role_codes": role_codes,
        "employee_id": str(user.employee_id) if user.employee_id else None,
    }


@dataclass(frozen=True)
class LoginInputDTO:
    identifier: str
    password: str


@dataclass(frozen=True)
class LoginOutputDTO:
    access_token: str
    employee_name: str
    token_type: str = "bearer"
    expires_in_hours: int = 12
    role: str = "user"
    role_code: list[str] = field(default_factory=list)
    must_change_password: bool = False



@dataclass(frozen=True)
class SignUpInputDTO:
    email: str
    password: str
    employee_code: str
    role_code: str = DEFAULT_SIGNUP_ROLE_CODE
    created_by: UUID | None = None
    updated_by: UUID | None = None


@dataclass(frozen=True)
class SignUpOutputDTO:
    access_token: str
    employee_name: str
    token_type: str = "bearer"
    expires_in_hours: int = 12
    role: str = "user"
    role_code: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SearchUserByEmployeeCodeInputDTO:
    employee_code: str


@dataclass(frozen=True)
class SearchUserByEmployeeCodeOutputDTO:
    id: UUID | None
    employee_id: UUID | None
    email: str
    employee_code: str
    employee_name: str
    role: Role
    role_codes: list[str]
    account_status: str
    is_active: bool
    photo_reference: str | None


class SearchUserByEmployeeCodeUseCase(BaseUseCase[SearchUserByEmployeeCodeOutputDTO]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, input_dto: SearchUserByEmployeeCodeInputDTO) -> SearchUserByEmployeeCodeOutputDTO:
        employee_code = input_dto.employee_code.strip()

        async with self.uow as uow:
            user_repo = uow.get_repo(UserEntity, UserModel)
            user = await user_repo.find_one(func.lower(UserModel.username) == employee_code.lower())
            if not user or user.id is None:
                raise ValueError("No user found for the given employee code")

            employee = None
            if user.employee_id is not None:
                employee_repo = uow.get_repo(EmployeeEntity, EmployeeModel)
                employee = await employee_repo.find_one(EmployeeModel.id == user.employee_id)

            role, role_codes = await get_app_role(uow, user.id)
            return SearchUserByEmployeeCodeOutputDTO(
                id=user.id,
                employee_id=user.employee_id,
                email=user.email or "",
                employee_code=employee.employee_no if employee else user.username,
                employee_name=employee_display_name(employee) or user.username,
                role=role,
                role_codes=role_codes,
                account_status=user.account_status,
                is_active=user.is_active and user.account_status == AccountStatus.ACTIVE.value,
                photo_reference=employee.photo_reference if employee else None,
            )


class LoginUseCase(BaseUseCase[LoginOutputDTO]):
    def __init__(self, uow: GenUnitOfWork, security_service, audit: AuditTrail):
        self.uow = uow
        self.security_service = security_service
        self.audit = audit

    async def _execute(self, input_dto: LoginInputDTO) -> LoginOutputDTO:
        identifier = input_dto.identifier.strip().lower()
        rejection: str | None = None
        failure_reason: str | None = None
        account_id: UUID | str = "anonymous"
        lockout_event: dict[str, Any] | None = None
        output: LoginOutputDTO | None = None

        # Failed-attempt counters must be committed, so rejections are raised after the UoW exits.
        async with self.uow as uow:
            user_repo = uow.get_repo(UserEntity, UserModel)
            user = await user_repo.find_one(
                or_(func.lower(UserModel.email) == identifier, func.lower(UserModel.username) == identifier)
            )
            now_utc = datetime.now(timezone.utc)

            if not user or user.id is None:
                rejection = INVALID_CREDENTIALS_MESSAGE
                failure_reason = "invalid_credentials"
            else:
                account_id = user.id
                if user.locked_until is not None and user.locked_until <= now_utc:
                    user = replace(user, locked_until=None, failed_login_count=0)

                if user.locked_until is not None:
                    rejection = is_login_allowed(user, now_utc)
                    failure_reason = "account_locked"
                elif not self.security_service.verify_password(input_dto.password, user.password_hash):
                    failed_count = (user.failed_login_count or 0) + 1
                    locked_until = None
                    if failed_count >= settings.AUTH_MAX_FAILED_LOGIN_ATTEMPTS:
                        locked_until = now_utc + timedelta(minutes=settings.AUTH_LOCKOUT_MINUTES)
                    await user_repo.update(
                        replace(user, failed_login_count=failed_count, locked_until=locked_until)
                    )
                    rejection = INVALID_CREDENTIALS_MESSAGE
                    failure_reason = "invalid_credentials"
                    if locked_until is not None:
                        lockout_event = {
                            "failed_attempt_count": failed_count,
                            "locked_until": locked_until.isoformat(),
                        }
                else:
                    rejection = is_login_allowed(user, now_utc)
                    if rejection is None:
                        user = await user_repo.update(
                            replace(user, failed_login_count=0, locked_until=None, last_login_at=now_utc)
                        )
                        role, role_codes = await get_app_role(uow, user.id)
                        employee = None
                        if user.employee_id is not None:
                            employee = await uow.get_repo(EmployeeEntity, EmployeeModel).find_one(
                                EmployeeModel.id == user.employee_id
                            )
                        output = LoginOutputDTO(
                            access_token=self.security_service.create_access_token(
                                _build_token_payload(user, role, role_codes)
                            ),
                            employee_name=employee_display_name(employee) or user.username,
                            token_type="bearer",
                            expires_in_hours=12,
                            role=role.value,
                            role_code=role_codes,
                            must_change_password=input_dto.password == DEFAULT_EMPLOYEE_PASSWORD,
                        )
                    else:
                        failure_reason = (
                            "account_inactive"
                            if not user.is_active or user.account_status == AccountStatus.DISABLED.value
                            else "account_pending"
                            if user.account_status == AccountStatus.PENDING.value
                            else "account_locked"
                        )

        if rejection or output is None:
            await self.audit.record(
                user_id=account_id,
                action="LOGIN_FAILURE",
                resource="authentication",
                resource_id=str(account_id),
                after={"reason": failure_reason or "authentication_rejected"},
            )
            if lockout_event is not None:
                await self.audit.record(
                    user_id=account_id,
                    action="ACCOUNT_LOCKED",
                    resource="user",
                    resource_id=str(account_id),
                    after=lockout_event,
                )
            raise ValueError(rejection or INVALID_CREDENTIALS_MESSAGE)
        await self.audit.record(
            user_id=account_id,
            action="LOGIN_SUCCESS",
            resource="authentication",
            resource_id=str(account_id),
            after={"outcome": "success"},
        )
        return output


class SignUpUseCase(BaseUseCase[SignUpOutputDTO]):
    def __init__(self, uow: GenUnitOfWork, security_service):
        self.uow = uow
        self.security_service = security_service

    async def _execute(self, input_dto: SignUpInputDTO) -> SignUpOutputDTO:
        email = input_dto.email.strip().lower()
        employee_code = input_dto.employee_code.strip()

        async with self.uow as uow:
            employee_repo = uow.get_repo(EmployeeEntity, EmployeeModel)
            employee = await employee_repo.find_one(
                EmployeeModel.employee_no == employee_code,
                EmployeeModel.is_active.is_(True),
            )
            if not employee:
                raise ValueError("Employee code is not registered")

            user, _ = await create_user_account(
                uow,
                employee=employee,
                email=email,
                password_hash=self.security_service.get_password_hash(input_dto.password),
                role_code=input_dto.role_code,
                account_status=AccountStatus.ACTIVE,
                actor_id=input_dto.created_by,
                password_set_by_user=True,
            )
            if user.id is None:
                raise RuntimeError("Created user account has no ID.")
            role, role_codes = await get_app_role(uow, user.id)

            return SignUpOutputDTO(
                access_token=self.security_service.create_access_token(
                    _build_token_payload(user, role, role_codes)
                ),
                employee_name=employee_display_name(employee),
                token_type="bearer",
                expires_in_hours=12,
                role=role.value,
                role_code=role_codes,
            )
