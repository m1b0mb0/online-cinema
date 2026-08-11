from abc import ABC, abstractmethod


class EmailSenderInterface(ABC):
    @abstractmethod
    async def send_activation_email(self, email: str, activation_link: str) -> None:
        pass

    @abstractmethod
    async def send_activation_complete_email(self, email: str, login_link: str) -> None:
        pass

    @abstractmethod
    async def send_password_reset_email(self, email: str, reset_link: str) -> None:
        pass

    @abstractmethod
    async def send_password_reset_complete_email(
        self, email: str, login_link: str
    ) -> None:
        pass

    @abstractmethod
    async def send_comment_reply_email(self, email: str, comment_link: str) -> None:
        pass

    @abstractmethod
    async def send_comment_like_email(self, email: str, comment_link: str) -> None:
        pass

    @abstractmethod
    async def send_payment_confirmation_email(
        self,
        email: str,
        order_id: int,
        amount: str,
        currency: str,
        payment_link: str,
    ) -> None:
        pass
