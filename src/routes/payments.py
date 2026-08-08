from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import stripe

from src.config import get_settings, get_stripe_client
from src.config.settings import BaseAppSettings
from src.database import (
    UserModel,
    OrderModel,
    OrderItemModel,
    OrderStatusEnum,
    PaymentModel,
    PaymentStatusEnum,
    PaymentItemModel,
    get_db,
)
from src.schemas import (
    PaymentCheckoutResponseSchema,
    PaymentResponseSchema,
)
from src.security.dependencies import get_current_active_user

router = APIRouter()

AUTH_RESPONSES = {
    401: {"description": "Access token is missing or invalid."},
    403: {"description": "User account is not activated."},
}


@router.post(
    "/payments/orders/{order_id}/checkout/",
    response_model=PaymentCheckoutResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Payment Checkout",
    description=(
        "Create a pending payment for an owned order and return a Stripe "
        "Checkout URL."
    ),
    response_description="Pending payment and Stripe Checkout URL.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Order was not found."},
        409: {"description": "Order cannot be paid in its current state."},
        409: {"description": "An active payment already exists for this order."},
        502: {"description": "Stripe Checkout session could not be created."},
        502: {"description": "Unable to create Stripe Checkout session."},
    },
)
async def create_payment_checkout(
    order_id: int = Path(gt=0, description="Order identifier."),
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_active_user),
    stripe_client: stripe.StripeClient = Depends(get_stripe_client),
    settings: BaseAppSettings = Depends(get_settings),
) -> PaymentCheckoutResponseSchema:
    order = await db.scalar(
        select(OrderModel)
        .where(OrderModel.id == order_id, OrderModel.user_id == current_user.id)
        .options(selectinload(OrderModel.items).selectinload(OrderItemModel.movie))
        .with_for_update()
    )

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order was not found."
        )

    if order.status != OrderStatusEnum.PENDING or not order.items:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order cannot be paid in its current state.",
        )

    active_payment_id = await db.scalar(
        select(PaymentModel.id)
        .where(
            PaymentModel.order_id == order.id,
            PaymentModel.status.in_(
                [PaymentStatusEnum.PENDING, PaymentStatusEnum.SUCCESSFUL]
            ),
        )
        .limit(1)
    )
    if active_payment_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active payment already exists for this order.",
        )

    total_amount = sum(
        (item.movie.price for item in order.items), start=Decimal("0.00")
    )

    payment = PaymentModel(
        user_id=current_user.id,
        order_id=order.id,
        status=PaymentStatusEnum.PENDING,
        amount=total_amount,
        items=[
            PaymentItemModel(order_item=item, price_at_payment=item.movie.price)
            for item in order.items
        ],
    )

    try:
        db.add(payment)
        await db.flush()

        line_items = [
            {
                "price_data": {
                    "currency": settings.STRIPE_CURRENCY.lower(),
                    "unit_amount": int(item.price_at_payment * Decimal("100")),
                    "product_data": {"name": item.order_item.movie.name},
                },
                "quantity": 1,
            }
            for item in payment.items
        ]
        metadata = {
            "payment_id": str(payment.id),
            "order_id": str(order.id),
            "user_id": str(current_user.id),
        }

        session = await stripe_client.v1.checkout.sessions.create_async(
            {
                "mode": "payment",
                "customer_email": current_user.email,
                "client_reference_id": str(payment.id),
                "line_items": line_items,
                "success_url": settings.STRIPE_SUCCESS_URL,
                "cancel_url": settings.STRIPE_CANCEL_URL,
                "metadata": metadata,
                "payment_intent_data": {"metadata": metadata},
            },
            {
                "idempotency_key": f"payment-checkout-{payment.id}",
            },
        )

        if not session.id or not session.url:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Stripe returned an incomplete Checkout session.",
            )

        payment.external_payment_id = session.id
        await db.commit()
    except stripe.StripeError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to create Stripe Checkout session.",
        ) from error
    except HTTPException:
        await db.rollback()
        raise
    except SQLAlchemyError:
        await db.rollback()
        raise

    return PaymentCheckoutResponseSchema(
        payment=PaymentResponseSchema(
            id=payment.id,
            order_id=payment.order_id,
            created_at=payment.created_at,
            status=payment.status,
            amount=payment.amount,
            external_payment_id=payment.external_payment_id,
            items_count=len(payment.items),
            items=payment.items,
        ),
        checkout_url=session.url,
    )
