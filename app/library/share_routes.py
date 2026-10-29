"""分享入口不授予编辑权限，不返回其他版本的分享标识或内部授权。"""
from fastapi import APIRouter, Depends, Query, Request, HTTPException

from app.auth.security import current_user
from app.library.access import (shared_question, shared_bank, question_document, public_question, bank_item, identifier)
from app.library.banks import view_bank
from app.library.bank_routes import encode
from app.library.schemas import QuestionShareRead, SharedQuestionRead, SharedBankRead

router = APIRouter(prefix="/shared", tags=["分享访问"])


@router.get("/questions/{token}", response_model=QuestionShareRead)
def question(token: str, request: Request, user=Depends(current_user)):
    anchor = shared_question(request.app.state.database, token)
    return encode({"recommendedVersionId": anchor["_id"], "question": public_question(anchor)})


@router.get("/questions/{token}/versions", response_model=list[SharedQuestionRead])
def question_versions(token: str, request: Request, skip: int = Query(0, ge=0),
                      limit: int = Query(20, ge=1, le=100), user=Depends(current_user)):
    db = request.app.state.database
    anchor = shared_question(db, token)
    return encode([public_question(q) for q in db.questions.find({"rootQuestionId": anchor["rootQuestionId"]})
                   .sort("version", 1).skip(skip).limit(limit)])


@router.get("/banks/{token}", response_model=SharedBankRead)
def bank(token: str, request: Request, user=Depends(current_user)):
    db = request.app.state.database
    return encode(view_bank(db, shared_bank(db, token), user["_id"], shared=True))


@router.get("/banks/{token}/questions/{root_id}/versions", response_model=list[SharedQuestionRead])
def bank_versions(token: str, root_id: str, request: Request, skip: int = Query(0, ge=0),
                  limit: int = Query(20, ge=1, le=100), user=Depends(current_user)):
    db = request.app.state.database
    source = shared_bank(db, token)
    item = bank_item(source, identifier(root_id))
    anchor = question_document(db, str(item["recommendedVersionId"]))
    if anchor["creatorId"] != source["creatorId"]:
        raise HTTPException(404, "收录题目不可分享")
    return encode([public_question(q) for q in db.questions.find({"rootQuestionId": anchor["rootQuestionId"]})
                   .sort("version", 1).skip(skip).limit(limit)])
