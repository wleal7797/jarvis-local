"""Base común de todas las entidades."""

from datetime import datetime
from typing import Any

from sqlalchemy import TIMESTAMP, BigInteger, CheckConstraint, Identity, MetaData, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Dimensiones de los vectores de bge-m3.
EMBEDDING_DIM = 1024

# Nombres predecibles para índices y restricciones: así las migraciones son estables.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        str: Text,
        datetime: TIMESTAMP(timezone=True),
        dict[str, Any]: JSONB,
    }


class IdMixin:
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


def check_in(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    """Restricción CHECK que limita una columna de texto a una lista de valores."""
    options = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({options})", name=name)
