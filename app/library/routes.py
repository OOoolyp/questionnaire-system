"""常用题及其不可变版本接口，仅创作者可管理。"""
from bson import ObjectId
from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder

from app.auth.security import current_user
from app.library.schemas import LibraryQuestionContent, LibraryQuestionRead, RestoreQuestionInput, SharingInput
from app.library.access import set_question_sharing
from app.library.questions import create_question, create_version, owned_question, restore_version

router = APIRouter(prefix="/library/questions", tags=["常用题版本"])


def serialize(document):
    return jsonable_encoder({"id": document["_id"], **{key: value for key, value in document.items() if key != "_id"}},
                            custom_encoder={ObjectId: str})


@router.post("", response_model=LibraryQuestionRead, status_code=201, summary="创建常用题第一版")
def create(payload: LibraryQuestionContent, request: Request, user=Depends(current_user)):
    return serialize(create_question(request.app.state.database, user["_id"], payload))


@router.get("", response_model=list[LibraryQuestionRead], summary="查看我的常用题（按第一版列出系列）")
def listing(request: Request, skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
            user=Depends(current_user)):
    documents = request.app.state.database.questions.find({"creatorId": user["_id"], "version": 1})
    return [serialize(doc) for doc in documents.sort([("createdAt", -1), ("_id", -1)]).skip(skip).limit(limit)]


@router.get("/{question_id}", response_model=LibraryQuestionRead, summary="查看具体题目版本")
def detail(question_id: str, request: Request, user=Depends(current_user)):
    return serialize(owned_question(request.app.state.database, question_id, user["_id"]))


@router.get("/{question_id}/versions", response_model=list[LibraryQuestionRead], summary="按编号查看同系列历史版本")
def versions(question_id: str, request: Request, skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
             user=Depends(current_user)):
    database = request.app.state.database
    selected = owned_question(database, question_id, user["_id"])
    documents = database.questions.find({"rootQuestionId": selected["rootQuestionId"], "creatorId": user["_id"]})
    return [serialize(doc) for doc in documents.sort("version", 1).skip(skip).limit(limit)]


@router.post("/{question_id}/versions", response_model=LibraryQuestionRead, status_code=201,
             summary="从指定父版本创建新版本")
def derive(question_id: str, payload: LibraryQuestionContent, request: Request, user=Depends(current_user)):
    return serialize(create_version(request.app.state.database, question_id, user["_id"], payload))


@router.post("/{question_id}/restore", response_model=LibraryQuestionRead, status_code=201,
             summary="将同系列历史内容恢复为新版本")
def restore(question_id: str, payload: RestoreQuestionInput, request: Request, user=Depends(current_user)):
    return serialize(restore_version(request.app.state.database, question_id, user["_id"], payload.restoredFromQuestionId))


@router.post("/{question_id}/sharing", response_model=LibraryQuestionRead, summary="开关当前版本的分享入口")
def sharing(question_id: str, payload: SharingInput, request: Request, user=Depends(current_user)):
    return serialize(set_question_sharing(request.app.state.database, question_id, user["_id"], payload.enabled))
