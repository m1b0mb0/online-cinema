from pydantic import BaseModel, EmailStr, field_validator

from src.database import UserGroupEnum, accounts_validators


class BaseEmailPasswordSchema(BaseModel):
    email: EmailStr
    password: str

    model_config = {"from_attributes": True}

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        return value.lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, value):
        return accounts_validators.validate_password_strength(value)


class UserRegistrationRequestSchema(BaseEmailPasswordSchema):
    pass


class PasswordResetRequestSchema(BaseModel):
    email: EmailStr


class PasswordResetCompleteRequestSchema(BaseEmailPasswordSchema):
    token: str


class UserLoginRequestSchema(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        return value.lower()


class UserLoginResponseSchema(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserLogoutRequestSchema(BaseModel):
    refresh_token: str


class UserRegistrationResponseSchema(BaseModel):
    id: int
    email: EmailStr

    model_config = {"from_attributes": True}


class UserActivationRequestSchema(BaseModel):
    email: EmailStr
    token: str


class MessageResponseSchema(BaseModel):
    message: str


class TokenRefreshRequestSchema(BaseModel):
    refresh_token: str


class TokenRefreshResponseSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ChangePasswordRequestSchema(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value):
        return accounts_validators.validate_password_strength(value)


class ChangeUserGroupRequestSchema(BaseModel):
    group_name: UserGroupEnum

    @field_validator("group_name", mode="before")
    @classmethod
    def normalize_group_name(cls, value):
        if isinstance(value, str):
            return value.lower()
        return value
