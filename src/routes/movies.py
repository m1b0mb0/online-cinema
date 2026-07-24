import math

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import (
    MovieModel,
)
from src.schemas.movies import (
    MovieListItemSchema,
    MovieListResponseSchema,
)
from src.database import get_db

router = APIRouter()


@router.get("/movies/", response_model=MovieListResponseSchema)
async def get_movie_list(
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(
        default=10, ge=1, le=20, description="Number of items per page"
    ),
    db: AsyncSession = Depends(get_db),
) -> MovieListResponseSchema:
    offset = (page - 1) * per_page

    count_stmt = select(func.count(MovieModel.id))
    total_items = await db.scalar(count_stmt) or 0

    movies_stmt = (
        select(MovieModel).order_by(desc(MovieModel.id)).offset(offset).limit(per_page)
    )
    movies = (await db.scalars(movies_stmt)).all()

    movie_list = [MovieListItemSchema.model_validate(movie) for movie in movies]

    total_pages = math.ceil(total_items / per_page)

    return MovieListResponseSchema(
        movies=movie_list,
        prev_page=(
            f"/theater/movies/?page={page - 1}&per_page={per_page}"
            if page > 1
            else None
        ),
        next_page=(
            f"/theater/movies/?page={page + 1}&per_page={per_page}"
            if page < total_pages
            else None
        ),
        total_pages=total_pages,
        total_items=total_items,
    )
