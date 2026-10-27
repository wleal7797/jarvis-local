"""Usuarios."""

from sqlalchemy import select

from app.models import User
from app.repositories.base_repository import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_username(self, username: str) -> User | None:
        return await self.session.scalar(select(User).where(User.username == username))

    async def list_all(self) -> list[User]:
        return list((await self.session.scalars(select(User).order_by(User.id))).all())
