from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas import GroupBrief


class PollCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    options: list[str] = Field(min_length=2, max_length=20)
    group_ids: list[int] = Field(min_length=1, max_length=100)

    @field_validator("subject")
    @classmethod
    def clean_subject(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Subject must not be blank")
        return value

    @field_validator("options")
    @classmethod
    def clean_options(cls, values: list[str]) -> list[str]:
        values = [value.strip() for value in values]
        if any(not value or len(value) > 200 for value in values):
            raise ValueError("Each option must contain 1 to 200 characters")
        if len({value.casefold() for value in values}) != len(values):
            raise ValueError("Options must be distinct")
        return values

    @field_validator("group_ids")
    @classmethod
    def unique_groups(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("Group IDs must be positive")
        return list(dict.fromkeys(values))


class VoteCreate(BaseModel):
    option_id: int = Field(gt=0)


class PollOptionOut(BaseModel):
    id: int
    label: str
    vote_count: int


class PollOut(BaseModel):
    id: int
    subject: str
    is_open: bool
    created_at: datetime
    groups: list[GroupBrief]
    options: list[PollOptionOut]
    total_votes: int
    has_voted: bool
