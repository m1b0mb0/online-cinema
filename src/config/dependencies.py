from functools import lru_cache

from fastapi import Depends

from src.config.settings import Settings
from src.security.interfaces import JWTAuthManagerInterface
from src.security.token_manager import JWTAuthManager


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_jwt_auth_manager(
    settings: Settings = Depends(get_settings),
) -> JWTAuthManagerInterface:
    return JWTAuthManager(
        secret_key_access=settings.SECRET_KEY_ACCESS,
        secret_key_refresh=settings.SECRET_KEY_REFRESH,
        algorithm=settings.JWT_SIGNING_ALGORITHM,
    )
