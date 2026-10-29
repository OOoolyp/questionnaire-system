"""使用追踪与按具体版本聚合。题目分享不等于答卷授权。"""
from decimal import Decimal, localcontext

from bson import Decimal128
from fastapi import HTTPException

from app.library.access import question_document


def analytics_question(database, question_id, user_id):
    question = question_document(database, question_id)
    author = question["creatorId"] == user_id
    if not author and not database.surveys.find_one(
        {"creatorId": user_id, "questions.sourceQuestionId": question["_id"]}, {"_id": 1}
    ):
        raise HTTPException(404, "题目不存在或没有可查看的使用记录")
    return question, author


def usage(database, question_id, user_id, scope, skip, limit):
    question, author = analytics_question(database, question_id, user_id)
    versions = list(database.questions.find({"rootQuestionId": question["rootQuestionId"]}, {"version": 1}))
    version_numbers = {q["_id"]: q["version"] for q in versions}
    ids = list(version_numbers) if scope == "series" else [question["_id"]]
    query = {"questions.sourceQuestionId": {"$in": ids}}
    if not author:
        query["creatorId"] = user_id
    result = next(database.surveys.aggregate([
        {"$match": query},
        {"$project": {"creatorId": 1, "rootSurveyId": 1, "version": 1, "status": 1,
                       "title": 1, "createdAt": 1, "matches": {"$filter": {"input": "$questions", "as": "q",
                       "cond": {"$in": ["$$q.sourceQuestionId", ids]}}}}},
        {"$facet": {
            "totals": [{"$group": {"_id": None, "versions": {"$sum": 1},
                "instances": {"$sum": {"$size": "$matches"}},
                "series": {"$addToSet": {"$ifNull": ["$rootSurveyId", "$_id"]}},
                "owned": {"$sum": {"$cond": [{"$eq": ["$creatorId", user_id]}, 1, 0]}}}}],
            "items": [{"$sort": {"createdAt": -1, "_id": -1}}, {"$skip": skip}, {"$limit": limit}],
        }},
    ]))
    totals = next(iter(result["totals"]), {})
    items = []
    for survey in result["items"]:
        own = survey["creatorId"] == user_id
        items.append({"surveyId": str(survey["_id"]), "rootSurveyId": str(survey.get("rootSurveyId", survey["_id"])),
            "surveyVersion": survey["version"], "status": survey["status"], "canViewResults": own,
            "title": survey["title"] if own else None,
            "createdAt": survey["createdAt"] if own else None,
            "instances": [{"questionId": str(q["questionId"]), "sourceQuestionId": str(q["sourceQuestionId"]),
                           "sourceVersion": version_numbers[q["sourceQuestionId"]], "order": q["order"]}
                          for q in survey["matches"]]})
    return {"questionVersionId": str(question["_id"]), "rootQuestionId": str(question["rootQuestionId"]),
            "scope": scope, "skip": skip, "limit": limit,
            "totalSurveyVersions": totals.get("versions", 0), "totalSurveySeries": len(totals.get("series", [])),
            "totalInstances": totals.get("instances", 0),
            "restrictedSurveyVersions": totals.get("versions", 0) - totals.get("owned", 0), "items": items}


def bucket_stage(size):
    # 用十进制处理边界，避免 0.3 / 0.1 的二进制浮点误差。
    return {"$group": {"_id": {"$floor": {"$divide": [{"$toDecimal": "$answers.value"}, Decimal128(str(size))]}},
                       "count": {"$sum": 1}}}


def decimal_label(value):
    return format(value, "f") if value.adjusted() < 15 and value.adjusted() > -10 else str(value.normalize())


def statistics(database, question_id, user_id, bucket_size):
    question, _ = analytics_question(database, question_id, user_id)
    surveys = list(database.surveys.find({"creatorId": user_id, "questions.sourceQuestionId": question["_id"]},
        {"title": 1, "rootSurveyId": 1, "version": 1, "status": 1, "questions": 1}))
    response_query = {"surveyId": {"$in": [s["_id"] for s in surveys]}}
    pairs = [{"surveyId": s["_id"], "answers.questionId": {"$in": [q["questionId"] for q in s["questions"]
               if q.get("sourceQuestionId") == question["_id"]]}} for s in surveys]
    answers = [{"$unwind": "$answers"}, {"$match": {"$or": pairs} if pairs else {"_id": {"$exists": False}}}]
    facets = {
        "submissions": [{"$count": "count"}],
        "summary": [*answers, {"$group": {"_id": None, "count": {"$sum": 1},
            "average": {"$avg": {"$toDecimal": "$answers.value"} if question["type"] == "number" else "$answers.value"},
            "minimum": {"$min": "$answers.value"}, "maximum": {"$max": "$answers.value"}}}],
        "answeredSubmissions": [*answers, {"$group": {"_id": "$_id"}}, {"$count": "count"}],
        "bySurvey": [*answers, {"$group": {"_id": "$surveyId", "count": {"$sum": 1}}}],
        "submissionsBySurvey": [{"$group": {"_id": "$surveyId", "count": {"$sum": 1}}}],
    }
    if question["type"] in {"single", "multiple"}:
        facets["options"] = [*answers, {"$unwind": "$answers.selectedOptionIds"},
                             {"$group": {"_id": "$answers.selectedOptionIds", "count": {"$sum": 1}}}]
    elif question["type"] == "number":
        facets["distribution"] = [*answers, bucket_stage(bucket_size), {"$sort": {"_id": 1}}, {"$limit": 101}]
    else:
        facets["texts"] = [*answers, {"$group": {"_id": "$answers.value", "count": {"$sum": 1}}},
                           {"$sort": {"count": -1, "_id": 1}}, {"$limit": 21}]
    result = next(database.responses.aggregate([{"$match": response_query}, {"$facet": facets}]))
    summary = next(iter(result["summary"]), {})
    count = summary.get("count", 0)
    option_counts = {row["_id"]: row["count"] for row in result.get("options", [])}
    distribution = []
    for row in result.get("distribution", [])[:100]:
        index = row["_id"].to_decimal() if isinstance(row["_id"], Decimal128) else Decimal(str(row["_id"]))
        with localcontext() as ctx:
            ctx.prec = 650
            lower = index * Decimal(str(bucket_size)); upper = lower + Decimal(str(bucket_size))
            low, high = decimal_label(lower), decimal_label(upper)
        distribution.append({"lower": low, "upper": high, "label": f"{low} ≤ x < {high}", "count": row["count"]})
    answers_by_survey = {row["_id"]: row["count"] for row in result["bySurvey"]}
    submissions_by_survey = {row["_id"]: row["count"] for row in result["submissionsBySurvey"]}
    texts = [{"value": row["_id"], "count": row["count"]} for row in result.get("texts", [])[:20]]
    numeric = question["type"] == "number"
    return {"questionVersionId": str(question["_id"]), "rootQuestionId": str(question["rootQuestionId"]),
        "version": question["version"], "title": question["title"], "type": question["type"],
        "scope": "owned_surveys_only", "surveyVersionCount": len(surveys),
        "surveySeriesCount": len({s.get("rootSurveyId", s["_id"]) for s in surveys}),
        "instanceCount": sum(len(pair["answers.questionId"]["$in"]) for pair in pairs),
        "submissionCount": next(iter(result["submissions"]), {}).get("count", 0),
        "answeredSubmissionCount": next(iter(result["answeredSubmissions"]), {}).get("count", 0), "answerCount": count,
        "average": float(summary["average"].to_decimal()) if numeric and summary.get("average") is not None else None,
        "minimum": summary.get("minimum") if numeric else None, "maximum": summary.get("maximum") if numeric else None,
        "bucketSize": bucket_size if numeric else None, "distribution": distribution,
        "distributionTruncated": len(result.get("distribution", [])) > 100,
        "options": [{"optionId": str(option["optionId"]), "text": option["text"],
                     "count": option_counts.get(option["optionId"], 0)} for option in question.get("options", [])],
        "textFrequencies": texts, "otherTextAnswerCount": count - sum(row["count"] for row in texts) if question["type"] == "text" else 0,
        "surveys": [{"surveyId": str(s["_id"]), "title": s["title"], "version": s["version"], "status": s["status"],
            "instanceCount": sum(q.get("sourceQuestionId") == question["_id"] for q in s["questions"]),
            "submissionCount": submissions_by_survey.get(s["_id"], 0), "answerCount": answers_by_survey.get(s["_id"], 0)}
            for s in sorted(surveys, key=lambda s: str(s["_id"]), reverse=True)]}
