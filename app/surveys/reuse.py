"""题目复用：服务端复制版本内容，草稿单文档条件更新。"""
from copy import deepcopy

from bson import ObjectId
from fastapi import HTTPException
from pydantic import Field, TypeAdapter, ValidationError

from app.library.questions import CONTENT_FIELDS, create_question
from app.library.schemas import LibraryQuestionContent, QuestionAccess
from app.library.access import readable_question, question_document
from app.surveys.questions import Identifier, QuestionInput, StrictModel
from app.surveys.submissions import owned
from app.surveys.jumps import validate_rules


class ReuseQuestionInput(QuestionAccess):
    sourceQuestionId: Identifier
    order: int | None = Field(default=None, strict=True, gt=0, le=2**31 - 1)
    beforeQuestionId: Identifier | None = None
    required: bool = Field(default=False, strict=True)


class SwitchVersionInput(QuestionAccess):
    sourceQuestionId: Identifier
    expectedSourceQuestionId: Identifier
    clearJumpRules: bool = Field(default=False, strict=True)


class DetachQuestionInput(StrictModel):
    expectedSourceQuestionId: Identifier


def find_question(survey, question_id):
    if not ObjectId.is_valid(question_id):
        raise HTTPException(400, "题目ID格式错误")
    question = next((q for q in survey["questions"] if q["questionId"] == ObjectId(question_id)), None)
    if question is None:
        raise HTTPException(404, "题目不存在或不属于本问卷")
    return question


def draft(database, survey_id, user_id):
    survey = owned(database, survey_id, user_id)
    if survey["status"] != "draft":
        raise HTTPException(409, "只有草稿问卷可以选题、切换版本或转为独立题")
    return survey


def snapshot(source):
    return {key: deepcopy(source[key]) for key in CONTENT_FIELDS if key in source}


def validate_question(question):
    content = {key: value for key, value in question.items()
               if key not in {"questionId", "sourceQuestionId", "jumpRules"}}
    if "options" in content:
        content["options"] = [{**o, "optionId": str(o["optionId"])} for o in content["options"]]
    try:
        TypeAdapter(QuestionInput).validate_python(content)
    except ValidationError:
        raise HTTPException(422, "所选版本与当前必答设置不兼容，请调整设置后重试")


def save_questions(database, survey, user_id, questions):
    validate_rules(questions, code=409)
    result = database.surveys.update_one(
        {"_id": survey["_id"], "creatorId": user_id, "status": "draft", "questions": survey["questions"]},
        {"$set": {"questions": sorted(questions, key=lambda q: q["order"])}})
    if not result.matched_count:
        raise HTTPException(409, "问卷已被其他请求修改或发布，请刷新后重试")


def save_to_library(database, survey_id, question_id, user_id):
    # 仅保存独立副本，不修改原问卷，已发布问卷也可保存。
    survey = owned(database, survey_id, user_id)
    content = snapshot(find_question(survey, question_id))
    if "options" in content:
        content["options"] = [{"text": item["text"], "order": item["order"]} for item in content["options"]]
    return create_question(database, user_id, LibraryQuestionContent.model_validate(content))


def add_from_library(database, survey_id, user_id, payload):
    survey = draft(database, survey_id, user_id)
    proof = payload.model_dump(include={"questionShareToken", "bankShareToken", "bankId"}, exclude_none=True)
    source = readable_question(database, payload.sourceQuestionId, user_id, proof)
    questions = deepcopy(survey["questions"])
    if payload.beforeQuestionId:
        target = find_question(survey, payload.beforeQuestionId)
        order = target["order"]
        if payload.order is not None and payload.order != order:
            raise HTTPException(409, "插入位置已改变，请刷新后重新选题")
        for item in questions:
            if item["order"] >= order:
                if item["order"] >= 2**31 - 1:
                    raise HTTPException(422, "题序已达上限，无法插入")
                item["order"] += 1
    else:
        order = payload.order if payload.order is not None else max((q["order"] for q in questions), default=0) + 1
        if order > 2**31 - 1:
            raise HTTPException(422, "题序已达上限，无法追加")
        if any(q["order"] == order for q in questions):
            raise HTTPException(409, "题序已被占用，请指定其他题序或插入位置")
    question = {**snapshot(source), "questionId": ObjectId(), "sourceQuestionId": source["_id"],
                "order": order, "required": payload.required, "jumpRules": []}
    validate_question(question)
    save_questions(database, survey, user_id, questions + [question])
    return question


def referenced_question(database, survey_id, question_id, user_id, expected_source):
    survey = draft(database, survey_id, user_id)
    question = find_question(survey, question_id)
    if question.get("sourceQuestionId") != ObjectId(expected_source):
        raise HTTPException(409, "题目来源已改变或已是独立题，请刷新后重试")
    return survey, question


def switch_version(database, survey_id, question_id, user_id, payload):
    survey, previous = referenced_question(database, survey_id, question_id, user_id, payload.expectedSourceQuestionId)
    original = question_document(database, str(previous["sourceQuestionId"]))
    proof = payload.model_dump(include={"questionShareToken", "bankShareToken", "bankId"}, exclude_none=True)
    source = readable_question(database, payload.sourceQuestionId, user_id, proof)
    if source["rootQuestionId"] != original["rootQuestionId"]:
        raise HTTPException(422, "切换版本必须选择同一道常用题的版本")
    question = {**snapshot(source), "questionId": previous["questionId"], "sourceQuestionId": source["_id"],
                "order": previous["order"], "required": previous["required"],
                "jumpRules": [] if payload.clearJumpRules else deepcopy(previous["jumpRules"])}
    validate_question(question)
    questions = [question if q["questionId"] == previous["questionId"] else q for q in survey["questions"]]
    save_questions(database, survey, user_id, questions)
    return question


def detach_question(database, survey_id, question_id, user_id, payload):
    survey, previous = referenced_question(database, survey_id, question_id, user_id, payload.expectedSourceQuestionId)
    question = deepcopy(previous)
    question.pop("sourceQuestionId")
    questions = [question if q["questionId"] == previous["questionId"] else q for q in survey["questions"]]
    save_questions(database, survey, user_id, questions)
    return question
