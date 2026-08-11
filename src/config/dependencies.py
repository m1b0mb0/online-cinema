from functools import lru_cache

from fastapi import Depends
import stripe

from src.config.settings import Settings, BaseAppSettings
from src.security.interfaces import JWTAuthManagerInterface
from src.security.token_manager import JWTAuthManager
from src.notifications.interfaces import EmailSenderInterface
from src.notifications.emails import EmailSender


@lru_cache
def get_settings() -> BaseAppSettings:
    return Settings()


def get_jwt_auth_manager(
    settings: BaseAppSettings = Depends(get_settings),
) -> JWTAuthManagerInterface:
    return JWTAuthManager(
        secret_key_access=settings.SECRET_KEY_ACCESS,
        secret_key_refresh=settings.SECRET_KEY_REFRESH,
        algorithm=settings.JWT_SIGNING_ALGORITHM,
    )


def get_email_notificator(
    settings: BaseAppSettings = Depends(get_settings),
) -> EmailSenderInterface:
    return EmailSender(
        hostname=settings.EMAIL_HOST,
        port=settings.EMAIL_PORT,
        email=settings.EMAIL_HOST_USER,
        password=settings.EMAIL_HOST_PASSWORD,
        use_tls=settings.EMAIL_USE_TLS,
        template_dir=settings.PATH_TO_EMAIL_TEMPLATES_DIR,
        activation_email_template_name=settings.ACTIVATION_EMAIL_TEMPLATE_NAME,
        activation_complete_email_template_name=settings.ACTIVATION_COMPLETE_EMAIL_TEMPLATE_NAME,
        password_email_template_name=settings.PASSWORD_RESET_TEMPLATE_NAME,
        password_complete_email_template_name=settings.PASSWORD_RESET_COMPLETE_TEMPLATE_NAME,
        comment_reply_template_name=settings.COMMENT_REPLY_TEMPLATE_NAME,
        comment_like_template_name=settings.COMMENT_LIKE_TEMPLATE_NAME,
        payment_confirmation_template_name=(
            settings.PAYMENT_CONFIRMATION_TEMPLATE_NAME
        ),
    )


get_accounts_email_notificator = get_email_notificator


def get_stripe_client(
    settings: BaseAppSettings = Depends(get_settings),
) -> stripe.StripeClient:
    return stripe.StripeClient(
        settings.STRIPE_SECRET_KEY,
        max_network_retries=2,
    )
