from src.notifications.interfaces import EmailSenderInterface


class StubEmailSender(EmailSenderInterface):
    def __init__(self) -> None:
        self.activation_emails: list[dict[str, str]] = []
        self.activation_complete_emails: list[dict[str, str]] = []
        self.password_reset_emails: list[dict[str, str]] = []
        self.password_reset_complete_emails: list[dict[str, str]] = []

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
