"""问卷版本：复制选定版本的单次读取快照，只插入新草稿。"""
from copy import deepcopy
from datetime import datetime, timezone
from secrets import token_urlsafe

from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.surveys.submissions import owned

MAX_INSERT_ATTEMPTS = 16
COPY_FIELDS = ("title", "description", "allowAnonymous", "allowRepeat", "questions")


def create_version(database, survey_id, user_id):
    parent = owned(database, survey_id, user_id)
    identifier = ObjectId()
    document = {
        **{key: deepcopy(parent[key]) for key in COPY_FIELDS},
        "_id": identifier, "creatorId": user_id,
        "rootSurveyId": parent["rootSurveyId"], "parentSurveyId": parent["_id"],
        "createdAt": datetime.now(timezone.utc), "status": "draft", "deadline": None,
    }
    for _ in range(MAX_INSERT_ATTEMPTS):
        latest = database.surveys.find_one({"rootSurveyId": parent["rootSurveyId"]}, sort=[("version", -1)])
        document["version"] = latest["version"] + 1
        document["shareToken"] = token_urlsafe(18)
        try:
            database.surveys.insert_one(document)
        except DuplicateKeyError as error:
            pattern = (error.details or {}).get("keyPattern", {})
            if pattern and pattern not in ({"rootSurveyId": 1, "version": 1}, {"shareToken": 1}):
                raise
            continue
        return database.surveys.find_one({"_id": identifier})
    raise HTTPException(409, "同时创建问卷版本的请求较多，请刷新版本列表后重试")


def list_versions(database, survey_id, user_id, skip, limit):
    parent = owned(database, survey_id, user_id)
    # 历史列表只读摘要，不重复传输各版本的完整题目和分享标识。
    return database.surveys.find(
        {"rootSurveyId": parent["rootSurveyId"], "creatorId": user_id},
        {"rootSurveyId": 1, "parentSurveyId": 1, "version": 1, "title": 1,
         "status": 1, "createdAt": 1},
    ).sort("version", 1).skip(skip).limit(limit)
