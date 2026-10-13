from fastapi import Depends

from app.core.generics.uow import get_unit_of_work, GenUnitOfWork
from app.filemaintenance.companies.application.use_case import (
    CreateCompanyUseCase, 
    UpdateCompanyUseCase, 
    ListCompaniesUseCase, 
    GetCompanyUseCase
)



def get_create_company_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)
        ) -> CreateCompanyUseCase:
    return CreateCompanyUseCase(uow)
def get_update_company_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)
        ) -> UpdateCompanyUseCase:
    return UpdateCompanyUseCase(uow)
def get_company_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)
        ) -> GetCompanyUseCase:
    return GetCompanyUseCase(uow)
def get_list_companies_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)
        ) -> ListCompaniesUseCase:
    return ListCompaniesUseCase(uow)


