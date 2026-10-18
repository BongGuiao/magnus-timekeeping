from enum import Enum
from typing import TypeVar, Type, Any, Generic,Optional,get_type_hints
from datetime import datetime
import inspect
from decimal import Decimal
from pydantic import BaseModel
from sqlalchemy.types import String
from sqlalchemy import JSON, Date, DateTime, Numeric, Float, Integer, Boolean

from sqlalchemy import inspect as sa_inspect

T_Entity = TypeVar("T_Entity")
T_Model = TypeVar("T_Model")
T = TypeVar('T')
class GenericMapper:
    @staticmethod
    def _extract_dict(obj: Any) -> dict:
        """Helper to convert dicts, dataclasses, Pydantic models, or standard objects to a dict."""
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump") and callable(obj.model_dump):  # Pydantic v2
            return obj.model_dump()
        if hasattr(obj, "dict") and callable(obj.dict):  # Pydantic v1
            return obj.dict()
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        return {}
    @staticmethod
    def to_model(entity: Any, model_cls: Type[T_Model]) -> Optional[T_Model]:
        if not entity:
            return None

        raw_dict = GenericMapper._extract_dict(entity)

        # 1. Dynamically unpack/flatten nested dicts/objects (e.g., entity.address)
        entity_dict = {}
        mapper = sa_inspect(model_cls)
        valid_columns = {col.key: col for col in mapper.column_attrs}
        for k, v in raw_dict.items():
            if (
                isinstance(v, dict)
                and k in valid_columns
                and isinstance(valid_columns[k].expression.type, JSON)
            ):
                entity_dict[k] = v
            elif isinstance(v, (datetime, str, int, float, bool, Decimal, type(None))):
                entity_dict[k] = v
            elif isinstance(v, Enum):
                # Extract the raw primitive value from the Enum (e.g., "R", "A")
                entity_dict[k] = v.value
            else:
                # Unpack nested object (e.g. Address) into root level keys
                nested_dict = GenericMapper._extract_dict(v)
                if nested_dict:
                    entity_dict.update(nested_dict)
                else:
                    entity_dict[k] = v

        # 2. Inspect target SQLAlchemy model columns
        model_data = {}
        for k, v in entity_dict.items():
            if k in valid_columns:
                col_attr = valid_columns[k]
                col_type = col_attr.expression.type

                # Convert Python bool -> "Y"/"N" if target DB column is String/VARCHAR
                if isinstance(v, bool) and isinstance(col_type, String):
                    v = "Y" if v else "N"

                # Truncate strings exceeding column max length
                elif isinstance(v, str) and isinstance(col_type, String) and col_type.length:
                    if len(v) > col_type.length:
                        v = v[: col_type.length]

                # Parse ISO date strings
                elif isinstance(v, str):
                    try:
                        v = datetime.fromisoformat(v.replace("Z", "+00:00"))
                    except ValueError:
                        pass

                # Strip timezone only when the database column is timezone-naive.
                if (
                    isinstance(v, datetime)
                    and v.tzinfo is not None
                    and isinstance(col_type, DateTime)
                    and not col_type.timezone
                ):
                    v = v.replace(tzinfo=None)

                model_data[k] = v

        return model_cls(**model_data)

    @staticmethod
    def to_entity(db_model: Any, entity_cls: Type[T_Entity]) -> Optional[T_Entity]:
        if not db_model:
            return None

        is_dict = isinstance(db_model, dict)
        model_dict = db_model if is_dict else db_model.__dict__

        sig = inspect.signature(entity_cls)
        type_hints = get_type_hints(entity_cls) if hasattr(entity_cls, "__annotations__") else {}

        entity_data = {}
        
        for param_name, param in sig.parameters.items():
            param_type = type_hints.get(param_name, param.annotation)

            v = None
            has_value = False

            if is_dict:
                if param_name in db_model:
                    v = db_model[param_name]
                    has_value = True
            else:
                # 1. Exact original behavior: check instance dict/columns first
                if param_name in model_dict:
                    v = model_dict[param_name]
                    has_value = True
                
                # 2. Safely check if it's a Python @property on the class (like account_balance)
                # This explicitly avoids SQLAlchemy relationships (area_rel, charges, etc.)
                elif hasattr(db_model, param_name):
                    class_attr = getattr(type(db_model), param_name, None)
                    if isinstance(class_attr, property):
                        v = getattr(db_model, param_name)
                        has_value = True

            if has_value:
                # Convert "Y"/"N" back to bool if entity expects bool
                if isinstance(v, str) and param_type is bool:
                    v = v.upper() in ("Y", "YES", "TRUE", "1")

                # Parse ISO date strings
                elif isinstance(v, str):
                    try:
                        v = datetime.fromisoformat(v.replace("Z", "+00:00"))
                    except ValueError:
                        pass

                entity_data[param_name] = v

            # 3. Reconstruct nested value object (e.g. Address) if parameter is a class type
            elif inspect.isclass(param_type) and not issubclass(param_type, (str, int, float, bool, datetime, Decimal)):
                nested_source = db_model.get(param_name) if is_dict else getattr(db_model, param_name, None)
                if nested_source:
                    nested_entity = GenericMapper.to_entity(nested_source, param_type)
                    if nested_entity:
                        entity_data[param_name] = nested_entity

        return entity_cls(**entity_data)
    @staticmethod

    def update_model(
        db_model: Any,
        entity: Any,
        exclude_fields: Optional[list[str]] = None,
    ) -> Any:
        if not db_model or not entity:
            return db_model

        exclude_fields = set(exclude_fields or ["id", "date_add"])

        # 1. Standardize input payload (Entity or Dict) to dict
        if isinstance(entity, dict):
            entity_dict = entity
        elif hasattr(entity, "model_dump"):  # Pydantic v2
            #entity_dict = entity.model_dump(exclude_unset=True)
            entity_dict = entity.model_dump()
        elif hasattr(entity, "dict"):  # Pydantic v1
            entity_dict = entity.dict(exclude_unset=True)
        else:
            entity_dict = getattr(entity, "__dict__", {})

        # 2. Inspect database model columns and attributes
        state = sa_inspect(db_model)
        mapper = state.mapper if state else None

        # Build attribute & column maps for exact and normalized lookups
        model_attrs = {}  # { 'contractdate': 'contractdate', 'contract_date': 'contractdate' }
        column_type_map = {}  # { 'contractdate': DateTime }

        if mapper:
            for prop in mapper.column_attrs:
                attr_name = prop.key
                column = prop.columns[0]

                # Map exact attribute name
                model_attrs[attr_name] = attr_name
                column_type_map[attr_name] = type(column.type)

                # Map normalized snake_case / un-underscored variations
                normalized = attr_name.lower().replace("_", "")
                model_attrs[normalized] = attr_name

        # 3. Apply updates
        for raw_key, new_value in entity_dict.items():
            if raw_key in exclude_fields or raw_key.startswith("_"):
                continue

            # Match incoming payload key to model attribute name
            matched_attr = model_attrs.get(
                raw_key
            ) or model_attrs.get(raw_key.lower().replace("_", ""))

            if not matched_attr or not hasattr(db_model, matched_attr):
                continue

            col_type = column_type_map.get(matched_attr)

            # 4. Type Conversions
            if col_type:
                # DateTime / Date conversion
                if issubclass(col_type, (DateTime, Date)) and isinstance(
                    new_value, str
                ):
                    if new_value.strip():
                        try:
                            parsed_dt = datetime.fromisoformat(
                                new_value.replace("Z", "+00:00")
                            )
                            new_value = (
                                parsed_dt.date()
                                if issubclass(col_type, Date)
                                and not issubclass(col_type, DateTime)
                                else parsed_dt
                            )
                        except ValueError:
                            pass
                    else:
                        new_value = None

                # Numeric / Decimal conversion
                elif issubclass(col_type, (Numeric, Float)) and isinstance(
                    new_value, (str, int, float)
                ):
                    try:
                        new_value = Decimal(str(new_value))
                    except Exception:
                        pass

                # Integer conversion
                elif issubclass(col_type, Integer) and isinstance(
                    new_value, str
                ):
                    try:
                        new_value = int(new_value)
                    except ValueError:
                        pass

                # Boolean conversion
                elif issubclass(col_type, Boolean) and isinstance(
                    new_value, str
                ):
                    new_value = new_value.lower() in ("true", "1", "yes")

            # 5. Assign attribute if changed
            try:
                current_value = getattr(db_model, matched_attr)
                
                # Optional: handle timezone alignment if comparing datetimes
                if isinstance(current_value, datetime) and isinstance(new_value, datetime):
                    if current_value.tzinfo and not new_value.tzinfo:
                        new_value = new_value.replace(tzinfo=current_value.tzinfo)
                    elif not current_value.tzinfo and new_value.tzinfo:
                        current_value = current_value.replace(tzinfo=new_value.tzinfo)

                if current_value != new_value:
                    setattr(db_model, matched_attr, new_value)
            except Exception:
                # Fallback: if any comparison error occurs, force-set the value
                setattr(db_model, matched_attr, new_value)

        return db_model

class MetaSchema(BaseModel):
    total_records: int


class ListResponseEnvelope(BaseModel, Generic[T]):
    status: str = "success"
    data: list[T] 
    meta: MetaSchema | None = None


class ResponseEnvelope(BaseModel, Generic[T]):
    status: str = "success"
    data: T