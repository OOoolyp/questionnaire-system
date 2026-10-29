"""常用题版本与题库的数据契约。

API 使用字符串 ID，持久化时由服务层转换为 ObjectId。
跨文档归属、权限和不可变性由服务层验证。
"""
from datetime import datetime
from typing import Literal

from pydantic import Field, TypeAdapter, model_validator

from app.surveys.questions import Identifier, OptionInput, QuestionInput, StrictModel, Text


class LibraryQuestionContent(StrictModel):
    title: Text
    type: Literal["single", "multiple", "text", "number"]
    options: list[OptionInput] | None = None
    validation: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_content(self):
        # 复用现有题型校验；题序与必答设置只用于校验，不进入题库内容。
        parsed = TypeAdapter(QuestionInput).validate_python({
            **self.model_dump(include={"title", "type", "options", "validation"}, exclude_none=True),
            "order": 1, "required": False,
        })
        self.validation = parsed.validation.model_dump(exclude_none=True)
        return self


class LibraryQuestionRead(LibraryQuestionContent):
    id: Identifier
    rootQuestionId: Identifier
    parentQuestionId: Identifier | None
    version: int = Field(strict=True, ge=1)
    creatorId: Identifier
    restoredFromQuestionId: Identifier | None = None
    shareToken: Text
    sharingEnabled: bool = Field(default=False, strict=True)
    createdAt: datetime

    @model_validator(mode="after")
    def validate_lineage(self):
        if self.version == 1:
            if self.rootQuestionId != self.id or self.parentQuestionId is not None or self.restoredFromQuestionId is not None:
                raise ValueError("第一版必须以自身为根，且不能有父版本或恢复来源")
        elif self.rootQuestionId == self.id or self.parentQuestionId is None or self.parentQuestionId == self.id:
            raise ValueError("后续版本必须具有其他根版本和父版本")
        if any(option.optionId is None for option in self.options or []):
            raise ValueError("已保存版本的选项必须有ID")
        return self


class BankItem(StrictModel):
    rootQuestionId: Identifier
    recommendedVersionId: Identifier
    category: str = ""
    order: int = Field(strict=True, gt=0, le=2**31 - 1)
    addedAt: datetime


class RestoreQuestionInput(StrictModel):
    restoredFromQuestionId: Identifier


class QuestionAccess(StrictModel):
    questionShareToken: Text | None = None
    bankShareToken: Text | None = None
    bankId: Identifier | None = None

    @model_validator(mode="after")
    def one_access_path(self):
        if sum(getattr(self, key) is not None for key in ("questionShareToken", "bankShareToken", "bankId")) > 1:
            raise ValueError("只能指定一个题目访问入口")
        return self


class SharingInput(StrictModel):
    enabled: bool = Field(strict=True)


class BankCreate(StrictModel):
    name: Text
    description: str = ""


class BankUpdate(StrictModel):
    name: Text | None = None
    description: str | None = None

    @model_validator(mode="after")
    def changes(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("至少提供一个非null修改字段")
        return self


class BankItemWrite(QuestionAccess):
    recommendedVersionId: Identifier
    expectedRecommendedVersionId: Identifier | None = None
    category: str = ""
    order: int = Field(strict=True, gt=0, le=2**31 - 1)


class BankItemRemove(StrictModel):
    expectedRecommendedVersionId: Identifier


class SharedQuestionRead(LibraryQuestionContent):
    id: Identifier
    rootQuestionId: Identifier
    parentQuestionId: Identifier | None
    restoredFromQuestionId: Identifier | None = None
    version: int
    createdAt: datetime


class QuestionShareRead(StrictModel):
    recommendedVersionId: Identifier
    question: SharedQuestionRead


class BankViewItem(BankItem):
    question: SharedQuestionRead | None


class SharedBankRead(StrictModel):
    id: Identifier
    name: str
    description: str
    items: list[BankViewItem]


class QuestionBankRead(StrictModel):
    id: Identifier
    creatorId: Identifier
    name: Text
    description: str = ""
    items: list[BankItem] = Field(default_factory=list)
    shareToken: Text
    sharingEnabled: bool = Field(default=False, strict=True)
    createdAt: datetime
    updatedAt: datetime

    @model_validator(mode="after")
    def validate_items(self):
        roots = [item.rootQuestionId.lower() for item in self.items]
        orders = [item.order for item in self.items]
        if len(set(roots)) != len(roots):
            raise ValueError("同一题库不能重复收录同一道题")
        if len(set(orders)) != len(orders):
            raise ValueError("题库内顺序不能重复")
        return self


class BankView(QuestionBankRead):
    items: list[BankViewItem]
