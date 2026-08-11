from types import SimpleNamespace


class StubCheckoutSessions:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, dict]] = []
        self.session = SimpleNamespace(
            id="cs_test_checkout_session",
            url="https://checkout.stripe.test/session",
            payment_intent="pi_test_payment_intent",
            metadata={},
            payment_status="unpaid",
            amount_total=1000,
            currency="usd",
        )
        self.error: Exception | None = None
        self.retrieve_calls: list[str] = []

    async def create_async(self, params: dict, options: dict):
        self.calls.append((params, options))
        if self.error is not None:
            raise self.error
        return self.session

    async def retrieve_async(self, session_id: str):
        self.retrieve_calls.append(session_id)
        if self.error is not None:
            raise self.error
        return self.session


class StubRefunds:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, dict]] = []
        self.refund = SimpleNamespace(
            id="re_test_refund",
            status="pending",
        )
        self.error: Exception | None = None

    async def create_async(self, params: dict, options: dict):
        self.calls.append((params, options))
        if self.error is not None:
            raise self.error
        return self.refund


class StubStripeClient:
    def __init__(self) -> None:
        self.checkout_sessions = StubCheckoutSessions()
        self.refunds = StubRefunds()
        self.v1 = SimpleNamespace(
            checkout=SimpleNamespace(sessions=self.checkout_sessions),
            refunds=self.refunds,
        )
