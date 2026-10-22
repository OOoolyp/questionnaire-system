"""题目请求结构、按题型校验，以及嵌入文档的编辑逻辑。"""

from typing import Annotated, Literal
from copy import deepcopy

from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Identifier = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{24}$")]
Count = Annotated[int, Field(strict=True, ge=0, le=2**31 - 1)]
Number = Annotated[int, Field(strict=True, ge=-(2**63), le=2**63 - 1)] | Annotated[
    float, Field(strict=True, allow_inf_nan=False)
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OptionInput(StrictModel):
    optionId: Identifier | None = None
    text: Text
    order: int = Field(strict=True, gt=0, le=2**31 - 1)


class EmptyValidation(StrictModel):
    pass


class MultipleValidation(StrictModel):
    minChoices: Count | None = None
    maxChoices: Count | None = None

    @model_validator(mode="after")
    def check_range(self):
        if self.minChoices is not None and self.maxChoices is not None and self.minChoices > self.maxChoices:
            raise ValueError("最少选择数不能大于最多选择数")
        return self


class TextValidation(StrictModel):
    minLength: Count | None = None
    maxLength: Count | None = None

    @model_validator(mode="after")
    def check_range(self):
        if self.minLength is not None and self.maxLength is not None and self.minLength > self.maxLength:
            raise ValueError("最小长度不能大于最大长度")
        return self


class NumberValidation(StrictModel):
    minValue: Number | None = None
    maxValue: Number | None = None
    integerOnly: bool = Field(False, strict=True)

    @model_validator(mode="after")
    def check_range(self):
        if self.minValue is not None and self.maxValue is not None and self.minValue > self.maxValue:
            raise ValueError("数值下限不能大于上限")
        if self.integerOnly and self.minValue is not None and self.maxValue is not None:
            from math import ceil, floor
            if ceil(self.minValue) > floor(self.maxValue):
                raise ValueError("数值范围内没有可填写的整数")
        return self


class QuestionBase(StrictModel):
    title: Text
    order: int = Field(strict=True, gt=0, le=2**31 - 1)
    required: bool = Field(False, strict=True)


class ChoiceQuestion(QuestionBase):
    options: list[OptionInput] = Field(min_length=2)

    @model_validator(mode="after")
    def check_options(self):
        orders = [option.order for option in self.options]
        ids = [str(ObjectId(option.optionId)) for option in self.options if option.optionId]
        if len(set(orders)) != len(orders):
            raise ValueError("选项顺序不能重复")
        if len(set(ids)) != len(ids):
            raise ValueError("选项ID不能重复")
        return self


class SingleQuestion(ChoiceQuestion):
    type: Literal["single"]
    validation: EmptyValidation = Field(default_factory=EmptyValidation)


class MultipleQuestion(ChoiceQuestion):
    type: Literal["multiple"]
    validation: MultipleValidation = Field(default_factory=MultipleValidation)

    @model_validator(mode="after")
    def check_counts(self):
        for count in [self.validation.minChoices, self.validation.maxChoices]:
            if count is not None and count > len(self.options):
                raise ValueError("选择数量限制不能超过选项数量")
        if self.required and self.validation.maxChoices == 0:
            raise ValueError("必答多选题的最多选择数不能为0")
        return self


class TextQuestion(QuestionBase):
    type: Literal["text"]
    validation: TextValidation = Field(default_factory=TextValidation)


class NumberQuestion(QuestionBase):
    type: Literal["number"]
    validation: NumberValidation = Field(default_factory=NumberValidation)


QuestionInput = Annotated[
    SingleQuestion | MultipleQuestion | TextQuestion | NumberQuestion,
    Field(discriminator="type"),
]

QUESTION_EXAMPLES = {
    "single": {"summary": "单选题", "value": {
        "type": "single", "title": "你喜欢哪种水果？", "order": 1, "required": True,
        "options": [{"text": "苹果", "order": 1}, {"text": "香蕉", "order": 2}],
        "validation": {},
    }},
    "multiple": {"summary": "多选题", "value": {
        "type": "multiple", "title": "你喜欢哪些水果？", "order": 2, "required": True,
        "options": [{"text": "苹果", "order": 1}, {"text": "香蕉", "order": 2},
                    {"text": "西瓜", "order": 3}],
        "validation": {"minChoices": 1, "maxChoices": 2},
    }},
    "text": {"summary": "文本填空", "value": {
        "type": "text", "title": "你的建议", "order": 3, "required": False,
        "validation": {"minLength": 2, "maxLength": 100},
    }},
    "number": {"summary": "数字填空", "value": {
        "type": "number", "title": "你的年龄", "order": 4, "required": True,
        "validation": {"minValue": 0, "maxValue": 120, "integerOnly": True},
    }},
}


class QuestionRead(QuestionBase):
    questionId: str
    type: Literal["single", "multiple", "text", "number"]
    options: list[OptionInput] | None = None
    validation: dict
    jumpRules: list[dict]


def build_question(payload, previous=None):
    question = payload.model_dump(exclude_none=True)
    question["questionId"] = previous["questionId"] if previous else ObjectId()
    question["jumpRules"] = (previous or {}).get("jumpRules", [])
    existing_ids = {option["optionId"] for option in (previous or {}).get("options", [])}
    for option in question.get("options", []):
        supplied = option.get("optionId")
        if supplied is not None:
            identifier = ObjectId(supplied)
            if identifier not in existing_ids:
                raise HTTPException(422, "选项ID只能引用当前题目已有的选项；新选项请省略optionId")
        else:
            identifier = ObjectId()
        option["optionId"] = identifier
    if "options" in question:
        question["options"].sort(key=lambda option: option["order"])
    return question


def edit_question(database, survey_id, user_id, payload=None, question_id=None, delete=False):
    if not ObjectId.is_valid(survey_id) or (question_id is not None and not ObjectId.is_valid(question_id)):
        raise HTTPException(400, "问卷ID和题目ID必须是24位十六进制字符串")
    query = {"_id": ObjectId(survey_id), "creatorId": user_id}
    survey = database.surveys.find_one(query)
    if survey is None:
        raise HTTPException(404, "问卷不存在")
    if survey["status"] != "draft":
        raise HTTPException(409, "只有草稿问卷可以编辑题目")
    questions = survey["questions"]
    previous = None
    if question_id is not None:
        previous = next((q for q in questions if q["questionId"] == ObjectId(question_id)), None)
        if previous is None:
            raise HTTPException(404, "题目不存在")
        questions = [q for q in questions if q["questionId"] != previous["questionId"]]
    if not delete:
        question = build_question(payload, previous)
        if any(q["order"] == question["order"] for q in questions):
            raise HTTPException(409, "题目顺序已被占用，请使用其他正整数")
        questions = questions + [question]
    questions.sort(key=lambda q: q["order"])
    from app.jumps import validate_rules
    validate_rules(questions, code=409)
    # 检查读取时的题目数组，防止并发编辑覆盖别人的修改。
    result = database.surveys.update_one(
        {**query, "status": "draft", "questions": survey["questions"]},
        {"$set": {"questions": questions}},
    )
    if not result.matched_count:
        raise HTTPException(409, "问卷已被其他请求修改，请重新查询后再试")
    return None if delete else question


def insert_question_before(database, survey_id, before_question_id, user_id, payload):
    """一次原子写入插入题目并顺移后续题序，不逐题修改，保留所有现有ID。"""
    if not ObjectId.is_valid(survey_id) or not ObjectId.is_valid(before_question_id):
        raise HTTPException(400, "问卷ID和目标题目ID格式错误")
    query = {"_id": ObjectId(survey_id), "creatorId": user_id}
    survey = database.surveys.find_one(query)
    if survey is None:
        raise HTTPException(404, "问卷不存在")
    if survey["status"] != "draft":
        raise HTTPException(409, "只有草稿问卷可以插入题目")
    target = next((q for q in survey["questions"] if q["questionId"] == ObjectId(before_question_id)), None)
    if target is None:
        raise HTTPException(404, "目标题目不存在")
    if payload.order != target["order"]:
        raise HTTPException(409, "题目顺序已经改变，请关闭窗口并刷新后重新插入")
    questions = deepcopy(survey["questions"])
    for question in questions:
        if question["order"] >= target["order"]:
            if question["order"] >= 2**31 - 1:
                raise HTTPException(422, "题目顺序已达上限，无法继续插入")
            question["order"] += 1
    inserted = build_question(payload)
    questions.append(inserted)
    questions.sort(key=lambda q: q["order"])
    from app.jumps import validate_rules
    validate_rules(questions, code=409)
    result = database.surveys.update_one(
        {**query, "status": "draft", "questions": survey["questions"]},
        {"$set": {"questions": questions}},
    )
    if not result.matched_count:
        raise HTTPException(409, "问卷已被其他请求修改，请重新查询后再试")
    return inserted
