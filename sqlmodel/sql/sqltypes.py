from collections.abc import Mapping, Sequence
from typing import (
    Any,
    Generic,
    TypeVar,
    cast,
)

from pydantic import BaseModel, TypeAdapter
from sqlalchemy import JSON, TypeDecorator, types
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine.interfaces import Dialect


class AutoString(TypeDecorator):
    impl = types.String
    cache_ok = True
    mysql_default_length = 255

    def load_dialect_impl(self, dialect: Dialect) -> types.TypeEngine[Any]:
        impl = cast(types.String, self.impl)
        if impl.length is None and dialect.name == "mysql":
            return dialect.type_descriptor(types.String(self.mysql_default_length))
        return super().load_dialect_impl(dialect)


T = TypeVar("T", bound=BaseModel | Sequence[BaseModel] | Mapping[str, BaseModel])


class PydanticJSONB(TypeDecorator, Generic[T]):
    """Custom type to automatically handle Pydantic model serialization."""

    impl = JSON().with_variant(JSONB, "postgresql")
    cache_ok = True  # allow SQLAlchemy to cache results

    def __init__(
        self,
        model_class: type[T],
        *args: Any,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self.adapter = TypeAdapter(model_class)
        self.coerce_compared_value = self.impl.coerce_compared_value

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        return self.adapter.dump_python(value, mode="json")

    def process_result_value(self, value: Any, dialect: Dialect) -> T | None:
        if value is None:
            return None
        return self.adapter.validate_python(value)
