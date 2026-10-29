"""题库由创作者管理；收录和推荐版本使用单文档条件更新。"""
from copy import deepcopy
from datetime import datetime, timezone
from secrets import token_urlsafe

from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.library.access import (owned_bank, readable_question, persisted_proof, public_question,
                                question_document, identifier)


def create_bank(database, user_id, payload):
    document = {**payload.model_dump(), "_id": ObjectId(), "creatorId": user_id,
                "items": [], "sharingEnabled": False, "createdAt": datetime.now(timezone.utc)}
    document["updatedAt"] = document["createdAt"]
    for _ in range(16):
        document["shareToken"] = token_urlsafe(18)
        try:
            database.question_banks.insert_one(document)
        except DuplicateKeyError:
            continue
        return database.question_banks.find_one({"_id": document["_id"]})
    raise HTTPException(409, "无法分配题库分享标识，请重试")


def condition(bank):
    return {key: bank[key] for key in ("_id", "creatorId", "name", "description", "items", "sharingEnabled")}


def update_bank(database, bank, changes):
    result = database.question_banks.update_one(condition(bank), {"$set": {**changes, "updatedAt": datetime.now(timezone.utc)}})
    if not result.matched_count:
        raise HTTPException(409, "题库已被其他请求修改，请刷新后重试")
    return database.question_banks.find_one({"_id": bank["_id"]})


def set_sharing(database, bank_id, user_id, enabled):
    bank = owned_bank(database, bank_id, user_id)
    if enabled:
        for item in bank["items"]:
            question = question_document(database, str(item["recommendedVersionId"]))
            if question["creatorId"] != user_id:
                raise HTTPException(409, "题库包含他人题目，不能再次分享；请移除外来收录后再开启")
    return update_bank(database, bank, {"sharingEnabled": enabled})


def put_item(database, bank_id, root_id, user_id, payload):
    bank = owned_bank(database, bank_id, user_id)
    root = identifier(root_id)
    proof = payload.model_dump(include={"questionShareToken", "bankShareToken", "bankId"}, exclude_none=True)
    question = readable_question(database, payload.recommendedVersionId, user_id, proof)
    if question["rootQuestionId"] != root:
        raise HTTPException(422, "推荐版本不属于收录的题目系列")
    if bank["sharingEnabled"] and question["creatorId"] != user_id:
        raise HTTPException(409, "已共享题库不能收录他人题目")
    items = deepcopy(bank["items"])
    previous = next((item for item in items if item["rootQuestionId"] == root), None)
    expected = ObjectId(payload.expectedRecommendedVersionId) if payload.expectedRecommendedVersionId else None
    if (previous and expected != previous["recommendedVersionId"]) or (not previous and expected is not None):
        raise HTTPException(409, "收录项已存在或推荐版本已改变，请刷新后重试")
    if any(item["rootQuestionId"] != root and item["order"] == payload.order for item in items):
        raise HTTPException(409, "题库顺序已被占用")
    item = {"rootQuestionId": root, "recommendedVersionId": question["_id"], "category": payload.category.strip(),
            "order": payload.order, "addedAt": previous["addedAt"] if previous else datetime.now(timezone.utc)}
    access = persisted_proof(database, question, user_id, payload)
    if access:
        item["accessProof"] = access
    items = [entry for entry in items if entry["rootQuestionId"] != root] + [item]
    return update_bank(database, bank, {"items": sorted(items, key=lambda row: row["order"])})


def remove_item(database, bank_id, root_id, user_id, expected):
    bank = owned_bank(database, bank_id, user_id)
    root = identifier(root_id)
    item = next((item for item in bank["items"] if item["rootQuestionId"] == root), None)
    if item is None or item["recommendedVersionId"] != ObjectId(expected):
        raise HTTPException(409, "收录项或推荐版本已改变，请刷新后重试")
    return update_bank(database, bank, {"items": [entry for entry in bank["items"] if entry["rootQuestionId"] != root]})


def delete_bank(database, bank_id, user_id):
    bank = owned_bank(database, bank_id, user_id)
    if not database.question_banks.delete_one(condition(bank)).deleted_count:
        raise HTTPException(409, "题库已被修改，请刷新后重试")


def view_bank(database, bank, user_id, shared=False):
    result = {"id": bank["_id"], "name": bank["name"], "description": bank["description"], "items": []}
    if not shared:
        result.update({key: bank[key] for key in ("creatorId", "shareToken", "sharingEnabled", "createdAt", "updatedAt")})
    for item in sorted(bank["items"], key=lambda row: row["order"]):
        public = {key: value for key, value in item.items() if key != "accessProof"}
        try:
            proof = {"bankShareToken": bank["shareToken"]} if shared else {"bankId": str(bank["_id"])}
            question = readable_question(database, str(item["recommendedVersionId"]), user_id, proof)
            public["question"] = public_question(question)
        except HTTPException as error:
            if error.status_code != 404:
                raise
            public["question"] = None
        result["items"].append(public)
    return result
