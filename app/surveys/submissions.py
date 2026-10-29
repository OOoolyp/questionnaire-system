"""问卷生命周期、填写路径校验和独立答卷存储。"""

from datetime import datetime, timezone

from bson import ObjectId
from fastapi import HTTPException
from pydantic import ConfigDict, Field, TypeAdapter, ValidationError, field_validator
from pymongo.errors import DuplicateKeyError

from app.surveys.jumps import PreviewAnswer, next_question, validate_answer, validate_rules
from app.surveys.questions import Identifier, QuestionInput, QuestionRead, StrictModel


class PublishInput(StrictModel):
    deadline: datetime | None = Field(default=None, description="带时区的截止时间；null表示不设置")

    @field_validator("deadline")
    @classmethod
    def check_timezone(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("截止时间必须带时区，例如2030-12-31T23:59:00+08:00")
        return value


class SubmittedAnswer(PreviewAnswer):
    questionId: Identifier


class SubmissionInput(StrictModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "isAnonymous": False,
        "answers": [{"questionId": "000000000000000000000001", "value": 20}],
    }})
    isAnonymous: bool = Field(False, strict=True)
    answers: list[SubmittedAnswer]


class SubmissionReceipt(StrictModel):
    id: str
    surveyId: str
    submittedAt: datetime
    isAnonymous: bool


class ResponseRead(SubmissionReceipt):
    respondentId: str | None
    answers: list[SubmittedAnswer]


class FillSurveyRead(StrictModel):
    id: str
    title: str
    description: str
    deadline: datetime | None
    allowAnonymous: bool
    allowRepeat: bool
    questions: list[QuestionRead]


class FillStep(PreviewAnswer):
    model_config = ConfigDict(json_schema_extra={"example": {
        "questionId": "000000000000000000000001", "value": 20,
    }})
    questionId: Identifier


def owned(database, survey_id, user_id):
    if not ObjectId.is_valid(survey_id):
        raise HTTPException(400, "问卷ID格式错误")
    survey = database.surveys.find_one({"_id": ObjectId(survey_id), "creatorId": user_id})
    if survey is None:
        raise HTTPException(404, "问卷不存在")
    return survey


def publish(database, survey_id, user_id, payload):
    survey = owned(database, survey_id, user_id)
    if survey["status"] != "draft":
        raise HTTPException(409, "只能发布草稿；已发布或关闭的问卷不能再次发布")
    questions = survey["questions"]
    if not questions:
        raise HTTPException(422, "至少需要一道题才能发布")
    ids, orders = [q["questionId"] for q in questions], [q["order"] for q in questions]
    if len(set(ids)) != len(ids) or len(set(orders)) != len(orders):
        raise HTTPException(422, "题目ID和顺序不能重复")
    for question in questions:
        configuration = {k: v for k, v in question.items() if k not in {"questionId", "jumpRules", "sourceQuestionId"}}
        if "options" in configuration:
            configuration["options"] = [{**o, "optionId": str(o["optionId"])} for o in configuration["options"]]
        try:
            TypeAdapter(QuestionInput).validate_python(configuration)
        except ValidationError:
            raise HTTPException(422, f"题目 {question['questionId']} 配置不完整或校验规则不合法")
    validate_rules(questions)
    now = datetime.now(timezone.utc)
    if payload.deadline is not None and payload.deadline <= now:
        raise HTTPException(422, "截止时间必须晚于当前时间")
    result = database.surveys.update_one(
        {"_id": survey["_id"], "creatorId": user_id, "status": "draft", "questions": questions},
        {"$set": {"status": "published", "deadline": payload.deadline}},
    )
    if not result.matched_count:
        raise HTTPException(409, "问卷已被其他请求修改，请重新查询后再发布")
    return database.surveys.find_one({"_id": survey["_id"]})


def close(database, survey_id, user_id):
    survey = owned(database, survey_id, user_id)
    if survey["status"] != "published":
        raise HTTPException(409, "只能关闭已发布问卷")
    result = database.surveys.update_one({"_id": survey["_id"], "creatorId": user_id, "status": "published"},
                                         {"$set": {"status": "closed"}})
    if not result.matched_count:
        raise HTTPException(409, "问卷状态已改变，请刷新")
    return database.surveys.find_one({"_id": survey["_id"]})


def available(database, share_token):
    survey = database.surveys.find_one({"shareToken": share_token})
    if survey is None or survey["status"] == "draft":
        raise HTTPException(404, "可填写问卷不存在")
    if survey["status"] != "published":
        raise HTTPException(409, "问卷已关闭")
    if survey["deadline"] is not None and datetime.now(timezone.utc) >= survey["deadline"]:
        raise HTTPException(409, "问卷已截止")
    return survey


def validate_submission(survey, payload):
    questions = sorted(survey["questions"], key=lambda q: q["order"])
    by_id = {str(q["questionId"]): q for q in questions}
    provided = {}
    for answer in payload.answers:
        identifier = str(ObjectId(answer.questionId))
        if identifier in provided:
            raise HTTPException(422, "同一道题不能提交多个答案")
        if identifier not in by_id:
            raise HTTPException(422, "答案引用的题目不属于本问卷")
        provided[identifier] = answer
    visited, saved = set(), []
    current = str(questions[0]["questionId"])
    while current is not None:
        if current in visited:
            raise HTTPException(409, "问卷跳转结构存在循环")
        visited.add(current)
        question = by_id[current]
        submitted = provided.get(current)
        answer = PreviewAnswer.model_validate(submitted.model_dump(exclude={"questionId"}, exclude_unset=True)) if submitted else PreviewAnswer()
        try:
            value = validate_answer(question, answer)
        except HTTPException as exc:
            raise HTTPException(exc.status_code, {"questionId": current, "message": exc.detail})
        if value is not None:
            record = {"questionId": ObjectId(current)}
            if question["type"] in {"single", "multiple"}:
                record["selectedOptionIds"] = sorted(value, key=str)
            else:
                record["value"] = value
            saved.append(record)
        current = next_question(questions, question, value)["nextQuestionId"]
    if set(provided) - visited:
        raise HTTPException(422, "不能提交被跳转跳过或结束后的题目答案")
    return saved


def submit(database, share_token, user_id, payload):
    survey = available(database, share_token)
    if payload.isAnonymous and not survey["allowAnonymous"]:
        raise HTTPException(422, "本问卷不允许匿名填写")
    answers = validate_submission(survey, payload)
    # 再次检查状态与时间；此检查成功是本次提交的接收时点。
    available(database, share_token)
    document = {"surveyId": survey["_id"], "respondentId": user_id,
                "isAnonymous": payload.isAnonymous, "submittedAt": datetime.now(timezone.utc),
                "answers": answers, "repeatRestricted": not survey["allowRepeat"]}
    try:
        identifier = database.responses.insert_one(document).inserted_id
    except DuplicateKeyError:
        raise HTTPException(409, "你已经提交过此问卷，不允许重复填写")
    return database.responses.find_one({"_id": identifier})


def receipt(document):
    return {"id": str(document["_id"]), "surveyId": str(document["surveyId"]),
            "submittedAt": document["submittedAt"], "isAnonymous": document["isAnonymous"]}


def creator_response(document):
    return {**receipt(document), "respondentId": None if document["isAnonymous"] else str(document["respondentId"]),
            "answers": document["answers"]}
