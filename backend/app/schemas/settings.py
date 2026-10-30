from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DefaultsUpdateIn(StrictModel):
    detect_reruns: int = Field(ge=10, le=100)
    verify_reruns: int = Field(ge=50, le=600)
