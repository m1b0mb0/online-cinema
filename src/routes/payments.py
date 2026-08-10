from decimal import Decimal
from typing import Annotated

from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    status,
)
from sqlalchemy import func, select
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
    PaymentListParams,
    PaymentListResponseSchema,
    PaymentRefundRequestSchema,
    PaymentRefundResponseSchema,
    PaymentResponseSchema,
    PaymentWebhookResponseSchema,
)
from src.security.dependencies import get_current_active_user
from src.utils import build_pagination

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
        409: {"description": "Order cannot be paid or has an active payment."},
        502: {"description": "Stripe Checkout session could not be created."},
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


@router.get(
    "/payments/",
    response_model=PaymentListResponseSchema,
    summary="List Current User Payments",
    description="Return the current user's paginated payment history.",
    response_description="Paginated payment history.",
    responses={**AUTH_RESPONSES},
)
async def get_current_user_payments(
    request: Request,
    params: Annotated[PaymentListParams, Query()],
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_active_user),
) -> PaymentListResponseSchema:
    total_items = await db.scalar(
        select(func.count(PaymentModel.id)).where(
            PaymentModel.user_id == current_user.id
        )
    )
    offset = (params.page - 1) * params.per_page

    statement = (
        select(PaymentModel)
        .where(PaymentModel.user_id == current_user.id)
        .options(
            selectinload(PaymentModel.items)
            .selectinload(PaymentItemModel.order_item)
            .selectinload(OrderItemModel.movie)
        )
        .order_by(PaymentModel.created_at.desc(), PaymentModel.id.desc())
        .offset(offset)
        .limit(params.per_page)
    )

    payments = (await db.scalars(statement)).all()

    payment_responses = [
        PaymentResponseSchema(
            id=payment.id,
            order_id=payment.order_id,
            created_at=payment.created_at,
            status=payment.status,
            amount=payment.amount,
            external_payment_id=payment.external_payment_id,
            items_count=len(payment.items),
            items=payment.items,
        )
        for payment in payments
    ]

    pagination = build_pagination(
        request=request,
        page=params.page,
        per_page=params.per_page,
        total_items=total_items,
    )

    return PaymentListResponseSchema(
        payments=payment_responses,
        **pagination,
    )


@router.post(
    "/payments/webhook/",
    response_model=PaymentWebhookResponseSchema,
    summary="Handle Stripe Webhook",
    description=(
        "Verify and process a Stripe webhook using the unmodified request body "
        "and `Stripe-Signature` header."
    ),
    response_description="Webhook acknowledgement.",
    responses={
        400: {"description": "Webhook payload or signature is invalid."},
    },
)
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: Annotated[
        str,
        Header(
            alias="Stripe-Signature",
            description="Stripe webhook signature.",
        ),
    ],
    db: AsyncSession = Depends(get_db),
    settings: BaseAppSettings = Depends(get_settings),
) -> PaymentWebhookResponseSchema:
    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.SignatureVerificationError) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload or signature is invalid.",
        ) from error

    checkout_events = {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
        "checkout.session.async_payment_failed",
        "checkout.session.expired",
    }
    refund_events = {
        "refund.created",
        "refund.updated",
        "refund.failed",
    }

    if event.type not in checkout_events | refund_events:
        return PaymentWebhookResponseSchema(received=True)

    stripe_object = event.data.object
    metadata = stripe_object.metadata or {}
    if isinstance(metadata, stripe.StripeObject):
        metadata = metadata.to_dict()

    try:
        payment_id = int(metadata.get("payment_id"))
    except (TypeError, ValueError):
        return PaymentWebhookResponseSchema(received=True)

    row = (
        await db.execute(
            select(PaymentModel, OrderModel)
            .join(OrderModel, PaymentModel.order_id == OrderModel.id)
            .where(PaymentModel.id == payment_id)
            .with_for_update()
        )
    ).one_or_none()
    if row is None:
        return PaymentWebhookResponseSchema(received=True)

    payment, order = row

    if metadata.get("order_id") != str(order.id) or metadata.get("user_id") != str(
        payment.user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook metadata does not match the payment.",
        )

    if event.type in checkout_events:
        if stripe_object.id != payment.external_payment_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Webhook Checkout Session does not match the payment.",
            )

        successful_event = event.type == "checkout.session.async_payment_succeeded" or (
            event.type == "checkout.session.completed"
            and stripe_object.payment_status in {"paid", "no_payment_required"}
        )

        if successful_event:
            expected_amount = int(payment.amount * Decimal("100"))
            if (
                stripe_object.amount_total != expected_amount
                or stripe_object.currency.lower() != settings.STRIPE_CURRENCY.lower()
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Webhook payment amount or currency does not match.",
                )

            if payment.status != PaymentStatusEnum.REFUNDED:
                payment.status = PaymentStatusEnum.SUCCESSFUL
                order.status = OrderStatusEnum.PAID
        elif (
            event.type
            in {
                "checkout.session.async_payment_failed",
                "checkout.session.expired",
            }
            and payment.status == PaymentStatusEnum.PENDING
        ):
            payment.status = PaymentStatusEnum.CANCELED

    elif stripe_object.status == "succeeded":
        payment.status = PaymentStatusEnum.REFUNDED
        order.status = OrderStatusEnum.CANCELED

    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise

    return PaymentWebhookResponseSchema(received=True)


@router.get(
    "/payments/{payment_id}/",
    response_model=PaymentResponseSchema,
    summary="Get Current User Payment",
    description="Return one payment owned by the current user.",
    response_description="Detailed payment with price snapshots.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Payment was not found."},
    },
)
async def get_current_user_payment(
    payment_id: int = Path(gt=0, description="Payment identifier."),
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_active_user),
) -> PaymentResponseSchema:
    payment = await db.scalar(
        select(PaymentModel)
        .where(
            PaymentModel.id == payment_id,
            PaymentModel.user_id == current_user.id,
        )
        .options(
            selectinload(PaymentModel.items)
            .selectinload(PaymentItemModel.order_item)
            .selectinload(OrderItemModel.movie)
        )
    )

    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Payment was not found."
        )

    return PaymentResponseSchema(
        id=payment.id,
        order_id=payment.order_id,
        created_at=payment.created_at,
        status=payment.status,
        amount=payment.amount,
        external_payment_id=payment.external_payment_id,
        items_count=len(payment.items),
        items=payment.items,
    )


@router.post(
    "/payments/{payment_id}/refund/",
    response_model=PaymentRefundResponseSchema,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request Payment Refund",
    description="Request a Stripe refund for a successful owned payment.",
    response_description="Payment accepted for refund processing.",
    responses={
        **AUTH_RESPONSES,
        404: {"description": "Payment was not found."},
        409: {"description": "Payment cannot be refunded in its current state."},
        502: {"description": "Stripe refund could not be created."},
    },
)
async def request_payment_refund(
    refund_data: PaymentRefundRequestSchema | None = Body(
        default=None,
        description="Optional refund request details.",
    ),
    payment_id: int = Path(gt=0, description="Payment identifier."),
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_active_user),
    stripe_client: stripe.StripeClient = Depends(get_stripe_client),
) -> PaymentRefundResponseSchema:
    payment = await db.scalar(
        select(PaymentModel)
        .where(
            PaymentModel.id == payment_id,
            PaymentModel.user_id == current_user.id,
        )
        .options(
            selectinload(PaymentModel.items)
            .selectinload(PaymentItemModel.order_item)
            .selectinload(OrderItemModel.movie),
            selectinload(PaymentModel.order),
        )
        .with_for_update()
    )

    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Payment was not found."
        )

    if payment.status != PaymentStatusEnum.SUCCESSFUL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a successful payment can be refunded.",
        )

    if payment.external_payment_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stripe Checkout Session is missing.",
        )

    try:
        checkout_session = await stripe_client.v1.checkout.sessions.retrieve_async(
            payment.external_payment_id
        )

        session_metadata = checkout_session.metadata or {}
        if isinstance(session_metadata, stripe.StripeObject):
            session_metadata = session_metadata.to_dict()

        if (
            checkout_session.id != payment.external_payment_id
            or session_metadata.get("payment_id") != str(payment.id)
            or session_metadata.get("order_id") != str(payment.order_id)
            or session_metadata.get("user_id") != str(current_user.id)
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Stripe Checkout Session does not match the payment.",
            )

        payment_intent = checkout_session.payment_intent
        payment_intent_id = (
            payment_intent.id if hasattr(payment_intent, "id") else payment_intent
        )

        if not payment_intent_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Stripe PaymentIntent is missing.",
            )

        refund = await stripe_client.v1.refunds.create_async(
            {
                "payment_intent": payment_intent_id,
                "reason": "requested_by_customer",
                "metadata": {
                    "payment_id": str(payment.id),
                    "order_id": str(payment.order_id),
                    "user_id": str(current_user.id),
                    "user_reason": refund_data.reason if refund_data else "",
                },
            },
            {
                "idempotency_key": f"payment-refund-{payment.id}",
            },
        )

        if not refund.id or not refund.status or refund.status == "failed":
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Stripe refund could not be created.",
            )

        await db.commit()
    except stripe.StripeError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to create Stripe refund.",
        ) from error
    except HTTPException:
        await db.rollback()
        raise
    except SQLAlchemyError:
        await db.rollback()
        raise

    return PaymentRefundResponseSchema(
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
        refund_id=refund.id,
        refund_status=refund.status,
    )
