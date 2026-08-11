from decimal import Decimal
from types import SimpleNamespace

import pytest
import stripe
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from main import app
from src.config import get_settings, get_stripe_client
from src.database import (
    CertificationModel,
    MovieModel,
    OrderItemModel,
    OrderModel,
    OrderStatusEnum,
    PaymentItemModel,
    PaymentModel,
    PaymentStatusEnum,
    UserGroupEnum,
    UserModel,
)
from src.tests.doubles.stubs.stripe import StubStripeClient
from src.tests.helpers import create_auth_headers

pytestmark = pytest.mark.integration


def build_movie(
    name: str,
    certification: CertificationModel,
    price: str,
) -> MovieModel:
    return MovieModel(
        name=name,
        year=2024,
        time=120,
        imdb=8.0,
        votes=1000,
        description=f"{name} description.",
        price=Decimal(price),
        certification=certification,
    )


async def create_user_with_headers(
    db_session,
    jwt_manager,
    email: str,
) -> tuple[UserModel, dict[str, str]]:
    headers = await create_auth_headers(
        db_session,
        jwt_manager,
        UserGroupEnum.USER,
        email,
    )
    user = await db_session.scalar(
        select(UserModel).where(UserModel.email == email)
    )
    assert user is not None
    return user, headers


def override_payment_dependencies(stripe_client: StubStripeClient) -> None:
    settings = get_settings().model_copy(
        update={
            "APP_BASE_URL": "https://cinema.test",
            "STRIPE_CURRENCY": "USD",
            "STRIPE_SUCCESS_URL": "https://cinema.test/payment-success",
            "STRIPE_CANCEL_URL": "https://cinema.test/payment-canceled",
            "STRIPE_WEBHOOK_SECRET": "whsec_test",
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_stripe_client] = lambda: stripe_client


async def create_stored_payment(
    db_session,
    user: UserModel,
    suffix: str,
    *,
    payment_status: PaymentStatusEnum = PaymentStatusEnum.PENDING,
    order_status: OrderStatusEnum = OrderStatusEnum.PENDING,
) -> tuple[PaymentModel, OrderModel]:
    movie = build_movie(
        f"Payment Flow Movie {suffix}",
        CertificationModel(name=f"Payment Flow Certification {suffix}"),
        "10.00",
    )
    order_item = OrderItemModel(movie=movie, price_at_order=movie.price)
    order = OrderModel(
        user_id=user.id,
        status=order_status,
        total_amount=movie.price,
        items=[order_item],
    )
    payment = PaymentModel(
        user_id=user.id,
        order=order,
        status=payment_status,
        amount=movie.price,
        external_payment_id=f"cs_test_{suffix}",
        items=[
            PaymentItemModel(
                order_item=order_item,
                price_at_payment=movie.price,
            )
        ],
    )
    db_session.add(payment)
    await db_session.commit()
    return payment, order


@pytest.mark.asyncio
async def test_create_checkout_persists_payment_and_uses_current_movie_prices(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "checkout-owner@example.com",
    )
    certification = CertificationModel(name="PG-13")
    first_movie = build_movie("First Checkout Movie", certification, "12.50")
    second_movie = build_movie("Second Checkout Movie", certification, "7.25")
    first_item = OrderItemModel(
        movie=first_movie,
        price_at_order=Decimal("10.00"),
    )
    second_item = OrderItemModel(
        movie=second_movie,
        price_at_order=Decimal("6.00"),
    )
    order = OrderModel(
        user_id=user.id,
        status=OrderStatusEnum.PENDING,
        total_amount=Decimal("16.00"),
        items=[first_item, second_item],
    )
    db_session.add(order)
    await db_session.commit()
    order_id = order.id
    user_id = user.id

    stripe_client = StubStripeClient()
    override_payment_dependencies(stripe_client)

    response = await client.post(
        f"/theater/payments/orders/{order_id}/checkout/",
        headers=headers,
    )

    assert response.status_code == 201
    response_data = response.json()
    assert Decimal(response_data["payment"]["amount"]) == Decimal("19.75")
    assert response_data["payment"]["external_payment_id"] == (
        "cs_test_checkout_session"
    )
    assert response_data["checkout_url"] == (
        "https://checkout.stripe.test/session"
    )

    db_session.expire_all()
    stored_payment = await db_session.scalar(
        select(PaymentModel)
        .where(PaymentModel.id == response_data["payment"]["id"])
        .options(
            selectinload(PaymentModel.items).selectinload(
                PaymentItemModel.order_item
            )
        )
    )
    assert stored_payment is not None
    assert stored_payment.status == PaymentStatusEnum.PENDING
    assert stored_payment.amount == Decimal("19.75")
    assert stored_payment.external_payment_id == "cs_test_checkout_session"
    assert [item.price_at_payment for item in stored_payment.items] == [
        Decimal("12.50"),
        Decimal("7.25"),
    ]
    assert [item.order_item.price_at_order for item in stored_payment.items] == [
        Decimal("10.00"),
        Decimal("6.00"),
    ]

    assert len(stripe_client.checkout_sessions.calls) == 1
    stripe_params, stripe_options = stripe_client.checkout_sessions.calls[0]
    assert [
        line_item["price_data"]["unit_amount"]
        for line_item in stripe_params["line_items"]
    ] == [1250, 725]
    assert all(
        isinstance(line_item["price_data"]["unit_amount"], int)
        for line_item in stripe_params["line_items"]
    )
    assert stripe_params["metadata"] == {
        "payment_id": str(stored_payment.id),
        "order_id": str(order_id),
        "user_id": str(user_id),
    }
    assert stripe_params["payment_intent_data"]["metadata"] == (
        stripe_params["metadata"]
    )
    assert stripe_params["success_url"] == (
        "https://cinema.test/payment-success"
        "?session_id={CHECKOUT_SESSION_ID}"
    )
    assert stripe_options["idempotency_key"] == (
        f"payment-checkout-{stored_payment.id}"
    )


@pytest.mark.asyncio
async def test_create_checkout_rejects_an_active_payment(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "duplicate-checkout-owner@example.com",
    )
    movie = build_movie(
        "Duplicate Checkout Movie",
        CertificationModel(name="R"),
        "9.99",
    )
    order_item = OrderItemModel(movie=movie, price_at_order=movie.price)
    order = OrderModel(
        user_id=user.id,
        status=OrderStatusEnum.PENDING,
        total_amount=movie.price,
        items=[order_item],
    )
    payment = PaymentModel(
        user_id=user.id,
        order=order,
        status=PaymentStatusEnum.PENDING,
        amount=movie.price,
        items=[
            PaymentItemModel(
                order_item=order_item,
                price_at_payment=movie.price,
            )
        ],
    )
    db_session.add(payment)
    await db_session.commit()

    stripe_client = StubStripeClient()
    override_payment_dependencies(stripe_client)

    response = await client.post(
        f"/theater/payments/orders/{order.id}/checkout/",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "An active payment already exists for this order."
    )
    assert stripe_client.checkout_sessions.calls == []
    payment_count = await db_session.scalar(
        select(func.count(PaymentModel.id)).where(PaymentModel.order_id == order.id)
    )
    assert payment_count == 1


@pytest.mark.asyncio
async def test_create_checkout_rolls_back_when_stripe_fails(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "failed-checkout-owner@example.com",
    )
    movie = build_movie(
        "Failed Checkout Movie",
        CertificationModel(name="PG"),
        "8.50",
    )
    order_item = OrderItemModel(
        movie=movie,
        price_at_order=Decimal("7.00"),
    )
    order = OrderModel(
        user_id=user.id,
        status=OrderStatusEnum.PENDING,
        total_amount=Decimal("7.00"),
        items=[order_item],
    )
    db_session.add(order)
    await db_session.commit()
    order_id = order.id
    order_item_id = order_item.id

    stripe_client = StubStripeClient()
    stripe_client.checkout_sessions.error = stripe.APIConnectionError(
        "Stripe is unavailable"
    )
    override_payment_dependencies(stripe_client)

    response = await client.post(
        f"/theater/payments/orders/{order_id}/checkout/",
        headers=headers,
    )

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "Unable to create Stripe Checkout session."
    )
    payment_count = await db_session.scalar(
        select(func.count(PaymentModel.id)).where(PaymentModel.order_id == order_id)
    )
    assert payment_count == 0
    db_session.expire_all()
    stored_item = await db_session.get(OrderItemModel, order_item_id)
    assert stored_item is not None
    assert stored_item.price_at_order == Decimal("7.00")


@pytest.mark.asyncio
async def test_create_checkout_hides_other_users_orders(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    owner, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        "private-checkout-owner@example.com",
    )
    _, outsider_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "private-checkout-outsider@example.com",
    )
    movie = build_movie(
        "Private Checkout Movie",
        CertificationModel(name="NC-17"),
        "11.00",
    )
    order = OrderModel(
        user_id=owner.id,
        status=OrderStatusEnum.PENDING,
        total_amount=movie.price,
        items=[OrderItemModel(movie=movie, price_at_order=movie.price)],
    )
    db_session.add(order)
    await db_session.commit()

    stripe_client = StubStripeClient()
    override_payment_dependencies(stripe_client)

    response = await client.post(
        f"/theater/payments/orders/{order.id}/checkout/",
        headers=outsider_headers,
    )

    assert response.status_code == 404
    assert stripe_client.checkout_sessions.calls == []


@pytest.mark.parametrize(
    ("order_status", "has_items"),
    [
        (OrderStatusEnum.PAID, True),
        (OrderStatusEnum.PENDING, False),
    ],
)
@pytest.mark.asyncio
async def test_create_checkout_rejects_orders_that_cannot_be_paid(
    order_status,
    has_items,
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        f"invalid-{order_status}-{has_items}@example.com",
    )
    items = []
    total_amount = Decimal("0.00")
    if has_items:
        movie = build_movie(
            "Invalid State Checkout Movie",
            CertificationModel(name="Invalid State Certification"),
            "10.00",
        )
        items.append(OrderItemModel(movie=movie, price_at_order=movie.price))
        total_amount = movie.price

    order = OrderModel(
        user_id=user.id,
        status=order_status,
        total_amount=total_amount,
        items=items,
    )
    db_session.add(order)
    await db_session.commit()

    stripe_client = StubStripeClient()
    override_payment_dependencies(stripe_client)

    response = await client.post(
        f"/theater/payments/orders/{order.id}/checkout/",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Order cannot be paid in its current state."
    )
    assert stripe_client.checkout_sessions.calls == []


@pytest.mark.asyncio
async def test_payment_history_and_detail_are_private_and_paginated(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    owner, owner_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "payment-history-owner@example.com",
    )
    outsider, outsider_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "payment-history-outsider@example.com",
    )
    first_payment, _ = await create_stored_payment(db_session, owner, "history-1")
    second_payment, _ = await create_stored_payment(db_session, owner, "history-2")
    outsider_payment, _ = await create_stored_payment(
        db_session,
        outsider,
        "history-other",
    )

    list_response = await client.get(
        "/theater/payments/",
        params={"page": 1, "per_page": 1},
        headers=owner_headers,
    )

    assert list_response.status_code == 200
    list_data = list_response.json()
    assert list_data["total_items"] == 2
    assert list_data["total_pages"] == 2
    assert [payment["id"] for payment in list_data["payments"]] == [
        second_payment.id
    ]

    detail_response = await client.get(
        f"/theater/payments/{first_payment.id}/",
        headers=owner_headers,
    )
    private_response = await client.get(
        f"/theater/payments/{outsider_payment.id}/",
        headers=owner_headers,
    )
    outsider_list_response = await client.get(
        "/theater/payments/",
        headers=outsider_headers,
    )

    assert detail_response.status_code == 200
    assert detail_response.json()["items_count"] == 1
    assert private_response.status_code == 404
    assert outsider_list_response.json()["total_items"] == 1


@pytest.mark.asyncio
async def test_payment_confirmation_is_private_and_reflects_webhook_status(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
    email_sender_stub,
):
    owner, owner_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "confirmation-owner@example.com",
    )
    _, outsider_headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "confirmation-outsider@example.com",
    )
    payment, order = await create_stored_payment(
        db_session,
        owner,
        "confirmation",
    )
    payment_id = payment.id
    order_id = order.id
    stripe_client = StubStripeClient()
    stripe_client.checkout_sessions.session.id = payment.external_payment_id
    stripe_client.checkout_sessions.session.metadata = {
        "payment_id": str(payment_id),
        "order_id": str(order_id),
        "user_id": str(owner.id),
    }
    override_payment_dependencies(stripe_client)

    private_response = await client.get(
        "/theater/payments/confirmation/",
        params={"session_id": payment.external_payment_id},
        headers=outsider_headers,
    )
    pending_response = await client.get(
        "/theater/payments/confirmation/",
        params={"session_id": payment.external_payment_id},
        headers=owner_headers,
    )

    assert private_response.status_code == 404
    assert pending_response.status_code == 200
    assert pending_response.json()["confirmed"] is False
    assert pending_response.json()["message"] == (
        "Payment is still being processed."
    )

    stripe_client.checkout_sessions.session.payment_status = "paid"

    confirmed_response = await client.get(
        "/theater/payments/confirmation/",
        params={"session_id": payment.external_payment_id},
        headers=owner_headers,
    )

    assert confirmed_response.status_code == 200
    assert confirmed_response.json()["confirmed"] is True
    assert confirmed_response.json()["message"] == (
        "Payment confirmed successfully."
    )
    assert confirmed_response.json()["payment"]["status"] == "successful"

    duplicate_response = await client.get(
        "/theater/payments/confirmation/",
        params={"session_id": payment.external_payment_id},
        headers=owner_headers,
    )

    assert duplicate_response.status_code == 200
    assert stripe_client.checkout_sessions.retrieve_calls == [
        payment.external_payment_id,
        payment.external_payment_id,
    ]
    db_session.expire_all()
    stored_payment = await db_session.get(PaymentModel, payment_id)
    stored_order = await db_session.get(OrderModel, order_id)
    assert stored_payment.status == PaymentStatusEnum.SUCCESSFUL
    assert stored_order.status == OrderStatusEnum.PAID
    assert email_sender_stub.payment_confirmation_emails == [
        {
            "email": "confirmation-owner@example.com",
            "order_id": order_id,
            "amount": "10.00",
            "currency": "USD",
            "payment_link": (
                f"https://cinema.test/theater/payments/{payment_id}/"
            ),
        }
    ]


@pytest.mark.asyncio
async def test_checkout_webhooks_update_status_without_reversing_success(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
    monkeypatch,
    email_sender_stub,
):
    user, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        "checkout-webhook-owner@example.com",
    )
    payment, order = await create_stored_payment(db_session, user, "webhook")
    payment_id = payment.id
    order_id = order.id
    stripe_client = StubStripeClient()
    override_payment_dependencies(stripe_client)

    metadata = {
        "payment_id": str(payment_id),
        "order_id": str(order_id),
        "user_id": str(user.id),
    }
    metadata = stripe.StripeObject.construct_from(metadata, "sk_test")
    successful_session = SimpleNamespace(
        id=payment.external_payment_id,
        metadata=metadata,
        payment_status="paid",
        amount_total=1000,
        currency="usd",
    )
    expired_session = SimpleNamespace(
        id=payment.external_payment_id,
        metadata=metadata,
        payment_status="unpaid",
        amount_total=1000,
        currency="usd",
    )
    events = [
        SimpleNamespace(
            type="checkout.session.async_payment_succeeded",
            data=SimpleNamespace(object=successful_session),
        ),
        SimpleNamespace(
            type="checkout.session.async_payment_succeeded",
            data=SimpleNamespace(object=successful_session),
        ),
        SimpleNamespace(
            type="checkout.session.expired",
            data=SimpleNamespace(object=expired_session),
        ),
    ]
    monkeypatch.setattr(
        stripe.Webhook,
        "construct_event",
        lambda payload, signature, secret: events.pop(0),
    )

    success_response = await client.post(
        "/theater/payments/webhook/",
        content=b"{}",
        headers={"Stripe-Signature": "test-signature"},
    )
    duplicate_response = await client.post(
        "/theater/payments/webhook/",
        content=b"{}",
        headers={"Stripe-Signature": "test-signature"},
    )
    stale_response = await client.post(
        "/theater/payments/webhook/",
        content=b"{}",
        headers={"Stripe-Signature": "test-signature"},
    )

    assert success_response.status_code == 200
    assert success_response.json() == {"received": True}
    assert duplicate_response.status_code == 200
    assert stale_response.status_code == 200
    db_session.expire_all()
    stored_payment = await db_session.get(PaymentModel, payment_id)
    stored_order = await db_session.get(OrderModel, order_id)
    assert stored_payment.status == PaymentStatusEnum.SUCCESSFUL
    assert stored_order.status == OrderStatusEnum.PAID
    assert email_sender_stub.payment_confirmation_emails == [
        {
            "email": "checkout-webhook-owner@example.com",
            "order_id": order_id,
            "amount": "10.00",
            "currency": "USD",
            "payment_link": (
                f"https://cinema.test/theater/payments/{payment_id}/"
            ),
        }
    ]


@pytest.mark.asyncio
async def test_refund_request_waits_for_webhook_before_changing_status(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "refund-request-owner@example.com",
    )
    payment, order = await create_stored_payment(
        db_session,
        user,
        "refund-request",
        payment_status=PaymentStatusEnum.SUCCESSFUL,
        order_status=OrderStatusEnum.PAID,
    )
    payment_id = payment.id
    order_id = order.id
    stripe_client = StubStripeClient()
    stripe_client.checkout_sessions.session.id = payment.external_payment_id
    stripe_client.checkout_sessions.session.metadata = {
        "payment_id": str(payment_id),
        "order_id": str(order_id),
        "user_id": str(user.id),
    }
    stripe_client.checkout_sessions.session.metadata = (
        stripe.StripeObject.construct_from(
            stripe_client.checkout_sessions.session.metadata,
            "sk_test",
        )
    )
    override_payment_dependencies(stripe_client)

    response = await client.post(
        f"/theater/payments/{payment_id}/refund/",
        json={"reason": "Accidental purchase"},
        headers=headers,
    )

    assert response.status_code == 202
    response_data = response.json()
    assert response_data["refund_id"] == "re_test_refund"
    assert response_data["refund_status"] == "pending"
    assert response_data["payment"]["status"] == "successful"
    assert stripe_client.checkout_sessions.retrieve_calls == [
        payment.external_payment_id
    ]
    refund_params, refund_options = stripe_client.refunds.calls[0]
    assert refund_params["payment_intent"] == "pi_test_payment_intent"
    assert refund_params["metadata"]["user_reason"] == "Accidental purchase"
    assert refund_options["idempotency_key"] == f"payment-refund-{payment_id}"

    db_session.expire_all()
    stored_payment = await db_session.get(PaymentModel, payment_id)
    stored_order = await db_session.get(OrderModel, order_id)
    assert stored_payment.status == PaymentStatusEnum.SUCCESSFUL
    assert stored_order.status == OrderStatusEnum.PAID


@pytest.mark.asyncio
async def test_refund_request_accepts_missing_optional_body(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
):
    user, headers = await create_user_with_headers(
        db_session,
        jwt_manager,
        "refund-without-body-owner@example.com",
    )
    payment, _ = await create_stored_payment(
        db_session,
        user,
        "refund-without-body",
        payment_status=PaymentStatusEnum.SUCCESSFUL,
        order_status=OrderStatusEnum.PAID,
    )
    stripe_client = StubStripeClient()
    stripe_client.checkout_sessions.session.id = payment.external_payment_id
    stripe_client.checkout_sessions.session.metadata = {
        "payment_id": str(payment.id),
        "order_id": str(payment.order_id),
        "user_id": str(user.id),
    }
    override_payment_dependencies(stripe_client)

    response = await client.post(
        f"/theater/payments/{payment.id}/refund/",
        headers=headers,
    )

    assert response.status_code == 202
    refund_params, _ = stripe_client.refunds.calls[0]
    assert refund_params["metadata"]["user_reason"] == ""


@pytest.mark.asyncio
async def test_refund_webhook_finalizes_local_payment_and_order(
    client,
    db_session,
    jwt_manager,
    seed_user_groups,
    monkeypatch,
):
    user, _ = await create_user_with_headers(
        db_session,
        jwt_manager,
        "refund-webhook-owner@example.com",
    )
    payment, order = await create_stored_payment(
        db_session,
        user,
        "refund-webhook",
        payment_status=PaymentStatusEnum.SUCCESSFUL,
        order_status=OrderStatusEnum.PAID,
    )
    payment_id = payment.id
    order_id = order.id
    override_payment_dependencies(StubStripeClient())

    refund = SimpleNamespace(
        id="re_test_refund",
        status="succeeded",
        metadata={
            "payment_id": str(payment_id),
            "order_id": str(order_id),
            "user_id": str(user.id),
        },
    )
    refund.metadata = stripe.StripeObject.construct_from(
        refund.metadata,
        "sk_test",
    )
    event = SimpleNamespace(
        type="refund.updated",
        data=SimpleNamespace(object=refund),
    )
    monkeypatch.setattr(
        stripe.Webhook,
        "construct_event",
        lambda payload, signature, secret: event,
    )

    response = await client.post(
        "/theater/payments/webhook/",
        content=b"{}",
        headers={"Stripe-Signature": "test-signature"},
    )

    assert response.status_code == 200
    db_session.expire_all()
    stored_payment = await db_session.get(PaymentModel, payment_id)
    stored_order = await db_session.get(OrderModel, order_id)
    assert stored_payment.status == PaymentStatusEnum.REFUNDED
    assert stored_order.status == OrderStatusEnum.CANCELED


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_stripe_signature(client):
    override_payment_dependencies(StubStripeClient())

    response = await client.post(
        "/theater/payments/webhook/",
        content=b"{}",
        headers={"Stripe-Signature": "t=1,v1=invalid"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Webhook payload or signature is invalid."
    )
