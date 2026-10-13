from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from elasticsearch import AsyncElasticsearch

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.application.use_case import (
    LoginUseCase,
    LoginInputDTO,
    LoginOutputDTO,
    SignUpUseCase,
    SignUpInputDTO,
    SignUpOutputDTO,
    SearchUserByEmployeeCodeUseCase,
    SearchUserByEmployeeCodeInputDTO,
    SearchUserByEmployeeCodeOutputDTO,
)
from app.auth.infrastructure.dependencies import (
    get_login_use_case,
    get_signup_use_case,
    get_search_user_by_employee_code_use_case,
    require_role,
)
from app.auth.domain.entities.user import DEFAULT_SIGNUP_ROLE_CODE, Role
from app.core.generics.mapper import ResponseEnvelope
router = APIRouter(prefix="/auth", tags=["Authentication"])

class LoginRequestSchema(BaseModel):
    # Accepts either the account's email address or employee code
    identifier: str = Field(min_length=1)
    password: str

class SignUpRequestSchema(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    employee_code: str = Field(min_length=1)
    # Kept for backward compatibility; the display name now comes from hr.employees.
    employee_name: Optional[str] = None
    role_code: str = Field(default=DEFAULT_SIGNUP_ROLE_CODE, min_length=1, max_length=50)

class TokenResponseSchema(BaseModel):
    access_token: str
    role: str
    role_code: list[str]
    expires_in_hours: int
    token_type: str
    employee_name: str

class UserResponseSchema(BaseModel):
    id: Optional[UUID] = None
    employee_id: Optional[UUID] = None
    email: str
    employee_code: str
    employee_name: str
    role: str
    role_codes: list[str] = []
    account_status: str
    is_active: bool
    photo_reference: str | None = None

@router.post("/login", response_model=ResponseEnvelope[TokenResponseSchema])
async def login(
    request: LoginRequestSchema, 
    use_case: LoginUseCase = Depends(get_login_use_case)
):
    input_dto = LoginInputDTO(identifier=request.identifier, password=request.password)
    # Invoking execute() triggers logger.info, error catching, and calls _execute()
    result: LoginOutputDTO = await use_case.execute(input_dto)

    return ResponseEnvelope[TokenResponseSchema](
        data=TokenResponseSchema(
            access_token=result.access_token,
            token_type=result.token_type,
            expires_in_hours=result.expires_in_hours,
            role=result.role,
            role_code=result.role_code,
            employee_name=result.employee_name
        )
    )

@router.post("/signup", response_model=TokenResponseSchema, status_code=status.HTTP_201_CREATED)
async def signup(
    request: SignUpRequestSchema,
    claims: dict = Depends(require_role([Role.ADMIN])),
    use_case: SignUpUseCase = Depends(get_signup_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    try:
        actor_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identity in authentication token.",
        ) from error

    input_dto = SignUpInputDTO(
        email=request.email,
        password=request.password,
        employee_code=request.employee_code,
        role_code=request.role_code,
        created_by=actor_id,
        updated_by=actor_id,
    )
    result: SignUpOutputDTO = await use_case.execute(input_dto)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CREATE",
        resource="user",
        resource_id=request.employee_code,
        after={
            "email": request.email,
            "employee_code": request.employee_code,
            "employee_name": result.employee_name,
            "role": result.role,
            "role_code": result.role_code,
        },
    )

    return TokenResponseSchema(
        access_token=result.access_token,
        token_type=result.token_type,
        expires_in_hours=result.expires_in_hours,
        role=result.role,
        role_code=result.role_code,
        employee_name=result.employee_name
    )

@router.get("/users/search", response_model=ResponseEnvelope[UserResponseSchema])
async def search_user_by_employee_code(
    employee_code: str,
    claims: dict = Depends(require_role([Role.ADMIN])),
    use_case: SearchUserByEmployeeCodeUseCase = Depends(get_search_user_by_employee_code_use_case),
):
    input_dto = SearchUserByEmployeeCodeInputDTO(employee_code=employee_code.strip())
    user: SearchUserByEmployeeCodeOutputDTO = await use_case.execute(input_dto)

    return ResponseEnvelope[UserResponseSchema](
        data=UserResponseSchema(
            id=user.id,
            employee_id=user.employee_id,
            email=user.email,
            employee_code=user.employee_code,
            employee_name=user.employee_name,
            role=user.role.value,
            role_codes=user.role_codes,
            account_status=user.account_status,
            is_active=user.is_active,
            photo_reference=user.photo_reference,
        )
    )

@router.get("/admin-dashboard")
def admin_dashboard(claims: dict = Depends(require_role([Role.ADMIN]))):
    return {"message": f"Welcome Admin {claims['email']}!"}