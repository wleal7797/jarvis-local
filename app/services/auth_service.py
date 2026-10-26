"""Inicio de sesión y usuarios (Etapa 11).

- **Contraseñas con Argon2** (argon2-cffi): ganador de la Password Hashing Competition.
  Es lento a propósito y usa memoria, así que adivinar contraseñas por fuerza bruta es caro.
- **Sesión en una cookie firmada (JWT, HS256)**: dice quién es y qué rol tiene, y vence a
  los 30 días. La cookie es `HttpOnly` (el JavaScript de la página no la puede leer) y
  `SameSite=Lax` (otros sitios no la pueden usar para hablar con JARVIS).
- **Límite de intentos**: 5 contraseñas equivocadas seguidas bloquean ese usuario 5 minutos.
- **Roles**:
  - `owner` (dueño): todo, incluido crear usuarios.
  - `member` (familia): conversar, su memoria, sus documentos personales y los de la casa.
  - `guest` (invitado): sólo conversar; no ve documentos ni recuerdos, y JARVIS no aprende
    nada de lo que dice.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import User
from app.models.user import ROLES
from app.repositories import UserRepository

SESSION_COOKIE = "jarvis_session"
UNUSABLE_PASSWORD = "!"  # el dueño de `scripts/seed.py` antes de elegir su contraseña
MIN_PASSWORD = 8
MAX_FAILURES = 5
LOCK_SECONDS = 300

_hasher = PasswordHasher()


class AuthError(Exception):
    """Usuario o contraseña incorrectos (no se dice cuál de los dos)."""


class LockedError(AuthError):
    def __init__(self, seconds: int) -> None:
        super().__init__(f"Demasiados intentos. Espere {seconds} s.")
        self.seconds = seconds


class UserError(ValueError):
    """Datos de usuario inválidos (nombre repetido, contraseña corta, rol desconocido…)."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def has_password(user: User) -> bool:
    return user.password_hash not in ("", UNUSABLE_PASSWORD)


@dataclass(frozen=True)
class Session:
    user_id: int
    role: str


class AuthService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_key: str,
        *,
        session_days: int = 30,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._session_factory = session_factory
        self._secret = secret_key
        self._seconds = session_days * 86400
        self._clock = clock
        self._failures: dict[str, tuple[int, float]] = {}  # usuario → (fallos, bloqueado hasta)

    # ---------- Sesiones ----------

    @property
    def session_seconds(self) -> int:
        return self._seconds

    def issue(self, user: User) -> str:
        now = int(self._clock())
        claims = {"sub": str(user.id), "role": user.role, "iat": now, "exp": now + self._seconds}
        return jwt.encode(claims, self._secret, algorithm="HS256")

    def read(self, token: str | None) -> Session | None:
        if not token:
            return None
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                options={"require": ["sub", "exp"], "verify_exp": False},
                leeway=0,
            )
        except jwt.PyJWTError:
            return None
        if claims["exp"] < self._clock():  # el vencimiento se revisa con el reloj del servicio
            return None
        return Session(user_id=int(claims["sub"]), role=str(claims.get("role", "")))

    # ---------- Entrar ----------

    async def needs_setup(self, owner_username: str) -> bool:
        """¿El dueño todavía no eligió contraseña? (primera vez que se abre JARVIS)."""
        async with self._session_factory() as session:
            owner = await UserRepository(session).get_by_username(owner_username)
            return owner is not None and not has_password(owner)

    async def setup_owner(self, owner_username: str, password: str) -> User:
        """Elegir la contraseña del dueño. Sólo funciona una vez."""
        _check_password(password)
        async with self._session_factory() as session:
            owner = await UserRepository(session).get_by_username(owner_username)
            if owner is None or has_password(owner):
                raise UserError("El dueño ya tiene contraseña.")
            owner.password_hash = hash_password(password)
            await session.commit()
            return owner

    async def authenticate(self, username: str, password: str) -> User:
        key = username.strip().lower()
        self._check_lock(key)
        async with self._session_factory() as session:
            user = await UserRepository(session).get_by_username(key)
            valid = (
                user is not None
                and user.is_active
                and has_password(user)
                and verify_password(user.password_hash, password)
            )
            if user is None:
                hash_password(password)  # mismo tiempo exista o no: no revela quién existe
            if not valid:
                self._fail(key)
                raise AuthError("Usuario o contraseña incorrectos.")
            if _hasher.check_needs_rehash(user.password_hash):
                user.password_hash = hash_password(password)
                await session.commit()
        self._failures.pop(key, None)
        return user

    def _check_lock(self, key: str) -> None:
        count, until = self._failures.get(key, (0, 0.0))
        remaining = int(until - self._clock())
        if count >= MAX_FAILURES and remaining > 0:
            raise LockedError(remaining)
        if count >= MAX_FAILURES:
            self._failures.pop(key, None)  # pasó el bloqueo: empieza de cero

    def _fail(self, key: str) -> None:
        count, _ = self._failures.get(key, (0, 0.0))
        count += 1
        until = self._clock() + LOCK_SECONDS if count >= MAX_FAILURES else 0.0
        self._failures[key] = (count, until)

    # ---------- Usuarios (sólo el dueño) ----------

    async def list_users(self) -> Sequence[User]:
        async with self._session_factory() as session:
            return await UserRepository(session).list_all()

    async def create_user(self, username: str, display_name: str, password: str, role: str) -> User:
        username = username.strip().lower()
        if not username.isascii() or not username.replace(".", "").replace("_", "").isalnum():
            raise UserError("El usuario sólo puede tener letras, números, punto y guion bajo.")
        _check_role(role)
        _check_password(password)
        async with self._session_factory() as session:
            repo = UserRepository(session)
            if await repo.get_by_username(username) is not None:
                raise UserError("Ya existe un usuario con ese nombre.")
            user = await repo.add(
                User(
                    username=username,
                    display_name=display_name.strip() or username,
                    password_hash=hash_password(password),
                    role=role,
                )
            )
            await session.commit()
            return user

    async def update_user(
        self,
        actor_id: int,
        user_id: int,
        *,
        role: str | None = None,
        is_active: bool | None = None,
        password: str | None = None,
        display_name: str | None = None,
    ) -> User:
        async with self._session_factory() as session:
            user = await UserRepository(session).get(user_id)
            if user is None:
                raise LookupError(user_id)
            if user_id == actor_id and (role not in (None, "owner") or is_active is False):
                raise UserError("No puede quitarse a sí mismo el rol de dueño ni desactivarse.")
            if role is not None:
                _check_role(role)
                user.role = role
            if is_active is not None:
                user.is_active = is_active
            if password is not None:
                _check_password(password)
                user.password_hash = hash_password(password)
            if display_name:
                user.display_name = display_name.strip()
            await session.commit()
            await session.refresh(user)
            return user


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise UserError(f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres.")


def _check_role(role: str) -> None:
    if role not in ROLES:
        raise UserError(f"Rol desconocido: {role}")
