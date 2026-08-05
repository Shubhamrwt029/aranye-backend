from pydantic import BaseModel, Field, field_validator


class OTPTemplateUpdate(BaseModel):
    template_id: str = Field(min_length=6, max_length=100)
    template: str = Field(min_length=10, max_length=1000)
    dlt_template_id: str = Field(min_length=6, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    sender_id: str = Field(min_length=3, max_length=11, pattern=r"^[A-Za-z0-9]+$")

    @field_validator("template")
    @classmethod
    def otp_variable_required(cls, value: str) -> str:
        if "##OTP##" not in value:
            raise ValueError("Template must contain the ##OTP## variable")
        return value.strip()


class OTPProviderStatus(BaseModel):
    provider: str
    configured: bool
    service_configured: bool
    environment: str
