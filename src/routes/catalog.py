import math
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import GenreModel, StarModel, get_db
from src.schemas import (
    ActorRequestSchema,
    ActorListResponseSchema,
    CatalogEntityListParams,
    GenreListResponseSchema,
    GenreRequestSchema,
    GenreSchema,
    NamedCatalogEntityRequestSchema,
    StarSchema,
)
from src.security.dependencies import get_moderator_or_admin_user
from src.services import (
    get_named_model_by_id,
    get_named_model_by_name,
    get_genres_with_movie_counts,
    get_named_models_page,
)

router = APIRouter()

ModelType = TypeVar("ModelType")

AUTH_RESPONSES = {
    401: {"description": "A valid access token is required."},
    403: {"description": "Moderator or administrator privileges are required."},
}


def _build_pagination_links(
    request: Request,
    page: int,
    per_page: int,
    total_pages: int,
) -> tuple[str | None, str | None]:
    prev_page = (
        str(request.url.include_query_params(page=page - 1, per_page=per_page))
        if page > 1
        else None
    )
    next_page = (
        str(request.url.include_query_params(page=page + 1, per_page=per_page))
        if page < total_pages
        else None
    )
    return prev_page, next_page


async def _get_entity_or_404(
    db: AsyncSession,
    model: type[ModelType],
    item_id: int,
    entity_name: str,
) -> ModelType:
    item = await get_named_model_by_id(db, model, item_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{entity_name} was not found.",
        )
    return item


async def _create_entity(
    db: AsyncSession,
    model: type[ModelType],
    data: NamedCatalogEntityRequestSchema,
    entity_name: str,
) -> ModelType:
    existing_item = await get_named_model_by_name(db, model, data.name)
    if existing_item:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{entity_name} with this name already exists.",
        )

    item = model(name=data.name)
    db.add(item)

    try:
        await db.commit()
        await db.refresh(item)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{entity_name} with this name already exists.",
        )

    return item


async def _update_entity(
    db: AsyncSession,
    model: type[ModelType],
    item_id: int,
    data: NamedCatalogEntityRequestSchema,
    entity_name: str,
) -> ModelType:
    item = await _get_entity_or_404(db, model, item_id, entity_name)
    existing_item = await get_named_model_by_name(db, model, data.name)

    if existing_item and existing_item.id != item_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{entity_name} with this name already exists.",
        )

    item.name = data.name

    try:
        await db.commit()
        await db.refresh(item)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{entity_name} with this name already exists.",
        )

    return item


async def _delete_entity(
    db: AsyncSession,
    model: type[ModelType],
    item_id: int,
    entity_name: str,
) -> None:
    item = await _get_entity_or_404(db, model, item_id, entity_name)
    await db.delete(item)
    await db.commit()


@router.get(
    "/genres/",
    response_model=GenreListResponseSchema,
    summary="List Genres",
    description=(
        "Return a paginated, optionally searchable list of movie genres. "
        "Each genre includes the number of associated movies."
    ),
    response_description="Paginated genre list with movie counts.",
)
async def get_genre_list(
    request: Request,
    params: Annotated[CatalogEntityListParams, Query()],
    db: AsyncSession = Depends(get_db),
) -> GenreListResponseSchema:
    genres, total_items = await get_genres_with_movie_counts(
        db,
        params.page,
        params.per_page,
        params.search,
    )
    total_pages = math.ceil(total_items / params.per_page)
    prev_page, next_page = _build_pagination_links(
        request,
        params.page,
        params.per_page,
        total_pages,
    )
    return GenreListResponseSchema(
        genres=genres,
        prev_page=prev_page,
        next_page=next_page,
        page=params.page,
        per_page=params.per_page,
        total_pages=total_pages,
        total_items=total_items,
    )


@router.post(
    "/genres/",
    response_model=GenreSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Genre",
    description="Create a genre. Moderator or administrator access is required.",
    response_description="Created genre.",
    dependencies=[Depends(get_moderator_or_admin_user)],
    responses={
        **AUTH_RESPONSES,
        409: {"description": "A genre with this name already exists."},
    },
)
async def create_genre(
    data: GenreRequestSchema,
    db: AsyncSession = Depends(get_db),
) -> GenreSchema:
    return await _create_entity(db, GenreModel, data, "Genre")


@router.get(
    "/genres/{genre_id}/",
    response_model=GenreSchema,
    summary="Get Genre",
    description="Return a genre by its identifier.",
    response_description="Genre details.",
    responses={404: {"description": "Genre was not found."}},
)
async def get_genre(
    genre_id: int,
    db: AsyncSession = Depends(get_db),
) -> GenreSchema:
    return await _get_entity_or_404(db, GenreModel, genre_id, "Genre")


@router.patch(
    "/genres/{genre_id}/",
    response_model=GenreSchema,
    summary="Update Genre",
    description="Rename a genre. Moderator or administrator access is required.",
    response_description="Updated genre.",
    dependencies=[Depends(get_moderator_or_admin_user)],
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Genre was not found."},
        409: {"description": "A genre with this name already exists."},
    },
)
async def update_genre(
    genre_id: int,
    data: GenreRequestSchema,
    db: AsyncSession = Depends(get_db),
) -> GenreSchema:
    return await _update_entity(db, GenreModel, genre_id, data, "Genre")


@router.delete(
    "/genres/{genre_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Genre",
    description="Delete a genre. Moderator or administrator access is required.",
    dependencies=[Depends(get_moderator_or_admin_user)],
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Genre was not found."},
    },
)
async def delete_genre(
    genre_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _delete_entity(db, GenreModel, genre_id, "Genre")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/actors/",
    response_model=ActorListResponseSchema,
    summary="List Actors",
    description="Return a paginated, optionally searchable list of actors.",
    response_description="Paginated actor list.",
)
async def get_actor_list(
    request: Request,
    params: Annotated[CatalogEntityListParams, Query()],
    db: AsyncSession = Depends(get_db),
) -> ActorListResponseSchema:
    actors, total_items = await get_named_models_page(
        db,
        StarModel,
        params.page,
        params.per_page,
        params.search,
    )
    total_pages = math.ceil(total_items / params.per_page)
    prev_page, next_page = _build_pagination_links(
        request,
        params.page,
        params.per_page,
        total_pages,
    )
    return ActorListResponseSchema(
        actors=actors,
        prev_page=prev_page,
        next_page=next_page,
        page=params.page,
        per_page=params.per_page,
        total_pages=total_pages,
        total_items=total_items,
    )


@router.post(
    "/actors/",
    response_model=StarSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Actor",
    description="Create an actor. Moderator or administrator access is required.",
    response_description="Created actor.",
    dependencies=[Depends(get_moderator_or_admin_user)],
    responses={
        **AUTH_RESPONSES,
        409: {"description": "An actor with this name already exists."},
    },
)
async def create_actor(
    data: ActorRequestSchema,
    db: AsyncSession = Depends(get_db),
) -> StarSchema:
    return await _create_entity(db, StarModel, data, "Actor")


@router.get(
    "/actors/{actor_id}/",
    response_model=StarSchema,
    summary="Get Actor",
    description="Return an actor by their identifier.",
    response_description="Actor details.",
    responses={404: {"description": "Actor was not found."}},
)
async def get_actor(
    actor_id: int,
    db: AsyncSession = Depends(get_db),
) -> StarSchema:
    return await _get_entity_or_404(db, StarModel, actor_id, "Actor")


@router.patch(
    "/actors/{actor_id}/",
    response_model=StarSchema,
    summary="Update Actor",
    description="Rename an actor. Moderator or administrator access is required.",
    response_description="Updated actor.",
    dependencies=[Depends(get_moderator_or_admin_user)],
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Actor was not found."},
        409: {"description": "An actor with this name already exists."},
    },
)
async def update_actor(
    actor_id: int,
    data: ActorRequestSchema,
    db: AsyncSession = Depends(get_db),
) -> StarSchema:
    return await _update_entity(db, StarModel, actor_id, data, "Actor")


@router.delete(
    "/actors/{actor_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Actor",
    description="Delete an actor. Moderator or administrator access is required.",
    dependencies=[Depends(get_moderator_or_admin_user)],
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Actor was not found."},
    },
)
async def delete_actor(
    actor_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _delete_entity(db, StarModel, actor_id, "Actor")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
