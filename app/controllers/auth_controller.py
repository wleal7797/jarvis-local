"""Controlador de inicio de sesión y usuarios (Etapa 11).

- `/api/auth/login` · `/api/auth/logout` · `/api/auth/me` · `/api/auth/setup`
- `/api/users` (sólo el dueño): crear usuarios, cambiar su rol, su contraseña o desactivarlos.
"""

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.dependencies import AuthServiceDep, OptionalUserDep, OwnerDep, SettingsDep
from app.schemas.auth import LoginIn, MeOut, SetupIn, UserIn, UserOut, UserUpdate
from app.services.auth_service import SESSION_COOKIE, AuthError, LockedError, UserError

router = APIRouter(prefix="/api", tags=["inicio de sesión"])


def _require(auth):
    if auth is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Inicio de sesión no disponible")
    return auth


def _set_cookie(request: Request, response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,  # el JavaScript de la página no la puede leer
        samesite="lax",  # otros sitios no la pueden usar
        secure=request.url.scheme == "https",  # detrás de Caddy (HTTPS) sólo viaja cifrada
        path="/",
    )


@router.get("/auth/me", response_model=MeOut, summary="¿Quién soy? (y si falta crear el dueño)")
async def me(user: OptionalUserDep, settings: SettingsDep, auth: AuthServiceDep):
    needs_setup = bool(auth) and await auth.needs_setup(settings.default_username)
    return MeOut(
        user=UserOut.model_validate(user) if user else None,
        needs_setup=needs_setup,
        auth_enabled=settings.auth_enabled,
    )


@router.post("/auth/setup", response_model=UserOut, summary="Primera vez: contraseña del dueño")
async def setup(
    body: SetupIn, request: Request, response: Response, settings: SettingsDep, auth: AuthServiceDep
):
    auth = _require(auth)
    try:
        owner = await auth.setup_owner(settings.default_username, body.password)
    except UserError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    _set_cookie(request, response, auth.issue(owner), auth.session_seconds)
    return owner


@router.post("/auth/login", response_model=UserOut, summary="Entrar con usuario y contraseña")
async def login(body: LoginIn, request: Request, response: Response, auth: AuthServiceDep):
    auth = _require(auth)
    try:
        user = await auth.authenticate(body.username, body.password)
    except LockedError as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, str(exc), headers={"Retry-After": str(exc.seconds)}
        ) from None
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
    _set_cookie(request, response, auth.issue(user), auth.session_seconds)
    return user


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Salir")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/users", response_model=list[UserOut], summary="Usuarios (sólo el dueño)")
async def list_users(owner: OwnerDep, auth: AuthServiceDep):
    return await _require(auth).list_users()


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un usuario (sólo el dueño)",
)
async def create_user(body: UserIn, owner: OwnerDep, auth: AuthServiceDep):
    try:
        return await _require(auth).create_user(
            body.username, body.display_name, body.password, body.role
        )
    except UserError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


@router.patch(
    "/users/{user_id}",
    response_model=UserOut,
    summary="Cambiar rol, nombre, contraseña o desactivar (sólo el dueño)",
)
async def update_user(user_id: int, body: UserUpdate, owner: OwnerDep, auth: AuthServiceDep):
    try:
        return await _require(auth).update_user(
            owner.id,
            user_id,
            role=body.role,
            is_active=body.is_active,
            password=body.password,
            display_name=body.display_name,
        )
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado") from None
    except UserError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
