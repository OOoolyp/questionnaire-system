"""可重复执行的结构升级与索引；不重建问卷或改动答卷。"""


def migrate_survey_versions(database):
    fields = ("rootSurveyId", "parentSurveyId", "version")
    missing = {"$or": [{key: {"$exists": False}} for key in fields]}
    documents = list(database.surveys.find(missing, {key: 1 for key in fields}))
    # 部分版本字段可能来自未完成的人工迁移，不能擅自把它重置为第一版。
    if any(any(key in document for key in fields) for document in documents):
        raise RuntimeError("问卷版本字段不完整，请修复后重启；不会重置已有版本关系")
    for document in documents:
        database.surveys.update_one(
            {"_id": document["_id"], **{key: {"$exists": False} for key in fields}},
            {"$set": {"rootSurveyId": document["_id"], "parentSurveyId": None, "version": 1}},
        )


def prepare_database(database):
    migrate_survey_versions(database)
    database.users.create_index("username", unique=True)
    if "accessToken_1" in database.surveys.index_information():
        database.surveys.drop_index("accessToken_1")
    database.surveys.update_many(
        {"accessToken": {"$exists": True}, "shareToken": {"$exists": False}},
        {"$rename": {"accessToken": "shareToken"}},
    )
    database.surveys.create_index("shareToken", unique=True)
    database.surveys.create_index([("creatorId", 1), ("createdAt", -1), ("_id", -1)])
    database.surveys.create_index([("rootSurveyId", 1), ("version", 1)], unique=True)
    database.surveys.create_index("questions.sourceQuestionId")
    database.questions.create_index([("rootQuestionId", 1), ("version", 1)], unique=True)
    database.questions.create_index("shareToken", unique=True)
    database.questions.create_index([("creatorId", 1), ("createdAt", -1), ("_id", -1)])
    database.question_banks.create_index("shareToken", unique=True)
    database.question_banks.create_index([("creatorId", 1), ("createdAt", -1), ("_id", -1)])
    database.responses.create_index([("surveyId", 1), ("respondentId", 1)], unique=True,
        partialFilterExpression={"repeatRestricted": True}, name="one_response_per_user")
    database.responses.create_index([("surveyId", 1), ("submittedAt", -1), ("_id", -1)])
