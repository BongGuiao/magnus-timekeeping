from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

from app.core.generics.uow import get_unit_of_work, GenUnitOfWork
from app.audit.infrastructure.dependencies import get_audit_es_client
from app.auth.application.change_password_use_case import ChangePasswordUseCase, LockoutPolicy
from app.auth.application.use_case import (
    LoginUseCase,
    SearchUserByEmployeeCodeUseCase,
    SignUpUseCase,
)
from app.auth.infrastructure.adapters import Argon2PasswordHasher, ElasticsearchAuditTrail
from app.auth.infrastructure.user_account_repository import SqlAlchemyUserAccountUnitOfWork
from app.core import security as security_service
from app.core.config import settings
from app.auth.domain.entities.user import Role

bearer_scheme = HTTPBearer()

def get_login_use_case(
        uow: GenUnitOfWork = Depends(get_unit_of_work),
        es_client=Depends(get_audit_es_client),
        ) -> LoginUseCase:
    return LoginUseCase(uow, security_service, ElasticsearchAuditTrail(es_client))

def get_signup_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> SignUpUseCase:
    return SignUpUseCase(uow, security_service)

def get_change_password_use_case(
        uow: GenUnitOfWork = Depends(get_unit_of_work),
        es_client=Depends(get_audit_es_client),
        ) -> ChangePasswordUseCase:
    return ChangePasswordUseCase(
        SqlAlchemyUserAccountUnitOfWork(uow),
        Argon2PasswordHasher(),
        ElasticsearchAuditTrail(es_client),
        LockoutPolicy(settings.AUTH_MAX_FAILED_LOGIN_ATTEMPTS, settings.AUTH_LOCKOUT_MINUTES),
    )

def get_search_user_by_employee_code_use_case(
        uow: GenUnitOfWork = Depends(get_unit_of_work)
        ) -> SearchUserByEmployeeCodeUseCase:
    return SearchUserByEmployeeCodeUseCase(uow)

def get_current_user_claims(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    try:
        return security_service.decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials"
        )

def require_role(allowed_roles: list[Role]):
    def role_checker(claims: dict = Depends(get_current_user_claims)):
        user_role = claims.get("role")
        if user_role not in [role.value for role in allowed_roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied"
            )
        return claims
    return role_checker