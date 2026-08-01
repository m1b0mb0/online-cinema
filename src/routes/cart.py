from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import CartItemModel, CartModel, MovieModel, UserModel, get_db
from src.schemas import CartItemResponseSchema, CartMovieSchema, CartResponseSchema
from src.services import get_movie_by_uuid_or_404
from src.security.dependencies import get_current_active_user

router = APIRouter()

AUTH_RESPONSES = {
    401: {"description": "Access token is missing or invalid."},
    403: {"description": "User account is not activated."},
}


@router.get(
    "/cart/",
    response_model=CartResponseSchema,
    summary="Get Current User Cart",
    description="Return the current user's cart, its movies, and total amount.",
    response_description="Current user's shopping cart.",
    responses=AUTH_RESPONSES,
)
async def get_current_user_cart(
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CartResponseSchema:
    statement = (
        select(CartModel)
        .where(CartModel.user_id == current_user.id)
        .options(
            selectinload(CartModel.items)
            .selectinload(CartItemModel.movie)
            .selectinload(MovieModel.genres)
        )
    )
    cart = await db.scalar(statement)

    if cart is None:
        cart = CartModel(user_id=current_user.id, items=[])
        db.add(cart)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            cart = await db.scalar(statement)
            if cart is None:
                raise
        except SQLAlchemyError:
            await db.rollback()
            raise

    total_amount = sum(
        (item.movie.price for item in cart.items),
        start=Decimal("0.00"),
    )

    return CartResponseSchema(
        id=cart.id,
        items=cart.items,
        items_count=len(cart.items),
        total_amount=total_amount,
    )


@router.post(
    "/cart/items/{movie_uuid}/",
    response_model=CartItemResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Add Movie To Cart",
    description="Add a movie to the current user's shopping cart.",
    response_description="Created cart item.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Movie was not found."},
        409: {"description": "Movie is already in the cart."},
    },
)
async def add_movie_to_cart(
    movie_uuid: UUID,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CartItemResponseSchema:
    movie = await get_movie_by_uuid_or_404(
        db, movie_uuid, loader_options=(selectinload(MovieModel.genres),)
    )

    cart = await db.scalar(
        select(CartModel).where(CartModel.user_id == current_user.id)
    )
    if cart is None:
        cart = CartModel(user_id=current_user.id)
        db.add(cart)
        await db.flush()

    existing_item = await db.scalar(
        select(CartItemModel).where(
            CartItemModel.cart_id == cart.id, CartItemModel.movie_id == movie.id
        )
    )

    if existing_item:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Movie is already in the cart.",
        )

    cart_item = CartItemModel(cart_id=cart.id, movie_id=movie.id)
    db.add(cart_item)

    try:
        await db.commit()
        await db.refresh(cart_item)
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Movie is already in the cart.",
        ) from error
    except SQLAlchemyError:
        await db.rollback()
        raise

    return CartItemResponseSchema(
        id=cart_item.id,
        added_at=cart_item.added_at,
        movie=CartMovieSchema.model_validate(movie),
    )


@router.delete(
    "/cart/items/{movie_uuid}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Movie From Cart",
    description="Remove one movie from the current user's shopping cart.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Movie is not in the user's cart."},
    },
)
async def remove_movie_from_cart(
    movie_uuid: UUID,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    cart_item = await db.scalar(
        select(CartItemModel)
        .join(CartModel, CartItemModel.cart_id == CartModel.id)
        .join(MovieModel, CartItemModel.movie_id == MovieModel.id)
        .where(
            CartModel.user_id == current_user.id,
            MovieModel.uuid == movie_uuid,
        )
    )
    if cart_item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie is not in the user's cart.",
        )

    await db.delete(cart_item)
    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/cart/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear Current User Cart",
    description="Remove every movie from the current user's shopping cart.",
    responses=AUTH_RESPONSES,
)
async def clear_current_user_cart(
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    cart = await db.scalar(
        select(CartModel).where(CartModel.user_id == current_user.id)
    )

    if cart is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        await db.execute(
            delete(CartItemModel).where(CartItemModel.cart_id == cart.id)
        )
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise

    return Response(status_code=status.HTTP_204_NO_CONTENT)
