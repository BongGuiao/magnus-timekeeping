# app/core/generics/uc_base.py
from abc import ABC, abstractmethod
from typing import TypeVar, Generic, Any
import logging

logger = logging.getLogger(__name__)

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")

class BaseUseCase(ABC, Generic[OutputT]):
    """
    A generic base use case class that standardizes execution wrappers,
    error handling, and logging across all application use cases.
    """
    @abstractmethod
    async def _execute(self, *args: Any, **kwargs: Any) -> OutputT:
        """Core business logic implemented by child use cases."""
        pass

    async def execute(self, *args: Any, **kwargs: Any) -> OutputT:
        """Standardized execution wrapper with centralized error handling."""
        use_case_name = self.__class__.__name__
        try:
            logger.info(f"Executing use case: {use_case_name}")
            result = await self._execute(*args, **kwargs)
            logger.info(f"Successfully executed use case: {use_case_name}")
            return result
        except ValueError as ve:
            # Re-raise validation errors directly so routers can map them to 400 Bad Request
            raise ve
        except Exception as e:
            logger.error(f"Failed use case {use_case_name}: {str(e)}", exc_info=True)
            raise RuntimeError(f"Use Case {use_case_name} execution failed: {str(e)}") from e