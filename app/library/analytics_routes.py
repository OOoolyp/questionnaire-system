"""题目作者可追踪引用；答卷聚合始终限定登录用户拥有的问卷。"""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request

from app.auth.security import current_user
from app.surveys.questions import StrictModel, Number
from app.library.statistics import usage, statistics

router = APIRouter(prefix="/analytics/questions/{question_id}", tags=["使用追踪与统计"])


class UsageInstance(StrictModel):
    questionId: str
    sourceQuestionId: str
    sourceVersion: int
    order: int


class UsageItem(StrictModel):
    surveyId: str
    rootSurveyId: str
    surveyVersion: int
    status: Literal["draft", "published", "closed"]
    canViewResults: bool
    title: str | None
    createdAt: datetime | None
    instances: list[UsageInstance]


class UsagePage(StrictModel):
    questionVersionId: str
    rootQuestionId: str
    scope: Literal["version", "series"]
    skip: int
    limit: int
    totalSurveyVersions: int
    totalSurveySeries: int
    totalInstances: int
    restrictedSurveyVersions: int
    items: list[UsageItem]


class Bucket(StrictModel):
    lower: str
    upper: str
    label: str
    count: int


class OptionCount(StrictModel):
    optionId: str
    text: str
    count: int


class TextCount(StrictModel):
    value: str
    count: int


class SurveyCount(StrictModel):
    surveyId: str
    title: str
    version: int
    status: Literal["draft", "published", "closed"]
    instanceCount: int
    submissionCount: int
    answerCount: int


class QuestionAggregate(StrictModel):
    questionVersionId: str
    rootQuestionId: str
    version: int
    title: str
    type: Literal["single", "multiple", "text", "number"]
    scope: Literal["owned_surveys_only"]
    surveyVersionCount: int
    surveySeriesCount: int
    instanceCount: int
    submissionCount: int
    answeredSubmissionCount: int
    answerCount: int
    average: Number | None
    minimum: Number | None
    maximum: Number | None
    bucketSize: float | None
    distribution: list[Bucket]
    distributionTruncated: bool
    options: list[OptionCount]
    textFrequencies: list[TextCount]
    otherTextAnswerCount: int
    surveys: list[SurveyCount]


@router.get("/usage", response_model=UsagePage, summary="查询具体版本或整个题目系列的引用")
def get_usage(question_id: str, request: Request, scope: Literal["version", "series"] = "version",
              skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100), user=Depends(current_user)):
    return usage(request.app.state.database, question_id, user["_id"], scope, skip, limit)


@router.get("/statistics", response_model=QuestionAggregate, summary="按具体题目版本汇总本人问卷中的答案")
def get_statistics(question_id: str, request: Request,
                   bucket_size: float = Query(10, gt=0, le=1e12, allow_inf_nan=False), user=Depends(current_user)):
    return statistics(request.app.state.database, question_id, user["_id"], bucket_size)
