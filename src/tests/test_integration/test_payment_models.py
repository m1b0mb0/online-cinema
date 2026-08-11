from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from src.database import (
    CertificationModel,
    MovieModel,
    OrderItemModel,
    OrderModel,
    PaymentItemModel,
    PaymentModel,
    PaymentStatusEnum,
    UserGroupEnum,
    UserGroupModel,
    UserModel,
)

pytestmark = pytest.mark.integration


async def build_order_data(
    db_session,
    email: str,
    suffix: str,
) -> tuple[UserModel, OrderModel, OrderItemModel]:
    group = await db_session.scalar(
        select(UserGroupModel).where(UserGroupModel.name == UserGroupEnum.USER)
    )
    assert group is not None

    user = UserModel(
        email=email,
        _hashed_password="not-used-in-payment-model-tests",
        is_active=True,
        group_id=group.id,
    )
    movie = MovieModel(
        name=f"Payment Movie {suffix}",
        year=2024,
        time=120,
        imdb=8.0,
        votes=1000,
        description="Payment model test movie.",
        price=Decimal("20.00"),
        certification=CertificationModel(name=f"Payment Certification {suffix}"),
    )
    order_item = OrderItemModel(
        movie=movie,
        price_at_order=Decimal("14.50"),
    )
    order = OrderModel(
        user=user,
        total_amount=Decimal("14.50"),
        items=[order_item],
    )
    db_session.add(order)
    await db_session.flush()
    return user, order, order_item


@pytest.mark.asyncio
async def test_payment_preserves_price_snapshot_and_relationships(
    db_session,
    seed_user_groups,
):
    user, order, order_item = await build_order_data(
        db_session,
        "payment-owner@example.com",
        "Snapshot",
    )
    payment = PaymentModel(
        user=user,
        order=order,
        amount=Decimal("14.50"),
        external_payment_id="pi_snapshot_test",
        items=[
            PaymentItemModel(
                order_item=order_item,
                price_at_payment=Decimal("14.50"),
            )
        ],
    )
    db_session.add(payment)
    await db_session.commit()

    payment_id = payment.id
    order_item.movie.price = Decimal("25.00")
    await db_session.commit()
    db_session.expire_all()

    stored_payment = await db_session.scalar(
        select(PaymentModel)
        .where(PaymentModel.id == payment_id)
        .options(
            selectinload(PaymentModel.user),
            selectinload(PaymentModel.order),
            selectinload(PaymentModel.items)
            .selectinload(PaymentItemModel.order_item)
            .selectinload(OrderItemModel.movie),
        )
    )

    assert stored_payment is not None
    assert stored_payment.status == PaymentStatusEnum.PENDING
    assert stored_payment.created_at is not None
    assert stored_payment.user.id == user.id
    assert stored_payment.order.id == order.id
    assert stored_payment.amount == Decimal("14.50")
    assert stored_payment.items[0].price_at_payment == Decimal("14.50")
    assert stored_payment.items[0].order_item.movie.price == Decimal("25.00")


@pytest.mark.asyncio
async def test_external_payment_id_must_be_unique(
    db_session,
    seed_user_groups,
):
    user, order, _ = await build_order_data(
        db_session,
        "unique-payment-owner@example.com",
        "Unique External Id",
    )
    db_session.add_all(
        [
            PaymentModel(
                user=user,
                order=order,
                amount=Decimal("14.50"),
                external_payment_id="pi_duplicate_test",
            ),
            PaymentModel(
                user=user,
                order=order,
                amount=Decimal("14.50"),
                external_payment_id="pi_duplicate_test",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_order_item_cannot_appear_twice_in_one_payment(
    db_session,
    seed_user_groups,
):
    user, order, order_item = await build_order_data(
        db_session,
        "unique-payment-item-owner@example.com",
        "Unique Item",
    )
    payment = PaymentModel(
        user=user,
        order=order,
        amount=Decimal("29.00"),
        items=[
            PaymentItemModel(
                order_item=order_item,
                price_at_payment=Decimal("14.50"),
            ),
            PaymentItemModel(
                order_item=order_item,
                price_at_payment=Decimal("14.50"),
            ),
        ],
    )
    db_session.add(payment)

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.parametrize("negative_field", ["amount", "price_at_payment"])
@pytest.mark.asyncio
async def test_payment_amounts_cannot_be_negative(
    negative_field,
    db_session,
    seed_user_groups,
):
    user, order, order_item = await build_order_data(
        db_session,
        f"negative-payment-{negative_field}@example.com",
        f"Negative {negative_field}",
    )
    amount = Decimal("14.50")
    price_at_payment = Decimal("14.50")
    if negative_field == "amount":
        amount = Decimal("-1.00")
    else:
        price_at_payment = Decimal("-1.00")

    payment = PaymentModel(
        user=user,
        order=order,
        amount=amount,
        items=[
            PaymentItemModel(
                order_item=order_item,
                price_at_payment=price_at_payment,
            )
        ],
    )
    db_session.add(payment)

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()
