# Storing Pydantic Models in JSONB Columns

You can store Pydantic models (including lists or dictionaries of models) in
JSON or JSONB database columns using `PydanticJSONB`.

This is especially useful when:

- You want to persist flexible, nested data structures in your models.
- You prefer to avoid separate relational tables for structured fields like
  metadata, config, or address.
- You want automatic serialization and deserialization with Pydantic.

## Requirements

- PostgreSQL for full `JSONB` support, or any database that supports `JSON`.
- Pydantic v2.
- SQLAlchemy 2.x.

## Usage

You can use it with SQLModel like this:

```python
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Column
from sqlmodel.sql.sqltypes import PydanticJSONB

class Address(BaseModel):
    street: str
    city: str

class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    address: Address = Field(sa_column=Column(PydanticJSONB(Address)))
```

This stores `address` as a `JSONB` column in PostgreSQL (or `JSON` in other
databases) and automatically serializes/deserializes to and from the `Address`
model.

If you're using a `list` or `dict` of models, `PydanticJSONB` supports that too:

```python
Field(sa_column=Column(PydanticJSONB(list[SomeModel])))
Field(sa_column=Column(PydanticJSONB(dict[str, SomeModel])))
```

## Create & Store Data

Here's how to create and store data with Pydantic models:

```python
from sqlmodel import Session, create_engine

engine = create_engine("postgresql://user:password@localhost/db")

# Insert a User with an Address
with Session(engine) as session:
    user = User(
        name="John Doe",
        address=Address(street="123 Main St", city="New York")
    )
    session.add(user)
    session.commit()
```

## Retrieve & Use Data

When you retrieve the data, it's automatically converted back to a Pydantic
model:

```pythonwith Session(engine) as session:
    user = session.query(User).first()
    print(user.address.street)  # "123 Main St"
    print(user.address.city)    # "New York"
    print(type(user.address))   # <class '__main__.Address'>
```

Result:

- ✅ No need for `Address(**user.address)`; it is already an `Address` instance.
- ✅ Automatic conversion between JSONB and Pydantic models.

This simplifies handling structured data in SQLModel, making JSONB storage
seamless and ergonomic. 🚀

## Alembic Migrations

To work with Alembic autogeneration, use the `render_item` hook to render
`PydanticJSONB` as the corresponding JSON type for your database. The example
below shows PostgreSQL `JSONB`.

```python
# env.py

from typing import TYPE_CHECKING, Any, Literal

from sqlmodel.sql.sqltypes import PydanticJSONB

if TYPE_CHECKING:
    from alembic.autogenerate.api import AutogenContext

def render_item(
    type_: str,
    obj: Any,
    autogen_context: AutogenContext,
) -> str | Literal[False]:
    """Customize schema render."""
    if type_ == "type" and isinstance(obj, PydanticJSONB):
        autogen_context.imports.add("import sqlalchemy as sa")
        autogen_context.imports.add("from sqlalchemy.dialects import postgresql")
        return "postgresql.JSONB(astext_type=sa.Text())"
    return False

context.configure(
    ...
    render_item=render_item,
)
```

## Advanced Guide

This `PydanticJSONB` implementation uses the SQLAlchemy
[TypeDecorator](https://docs.sqlalchemy.org/en/21/core/custom_types.html#augmenting-existing-types)
API to create a new type and relies on `TypeDecorator` methods
`process_bind_param` and `process_result_value` to convert between Pydantic
models and JSON-serializable Python objects. Because the database ultimately
stores `str`/`bytes` (or driver-specific JSON representations), the output of
`process_bind_param` is converted again into `str`/`bytes`, and the input of
`process_result_value` was converted back from `str`/`bytes`. As a result, this
is effectively double serialization/deserialization:

Pydantic model <-> Python object <-> `str`/`bytes`

If you are willing to rely on non-guaranteed internals and driver implementation
details, you can implement your own `PydanticJSONB` by overriding
`bind_processor` and/or `result_processor`. In some cases, this can bypass the
`TypeDecorator` conversion path and convert between Pydantic models and
`str`/`bytes` directly.

**Note**: This optimization is only relevant when a SQLAlchemy dialect/driver
does not already provide native JSON serialization/deserialization, so that the
intermediate conversion on `TypeDecorator` can be bypassed. Depending on the
driver, a combination of `process_bind_param`/`process_result_value` and
`bind_processor`/`result_processor` may be the outcome.

```python
from typing import TYPE_CHECKING, Any

from sqlalchemy import Dialect


if TYPE_CHECKING:
    from sqlalchemy.sql.type_api import _BindProcessorType, _ResultProcessorType

# Only for SQLAlchemy driver dialect WITHOUT native JSON serialization
@override
def bind_processor(self, dialect: Dialect) -> _BindProcessorType:
    def processor(value: T | None) -> str | None:
        if value is None:
            return None
        # Adjust based on the driver behavior.
        return self.adapter.dump_json(value).decode("utf-8")

    return processor

# Only for SQLAlchemy driver dialect WITHOUT native JSON deserialization
@override
def result_processor(self, dialect: Dialect, coltype: Any) -> _ResultProcessorType:
    def processor(value: Any) -> T | None:
        if value is None:
            return None
        # Adjust based on the driver behavior.
        return self.adapter.validate_json(value)

    return processor
```

SQLAlchemy PostgreSQL driver details for reference:

| SQLAlchemy Driver Dialects | Native JSON Serialzation | Native JSON Deserialization |
| -------------------------- | ------------------------ | --------------------------- |
| PostgreSQL:asyncpg         | ❌                       | ✅                          |
| PostgreSQL:psycopg         | ✅                       | ✅                          |
| PostgreSQL:psycopg2        | ✅                       | ✅                          |
| PostgreSQL:psycopg2cffi    | ✅                       | ✅                          |
| PostgreSQL:pg8000          | ❌                       | ✅                          |

## Limitations

### Nested Model Updates

Currently, updating attributes inside a nested Pydantic model doesn't
automatically trigger a database update. This is similar to how plain
dictionaries work in SQLAlchemy. For example:

```python
# This won't trigger a database update
row = select(...)  # some MyTable row
row.data.x = 1
db.add(row)  # no effect, change isn't detected
```

To update nested model attributes, you need to reassign the entire model:

```python
# Workaround: Create a new instance and reassign
updated = ExtraData(**row.data.model_dump())
updated.x = 1
row.data = updated
db.add(row)
```

This limitation will be addressed in a future update using `MutableDict` to
enable change tracking for nested fields. The `MutableDict` implementation will
emit change events when the contents of the dictionary are altered, including
when values are added or removed.

## Notes

- Falls back to `JSON` if `JSONB` is not available.
- Only tested with PostgreSQL at the moment.
