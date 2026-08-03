from src.services.accounts import (
    get_user_by_email,
    build_account_link,
    activate_user_account,
)
from src.services.movies import (
    apply_movie_filters,
    apply_movie_sorting,
    get_movie_by_uuid_or_404,
    get_or_create_models_by_name,
    get_named_models_page,
    get_genres_with_movie_counts,
    get_named_model_by_id,
    get_named_model_by_name,
    get_favorite_movies_page,
)
