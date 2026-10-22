from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.questions import QuestionRead


class SurveyCreate(BaseModel):
    title: str = Field(min_length=1, description="问卷标题，不能全是空格")
    description: str = Field(default="", description="问卷说明")
    allowAnonymous: bool = Field(default=False, strict=True)
    allowRepeat: bool = Field(default=False, strict=True)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("问卷标题不能为空或全是空格")
        return value

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "title": "生活习惯调查",
                "description": "第一阶段：创建和查询问卷草稿",
                "allowAnonymous": False,
                "allowRepeat": False,
            }
        },
    )


class SurveyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    allowAnonymous: bool | None = Field(default=None, strict=True)
    allowRepeat: bool | None = Field(default=None, strict=True)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value):
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("问卷标题不能为空或全是空格")
        return value

    @model_validator(mode="after")
    def validate_changes(self):
        if not self.model_fields_set:
            raise ValueError("至少提供一个需要修改的字段")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("修改字段不能为null；清空说明请使用空字符串")
        return self


class SurveyRead(SurveyCreate):
    id: str
    creatorId: str
    createdAt: datetime
    status: Literal["draft", "published", "closed"]
    deadline: datetime | None
    shareToken: str
    questions: list[QuestionRead]


class UserRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("用户名不能为空或全是空格")
        return value


class UserRead(BaseModel):
    id: str
    username: str
    createdAt: datetime


class TokenRead(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
