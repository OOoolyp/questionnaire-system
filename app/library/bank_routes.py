"""题库管理、收录、分类排序及推荐版本。"""
from bson import ObjectId
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.encoders import jsonable_encoder

from app.auth.security import current_user
from app.library import banks
from app.library.access import owned_bank, bank_item, readable_question, identifier, public_question
from app.library.schemas import (BankCreate, BankUpdate, BankItemWrite, BankItemRemove, BankView,
                                 QuestionBankRead, SharingInput, SharedQuestionRead)

router = APIRouter(prefix="/library/banks", tags=["题库"])


def encode(value):
    return jsonable_encoder(value, custom_encoder={ObjectId: str})


@router.post("", response_model=BankView, status_code=201)
def create(payload: BankCreate, request: Request, user=Depends(current_user)):
    db = request.app.state.database
    return encode(banks.view_bank(db, banks.create_bank(db, user["_id"], payload), user["_id"]))


@router.get("", response_model=list[QuestionBankRead])
def listing(request: Request, skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100), user=Depends(current_user)):
    rows = request.app.state.database.question_banks.find({"creatorId": user["_id"]}).sort(
        [("createdAt", -1), ("_id", -1)]).skip(skip).limit(limit)
    result = []
    for row in rows:
        result.append({"id": row["_id"], **{k: v for k, v in row.items() if k not in {"_id", "items"}},
                       "items": [{k: v for k, v in item.items() if k != "accessProof"} for item in row["items"]]})
    return encode(result)


@router.get("/{bank_id}", response_model=BankView)
def detail(bank_id: str, request: Request, user=Depends(current_user)):
    db = request.app.state.database
    return encode(banks.view_bank(db, owned_bank(db, bank_id, user["_id"]), user["_id"]))


@router.patch("/{bank_id}", response_model=BankView)
def update(bank_id: str, payload: BankUpdate, request: Request, user=Depends(current_user)):
    db = request.app.state.database
    bank = banks.update_bank(db, owned_bank(db, bank_id, user["_id"]), payload.model_dump(exclude_unset=True))
    return encode(banks.view_bank(db, bank, user["_id"]))


@router.delete("/{bank_id}", status_code=204)
def delete(bank_id: str, request: Request, user=Depends(current_user)):
    banks.delete_bank(request.app.state.database, bank_id, user["_id"])
    return Response(status_code=204)


@router.post("/{bank_id}/sharing", response_model=BankView)
def sharing(bank_id: str, payload: SharingInput, request: Request, user=Depends(current_user)):
    db = request.app.state.database
    return encode(banks.view_bank(db, banks.set_sharing(db, bank_id, user["_id"], payload.enabled), user["_id"]))


@router.put("/{bank_id}/items/{root_id}", response_model=BankView)
def put_item(bank_id: str, root_id: str, payload: BankItemWrite, request: Request, user=Depends(current_user)):
    db = request.app.state.database
    return encode(banks.view_bank(db, banks.put_item(db, bank_id, root_id, user["_id"], payload), user["_id"]))


@router.delete("/{bank_id}/items/{root_id}", response_model=BankView)
def remove_item(bank_id: str, root_id: str, payload: BankItemRemove, request: Request, user=Depends(current_user)):
    db = request.app.state.database
    return encode(banks.view_bank(db, banks.remove_item(db, bank_id, root_id, user["_id"], payload.expectedRecommendedVersionId), user["_id"]))


@router.get("/{bank_id}/questions/{root_id}/versions", response_model=list[SharedQuestionRead])
def versions(bank_id: str, root_id: str, request: Request, skip: int = Query(0, ge=0),
             limit: int = Query(20, ge=1, le=100), user=Depends(current_user)):
    db = request.app.state.database
    bank = owned_bank(db, bank_id, user["_id"])
    item = bank_item(bank, identifier(root_id))
    readable_question(db, str(item["recommendedVersionId"]), user["_id"], {"bankId": bank_id})
    return encode([public_question(q) for q in db.questions.find({"rootQuestionId": item["rootQuestionId"]})
                   .sort("version", 1).skip(skip).limit(limit)])
