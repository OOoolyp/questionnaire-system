"""根据已保存答卷实时聚合，不缓存统计结果或暴露填写者身份。"""

from datetime import datetime
from typing import Literal

from bson import ObjectId
from fastapi import HTTPException

from app.questions import Number, StrictModel
from app.submissions import owned


class OptionStatistics(StrictModel):
    optionId: str
    text: str
    count: int


class QuestionStatistics(StrictModel):
    questionId: str
    title: str
    type: Literal["single", "multiple", "text", "number"]
    order: int
    answerCount: int
    options: list[OptionStatistics]
    average: float | None


class SurveyStatistics(StrictModel):
    surveyId: str
    title: str
    submissionCount: int
    questions: list[QuestionStatistics]


class AnswerContent(StrictModel):
    value: str | Number
    submittedAt: datetime


class AnswerPage(StrictModel):
    questionId: str
    total: int
    skip: int
    limit: int
    items: list[AnswerContent]


def find_question(survey, question_id):
    if not ObjectId.is_valid(question_id):
        raise HTTPException(400, "题目ID格式错误")
    question = next((q for q in survey["questions"] if q["questionId"] == ObjectId(question_id)), None)
    if question is None:
        raise HTTPException(404, "题目不存在或不属于本问卷")
    return question


def aggregate_summary(database, survey, question_id=None):
    filter_question = [{"$match": {"answers.questionId": question_id}}] if question_id else []
    result = next(database.responses.aggregate([
        {"$match": {"surveyId": survey["_id"]}},
        {"$facet": {
            "submissions": [{"$count": "count"}],
            "answers": [
                {"$unwind": "$answers"}, *filter_question,
                {"$group": {"_id": "$answers.questionId", "count": {"$sum": 1},
                             "average": {"$avg": "$answers.value"}}},
            ],
            "options": [
                {"$unwind": "$answers"}, *filter_question,
                {"$unwind": "$answers.selectedOptionIds"},
                {"$group": {"_id": {"question": "$answers.questionId", "option": "$answers.selectedOptionIds"},
                             "count": {"$sum": 1}}},
            ],
        }},
    ]))
    answers = {item["_id"]: item for item in result["answers"]}
    options = {(item["_id"]["question"], item["_id"]["option"]): item["count"] for item in result["options"]}
    questions = []
    for question in sorted(survey["questions"], key=lambda q: q["order"]):
        identifier = question["questionId"]
        if question_id is not None and identifier != question_id:
            continue
        summary = answers.get(identifier, {})
        questions.append({
            "questionId": str(identifier), "title": question["title"], "type": question["type"], "order": question["order"],
            "answerCount": summary.get("count", 0),
            "options": [{"optionId": str(option["optionId"]), "text": option["text"],
                         "count": options.get((identifier, option["optionId"]), 0)}
                        for option in sorted(question.get("options", []), key=lambda o: o["order"])],
            "average": summary.get("average") if question["type"] == "number" else None,
        })
    return {"surveyId": str(survey["_id"]), "title": survey["title"],
            "submissionCount": result["submissions"][0]["count"] if result["submissions"] else 0,
            "questions": questions}


def survey_statistics(database, survey_id, user_id):
    survey = owned(database, survey_id, user_id)
    return aggregate_summary(database, survey)


def question_statistics(database, survey_id, question_id, user_id):
    survey = owned(database, survey_id, user_id)
    question = find_question(survey, question_id)
    return aggregate_summary(database, survey, question["questionId"])["questions"][0]


def answer_contents(database, survey_id, question_id, user_id, skip, limit):
    survey = owned(database, survey_id, user_id)
    question = find_question(survey, question_id)
    if question["type"] not in {"text", "number"}:
        raise HTTPException(400, "本接口仅查看文本或数字填空内容；选择题请查看统计")
    result = next(database.responses.aggregate([
        {"$match": {"surveyId": survey["_id"], "answers.questionId": question["questionId"]}},
        {"$sort": {"submittedAt": -1, "_id": -1}},
        {"$unwind": "$answers"},
        {"$match": {"answers.questionId": question["questionId"]}},
        {"$facet": {
            "total": [{"$count": "count"}],
            "items": [{"$skip": skip}, {"$limit": limit},
                      {"$project": {"_id": 0, "value": "$answers.value", "submittedAt": 1}}],
        }},
    ]))
    return {"questionId": question_id, "skip": skip, "limit": limit,
            "total": result["total"][0]["count"] if result["total"] else 0,
            "items": result["items"]}
