from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, status, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.security.dependencies import get_admin_user
from src.schemas import (
    AdminCartDetailResponseSchema,
    AdminCartListResponseSchema,
    AdminCartSummarySchema,
    AdminOrderFilterParams,
    AdminOrderResponseSchema,
    AdminOrderListResponseSchema,
)
from src.schemas.accounts import ChangeUserGroupRequestSchema, MessageResponseSchema
from src.database import (
    get_db,
    UserModel,
    UserGroupModel,
    CartModel,
    CartItemModel,
    MovieModel,
    OrderModel,
    OrderItemModel,
)
from src.utils import build_pagination

router = APIRouter()

ADMIN_RESPONSES = {
    401: {"description": "Access token is missing or invalid."},
    403: {"description": "Administrator privileges are required."},
}


@router.get(
    "/orders/",
    response_model=AdminOrderListResponseSchema,
    summary="List User Orders",
    description=(
        "Return a paginated list of user orders filtered by user, creation "
        "date, and status. Administrator access is required."
    ),
    response_description="Paginated user order summaries.",
    responses=ADMIN_RESPONSES,
)
async def get_admin_orders(
    request: Request,
    filters: Annotated[AdminOrderFilterParams, Query()],
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_admin_user),
) -> AdminOrderListResponseSchema:
    conditions = []

    if filters.user_id is not None:
        conditions.append(OrderModel.user_id == filters.user_id)

    if filters.status is not None:
        conditions.append(OrderModel.status == filters.status)

    if filters.date_from is not None:
        date_from = datetime.combine(filters.date_from, time.min, tzinfo=timezone.utc)
        conditions.append(OrderModel.created_at >= date_from)

    if filters.date_to is not None:
        if filters.date_to < date.max:
            date_to = datetime.combine(
                filters.date_to + timedelta(days=1),
                time.min,
                tzinfo=timezone.utc,
            )
            conditions.append(OrderModel.created_at < date_to)

    total_items = await db.scalar(select(func.count(OrderModel.id)).where(*conditions))

    statement = (
        select(OrderModel)
        .where(*conditions)
        .options(
            selectinload(OrderModel.user),
            selectinload(OrderModel.items).selectinload(OrderItemModel.movie),
        )
        .order_by(OrderModel.created_at.desc(), OrderModel.id.desc())
        .offset((filters.page - 1) * filters.per_page)
        .limit(filters.per_page)
    )

    orders = (await db.scalars(statement)).all()

    order_responses = []
    for order in orders:
        order_responses.append(
            AdminOrderResponseSchema(
                id=order.id,
                created_at=order.created_at,
                status=order.status,
                total_amount=order.total_amount,
                items_count=len(order.items),
                items=order.items,
                user=order.user,
            )
        )

    pagination = build_pagination(
        request=request,
        page=filters.page,
        per_page=filters.per_page,
        total_items=total_items,
    )

    return AdminOrderListResponseSchema(orders=order_responses, **pagination)


@router.get(
    "/carts/",
    response_model=AdminCartListResponseSchema,
    summary="List User Carts",
    description=(
        "Return a paginated overview of user carts for administration and "
        "troubleshooting. Administrator access is required."
    ),
    response_description="Paginated user cart summaries.",
    responses=ADMIN_RESPONSES,
)
async def get_user_carts(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number."),
    per_page: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Number of carts per page.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_admin_user),
) -> AdminCartListResponseSchema:
    total_items = await db.scalar(select(func.count(CartModel.id)))
    offset = (page - 1) * per_page

    statement = (
        select(CartModel)
        .options(
            selectinload(CartModel.user),
            selectinload(CartModel.items).selectinload(CartItemModel.movie),
        )
        .order_by(CartModel.id)
        .offset(offset)
        .limit(per_page)
    )

    carts = (await db.scalars(statement)).all()

    cart_summaries = []
    for cart in carts:
        total_amount = sum(
            (item.movie.price for item in cart.items), start=Decimal("0.00")
        )

        cart_summaries.append(
            AdminCartSummarySchema(
                id=cart.id,
                user=cart.user,
                items_count=len(cart.items),
                total_amount=total_amount,
            )
        )

    pagination = build_pagination(
        request=request,
        page=page,
        per_page=per_page,
        total_items=total_items,
    )

    return AdminCartListResponseSchema(
        carts=cart_summaries,
        **pagination,
    )


@router.get(
    "/users/{user_id}/cart/",
    response_model=AdminCartDetailResponseSchema,
    summary="Get User Cart",
    description=(
        "Return the movies and total amount in a specific user's cart. "
        "Administrator access is required."
    ),
    response_description="Detailed user shopping cart.",
    responses={
        **ADMIN_RESPONSES,
        404: {"description": "User or shopping cart was not found."},
    },
)
async def get_user_cart(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_admin_user),
) -> AdminCartDetailResponseSchema:
    statement = (
        select(CartModel)
        .where(CartModel.user_id == user_id)
        .options(
            selectinload(CartModel.user),
            selectinload(CartModel.items)
            .selectinload(CartItemModel.movie)
            .selectinload(MovieModel.genres),
        )
    )
    cart = await db.scalar(statement)

    if cart is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shopping cart was not found for the requested user.",
        )

    total_amount = sum(
        (item.movie.price for item in cart.items),
        start=Decimal("0.00"),
    )

    return AdminCartDetailResponseSchema(
        id=cart.id,
        user=cart.user,
        items_count=len(cart.items),
        total_amount=total_amount,
        items=cart.items,
    )


@router.post(
    "/users/{user_id}/group/",
    response_model=MessageResponseSchema,
    summary="Change User Group",
    description=(
        "Allow an administrator to change a user's group. Accepted groups are "
        "`user`, `moderator`, and `admin`."
    ),
    status_code=status.HTTP_200_OK,
    responses={
        400: {
            "description": "Bad Request - The requested group does not exist.",
            "content": {
                "application/json": {"example": {"detail": "Invalid group name."}}
            },
        },
        401: {
            "description": "Unauthorized - Access token is missing or invalid.",
            "content": {
                "application/json": {"example": {"detail": "Not authenticated"}}
            },
        },
        403: {
            "description": "Forbidden - Administrator privileges are required.",
            "content": {
                "application/json": {
                    "example": {"detail": "Administrator privileges are required."}
                }
            },
        },
        404: {
            "description": "Not Found - Target user does not exist.",
            "content": {"application/json": {"example": {"detail": "User not found."}}},
        },
    },
)
async def change_user_group(
    user_id: int,
    group_data: ChangeUserGroupRequestSchema,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_admin_user),
) -> MessageResponseSchema:
    user = await db.scalar(
        select(UserModel)
        .where(UserModel.id == user_id)
        .options(selectinload(UserModel.group))
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )

    new_group = await db.scalar(
        select(UserGroupModel).where(UserGroupModel.name == group_data.group_name)
    )
    if not new_group:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid group name."
        )

    user.group_id = new_group.id
    await db.commit()

    return MessageResponseSchema(message="User group has been updated successfully.")


@router.post(
    "/users/{user_id}/activate/",
    response_model=MessageResponseSchema,
    summary="Manually Activate User Account",
    description=(
        "Allow an administrator to manually activate a user account without an "
        "activation token."
    ),
    status_code=status.HTTP_200_OK,
    responses={
        400: {
            "description": "Bad Request - User account is already active.",
            "content": {
                "application/json": {"example": {"detail": "User is already active."}}
            },
        },
        401: {
            "description": "Unauthorized - Access token is missing or invalid.",
            "content": {
                "application/json": {"example": {"detail": "Not authenticated"}}
            },
        },
        403: {
            "description": "Forbidden - Administrator privileges are required.",
            "content": {
                "application/json": {
                    "example": {"detail": "Administrator privileges are required."}
                }
            },
        },
        404: {
            "description": "Not Found - Target user does not exist.",
            "content": {"application/json": {"example": {"detail": "User not found."}}},
        },
    },
)
async def activate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_admin_user),
) -> MessageResponseSchema:
    user = await db.get(UserModel, user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )

    if user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already active.",
        )

    user.is_active = True
    await db.commit()

    return MessageResponseSchema(message="User activated successfully.")
