"""常用题版本：只插入，不覆盖；系列内编号与父版本关系独立。"""
from copy import deepcopy
from datetime import datetime, timezone
from secrets import token_urlsafe

from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

CONTENT_FIELDS = ("title", "type", "options", "validation")
MAX_INSERT_ATTEMPTS = 16


def owned_question(database, question_id, user_id):
    if not ObjectId.is_valid(question_id):
        raise HTTPException(400, "题目ID必须是24位十六进制字符串")
    document = database.questions.find_one({"_id": ObjectId(question_id), "creatorId": user_id})
    if document is None:
        raise HTTPException(404, "题目不存在或无权访问")
    return document


def build_content(payload, parent=None):
    content = payload.model_dump(include=set(CONTENT_FIELDS), exclude_none=True)
    previous_ids = {item["optionId"] for item in (parent or {}).get("options", [])}
    for option in content.get("options", []):
        supplied = option.get("optionId")
        if supplied is not None and ObjectId(supplied) not in previous_ids:
            raise HTTPException(422, "选项ID只能引用父版本已有的选项；新选项请省略optionId")
        option["optionId"] = ObjectId(supplied) if supplied else ObjectId()
    if "options" in content:
        content["options"].sort(key=lambda item: item["order"])
    return content


def insert_version(database, user_id, content, parent=None, restored_from=None):
    identifier = ObjectId()
    root = parent["rootQuestionId"] if parent else identifier
    document = {
        **deepcopy(content), "_id": identifier, "rootQuestionId": root,
        "parentQuestionId": parent["_id"] if parent else None,
        "restoredFromQuestionId": restored_from,
        "creatorId": user_id, "sharingEnabled": False,
        "createdAt": datetime.now(timezone.utc),
    }
    for _ in range(MAX_INSERT_ATTEMPTS):
        latest = database.questions.find_one({"rootQuestionId": root}, sort=[("version", -1)]) if parent else None
        document["version"] = latest["version"] + 1 if latest else 1
        document["shareToken"] = token_urlsafe(18)
        try:
            database.questions.insert_one(document)
        except DuplicateKeyError:
            # 联合唯一索引兜底并发取号；分享标识碰撞也重新生成后重试。
            continue
        return database.questions.find_one({"_id": identifier})
    raise HTTPException(409, "同时创建版本的请求较多，请刷新版本列表后重试")


def create_question(database, user_id, payload):
    return insert_version(database, user_id, build_content(payload))


def create_version(database, question_id, user_id, payload):
    parent = owned_question(database, question_id, user_id)
    return insert_version(database, user_id, build_content(payload, parent), parent)


def restore_version(database, question_id, user_id, restored_from_id):
    parent = owned_question(database, question_id, user_id)
    source = owned_question(database, restored_from_id, user_id)
    if source["rootQuestionId"] != parent["rootQuestionId"]:
        raise HTTPException(422, "只能恢复同一道题的历史版本")
    content = {key: deepcopy(source[key]) for key in CONTENT_FIELDS if key in source}
    return insert_version(database, user_id, content, parent, source["_id"])
