"""分享只授予读取和选用；每次请求重新检查入口与系列归属。"""
from bson import ObjectId
from fastapi import HTTPException

from app.library.questions import owned_question


def identifier(value):
    if not ObjectId.is_valid(value):
        raise HTTPException(400, "ID必须为24位十六进制字符串")
    return ObjectId(value)


def question_document(database, question_id):
    question = database.questions.find_one({"_id": identifier(question_id)})
    if question is None:
        raise HTTPException(404, "题目不存在或无权访问")
    return question


def shared_question(database, token):
    question = database.questions.find_one({"shareToken": token, "sharingEnabled": True})
    if question is None:
        raise HTTPException(404, "题目分享不存在或已关闭")
    return question


def owned_bank(database, bank_id, user_id):
    bank = database.question_banks.find_one({"_id": identifier(bank_id), "creatorId": user_id})
    if bank is None:
        raise HTTPException(404, "题库不存在或无权访问")
    return bank


def shared_bank(database, token):
    bank = database.question_banks.find_one({"shareToken": token, "sharingEnabled": True})
    if bank is None:
        raise HTTPException(404, "题库分享不存在或已关闭")
    return bank


def bank_item(bank, root_id):
    item = next((item for item in bank["items"] if item["rootQuestionId"] == root_id), None)
    if item is None:
        raise HTTPException(404, "题目未收录在此题库")
    return item


def readable_question(database, question_id, user_id, proof=None):
    question = question_document(database, question_id)
    if question["creatorId"] == user_id:
        return question
    proof = proof or {}
    if proof.get("bankId"):
        bank = owned_bank(database, proof["bankId"], user_id)
        item = bank_item(bank, question["rootQuestionId"])
        proof = item.get("accessProof", {})
    if proof.get("questionShareToken"):
        anchor = shared_question(database, proof["questionShareToken"])
        if anchor["rootQuestionId"] == question["rootQuestionId"]:
            return question
    elif proof.get("bankShareToken"):
        bank = shared_bank(database, proof["bankShareToken"])
        bank_item(bank, question["rootQuestionId"])
        # 共享题库只能传播创作者本人题目，防止私有外来收录被转分享。
        if bank["creatorId"] == question["creatorId"]:
            return question
    raise HTTPException(404, "题目不存在或当前分享授权已失效")


def persisted_proof(database, question, user_id, payload):
    if question["creatorId"] == user_id:
        return {}
    proof = payload.model_dump(include={"questionShareToken", "bankShareToken", "bankId"}, exclude_none=True)
    if proof.get("bankId"):
        bank = owned_bank(database, proof["bankId"], user_id)
        return dict(bank_item(bank, question["rootQuestionId"]).get("accessProof", {}))
    return proof


def set_question_sharing(database, question_id, user_id, enabled):
    question = owned_question(database, question_id, user_id)
    database.questions.update_one({"_id": question["_id"], "creatorId": user_id}, {"$set": {"sharingEnabled": enabled}})
    return database.questions.find_one({"_id": question["_id"]})


PUBLIC_QUESTION_FIELDS = ("rootQuestionId", "parentQuestionId", "restoredFromQuestionId", "version",
                          "title", "type", "options", "validation", "createdAt")


def public_question(question):
    return {"id": question["_id"], **{key: question[key] for key in PUBLIC_QUESTION_FIELDS if key in question}}
