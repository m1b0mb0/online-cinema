import os

from src.database.models.accounts import (
    ActivationTokenModel,
    PasswordResetTokenModel,
    RefreshTokenModel,
    UserGroupEnum,
    UserGroupModel,
    UserModel,
    UserProfileModel,
)
from src.database.models.base import Base
from src.database.models.cart import CartItemModel, CartModel
from src.database.models.comments import CommentModel
from src.database.models.favorites import FavoriteModel
from src.database.models.movies import (
    CertificationModel,
    DirectorModel,
    GenreModel,
    MovieDirectorsModel,
    MovieGenresModel,
    MovieModel,
    MovieStarsModel,
    StarModel,
)
from src.database.models.order import OrderItemModel, OrderModel, OrderStatusEnum
from src.database.models.payments import (
    PaymentItemModel,
    PaymentModel,
    PaymentStatusEnum,
)
from src.database.models.ratings import MovieRatingModel
from src.database.models.reactions import (
    CommentReactionModel,
    MovieReactionModel,
    ReactionMixin,
    ReactionTypeEnum,
)
from src.database.validators import accounts as accounts_validators

environment = os.getenv("ENVIRONMENT", "developing")

if environment == "testing":
    from src.database.session_sqlite import (
        get_sqlite_db as get_db,
    )
    from src.database.session_sqlite import (
        get_sqlite_db_contextmanager as get_db_contextmanager,
    )
    from src.database.session_sqlite import (
        reset_sqlite_database as reset_database,
    )
else:
    from src.database.session import (
        get_async_session as get_db,
    )
    from src.database.session import (
        get_postgresql_db_contextmanager as get_db_contextmanager,
    )

    async def reset_database() -> None:
        raise RuntimeError("Database reset is only available in testing environment.")
