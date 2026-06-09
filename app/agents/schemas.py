from pydantic import BaseModel, ConfigDict, Field


class CoderOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Pure code")
    explanation: str = Field(description="Brief explanation")
    language: str = Field(description="Programming language")


class SearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(description="Summary")
    sources: list[str] = Field(description="Source links")
