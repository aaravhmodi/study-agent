from pydantic import BaseModel, ConfigDict, Field


class SignInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=200)
