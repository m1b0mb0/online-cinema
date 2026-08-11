from src.notifications.interfaces import EmailSenderInterface


class StubEmailSender(EmailSenderInterface):
    def __init__(self) -> None:
        self.activation_emails: list[dict[str, str]] = []
        self.activation_complete_emails: list[dict[str, str]] = []
        self.password_reset_emails: list[dict[str, str]] = []
        self.password_reset_complete_emails: list[dict[str, str]] = []
        self.comment_reply_emails: list[dict[str, str]] = []
        self.comment_like_emails: list[dict[str, str]] = []
        self.payment_confirmation_emails: list[dict[str, str | int]] = []

    async def send_activation_email(self, email: str, activation_link: str) -> None:
        self.activation_emails.append(
            {"email": email, "activation_link": activation_link}
        )

    async def send_activation_complete_email(self, email: str, login_link: str) -> None:
        self.activation_complete_emails.append(
            {"email": email, "login_link": login_link}
        )

    async def send_password_reset_email(self, email: str, reset_link: str) -> None:
        self.password_reset_emails.append({"email": email, "reset_link": reset_link})

    async def send_password_reset_complete_email(
        self, email: str, login_link: str
    ) -> None:
        self.password_reset_complete_emails.append(
            {"email": email, "login_link": login_link}
        )

    async def send_comment_reply_email(
        self, email: str, comment_link: str
    ) -> None:
        self.comment_reply_emails.append(
            {"email": email, "comment_link": comment_link}
        )

    async def send_comment_like_email(
        self, email: str, comment_link: str
    ) -> None:
        self.comment_like_emails.append(
            {"email": email, "comment_link": comment_link}
        )

    async def send_payment_confirmation_email(
        self,
        email: str,
        order_id: int,
        amount: str,
        currency: str,
        payment_link: str,
    ) -> None:
        self.payment_confirmation_emails.append(
            {
                "email": email,
                "order_id": order_id,
                "amount": amount,
                "currency": currency,
                "payment_link": payment_link,
            }
        )
