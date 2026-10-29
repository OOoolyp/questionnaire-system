"""问卷与常用题之间的复用接口。"""
from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from bson import ObjectId

from app.auth.security import current_user
from app.library.routes import serialize
from app.library.schemas import LibraryQuestionRead
from app.library.schemas import SharedQuestionRead
from app.library.access import public_question, question_document
from app.surveys.submissions import owned
from app.surveys.reuse import find_question
from fastapi import HTTPException
from app.surveys.questions import QuestionRead
from app.surveys.reuse import (
    ReuseQuestionInput, SwitchVersionInput, DetachQuestionInput,
    save_to_library, add_from_library, switch_version, detach_question,
)

router = APIRouter(prefix="/surveys/{survey_id}/questions", tags=["题目复用"])


@router.post("/{question_id}/save-to-library", response_model=LibraryQuestionRead, status_code=201,
             summary="将问卷题目另存为常用题第一版，不改变原问卷")
def save(survey_id: str, question_id: str, request: Request, user=Depends(current_user)):
    return serialize(save_to_library(request.app.state.database, survey_id, question_id, user["_id"]))


@router.post("/from-library", response_model=QuestionRead, response_model_exclude_none=True, status_code=201,
             summary="选用具体常用题版本加入草稿")
def add(survey_id: str, payload: ReuseQuestionInput, request: Request, user=Depends(current_user)):
    return jsonable_encoder(add_from_library(request.app.state.database, survey_id, user["_id"], payload),
                            custom_encoder={ObjectId: str})


@router.post("/{question_id}/switch-version", response_model=QuestionRead, response_model_exclude_none=True,
             summary="切换同系列版本，保留问卷内题目ID")
def switch(survey_id: str, question_id: str, payload: SwitchVersionInput, request: Request, user=Depends(current_user)):
    return jsonable_encoder(switch_version(request.app.state.database, survey_id, question_id, user["_id"], payload),
                            custom_encoder={ObjectId: str})


@router.post("/{question_id}/detach", response_model=QuestionRead, response_model_exclude_none=True,
             summary="移除来源关联，保留内容与跳转规则")
def detach(survey_id: str, question_id: str, payload: DetachQuestionInput, request: Request, user=Depends(current_user)):
    return jsonable_encoder(detach_question(request.app.state.database, survey_id, question_id, user["_id"], payload),
                            custom_encoder={ObjectId: str})


@router.get("/{question_id}/source", response_model=SharedQuestionRead, summary="查看自己问卷已使用的固定来源版本")
def source(survey_id: str, question_id: str, request: Request, user=Depends(current_user)):
    db = request.app.state.database
    question = find_question(owned(db, survey_id, user["_id"]), question_id)
    if not question.get("sourceQuestionId"):
        raise HTTPException(404, "此题没有常用题来源")
    return jsonable_encoder(public_question(question_document(db, str(question["sourceQuestionId"]))), custom_encoder={ObjectId: str})
