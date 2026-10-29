"""问卷历史与新版本接口，版本内容仍由原有问卷接口编辑。"""
from datetime import datetime
from typing import Literal

from bson import ObjectId
from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import Field

from app.auth.security import current_user
from app.surveys.questions import Identifier, StrictModel
from app.surveys.schemas import SurveyRead
from app.surveys.versions import create_version, list_versions

router = APIRouter(prefix="/surveys/{survey_id}/versions", tags=["问卷版本"])


class SurveyVersionCreate(StrictModel):
    """空请求；版本、来源、身份和分享标识全部由服务端生成。"""


class SurveyVersionRead(StrictModel):
    id: Identifier
    rootSurveyId: Identifier
    parentSurveyId: Identifier | None
    version: int = Field(strict=True, ge=1)
    title: str
    status: Literal["draft", "published", "closed"]
    createdAt: datetime


def serialize(document):
    return jsonable_encoder({"id": document["_id"], **{k: v for k, v in document.items() if k != "_id"}},
                            custom_encoder={ObjectId: str})


@router.post("", response_model=SurveyRead, status_code=201, summary="从指定问卷版本创建新草稿")
def create(survey_id: str, payload: SurveyVersionCreate, request: Request, user=Depends(current_user)):
    return serialize(create_version(request.app.state.database, survey_id, user["_id"]))


@router.get("", response_model=list[SurveyVersionRead], summary="查询同系列问卷历史，按版本号升序")
def history(survey_id: str, request: Request, skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
            user=Depends(current_user)):
    return [serialize(doc) for doc in list_versions(request.app.state.database, survey_id, user["_id"], skip, limit)]
