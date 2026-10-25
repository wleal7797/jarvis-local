"""Usuarios de JARVIS: el dueño, la familia y los invitados."""

from typing import TYPE_CHECKING, Literal

from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, IdMixin, check_in

if TYPE_CHECKING:
    from app.models.conversation import Conversation
    from app.models.memory import Memory

Role = Literal["owner", "member", "guest"]
ROLES: tuple[Role, ...] = ("owner", "member", "guest")


class User(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "users"
    __table_args__ = (check_in("role", ROLES, "role"),)

    username: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[str]
    password_hash: Mapped[str]  # Argon2 (Etapa 11)
    role: Mapped[str] = mapped_column(server_default=text("'member'"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )
    memories: Mapped[list["Memory"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )
