"""Contratos JSON del inicio de sesión y los usuarios."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RoleName = Literal["owner", "member", "guest"]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64, examples=["dueno"])
    password: str = Field(min_length=1, max_length=256)


class SetupIn(BaseModel):
    password: str = Field(min_length=8, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime


class MeOut(BaseModel):
    user: UserOut | None
    needs_setup: bool = False
    auth_enabled: bool = True


class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=32, examples=["laura"])
    display_name: str = Field(default="", max_length=64, examples=["Laura"])
    password: str = Field(min_length=8, max_length=256)
    role: RoleName = "member"


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=64)
    role: RoleName | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)
