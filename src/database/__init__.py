import os

from src.database.models.base import Base
from src.database.models.accounts import (
    UserModel,
    UserGroupModel,
    UserGroupEnum,
    ActivationTokenModel,
    PasswordResetTokenModel,
    RefreshTokenModel,
    UserProfileModel,
)
from src.database.validators import accounts as accounts_validators

from src.database.models.movies import (
    MovieModel,
    StarModel,
    GenreModel,
    DirectorModel,
    CertificationModel,
    MovieStarsModel,
    MovieGenresModel,
    MovieDirectorsModel,
)

environment = os.getenv("ENVIRONMENT", "developing")

if environment == "testing":
    from src.database.session_sqlite import (
        get_sqlite_db as get_db,
        get_sqlite_db_contextmanager as get_db_contextmanager,
        reset_sqlite_database as reset_database,
    )
else:
    from src.database.session import (
        get_async_session as get_db,
        get_postgresql_db_contextmanager as get_db_contextmanager,
    )

    async def reset_database() -> None:
        raise RuntimeError("Database reset is only available in testing environment.")
