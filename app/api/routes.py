"""现有 HTTP 接口。新增业务可在所属业务包定义路由后集中注册。"""
from datetime import datetime, timezone
from secrets import token_urlsafe

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse
from fastapi.encoders import jsonable_encoder
from pymongo.errors import DuplicateKeyError

from app.surveys.schemas import SurveyCreate, SurveyUpdate, SurveyRead
from app.auth.schemas import TokenRead, UserRead, UserRegister
from app.surveys.questions import QUESTION_EXAMPLES, QuestionInput, QuestionRead, edit_question, insert_question_before
from app.surveys.jumps import JumpRulesInput, PreviewAnswer, PreviewRead, preview, set_rules, next_question, validate_answer
from app.surveys.submissions import (
    FillStep, FillSurveyRead, PublishInput, ResponseRead, SubmissionInput,
    SubmissionReceipt, available, close, creator_response, owned, publish, receipt, submit,
)
from app.surveys.statistics import (
    AnswerPage, QuestionStatistics, SurveyStatistics, answer_contents,
    question_statistics, survey_statistics,
)
from app.auth.security import (
    TOKEN_SECONDS, current_user, dummy_hash, issue_token, password_hash,
)

router = APIRouter()


@router.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/ui/")


@router.get("/health", tags=["运行检查"], summary="检查数据库连接")
def health(request: Request):
    request.app.state.database.command("ping")
    return {"status": "ok", "database": "connected"}


def serialize_survey(document: dict) -> dict:
    result = {"id": str(document["_id"]), **{
        key: value for key, value in document.items() if key != "_id"
    }}
    result["creatorId"] = str(document["creatorId"])
    return jsonable_encoder(result, custom_encoder={ObjectId: str})


def serialize_user(document: dict) -> dict:
    return {
        "id": str(document["_id"]),
        "username": document["username"],
        "createdAt": document["createdAt"],
    }


@router.post("/auth/register", response_model=UserRead, status_code=201,
          tags=["账号"], summary="注册账号")
def register(payload: UserRegister, request: Request):
    document = {
        "username": payload.username,
        "passwordHash": password_hash.hash(payload.password),
        "createdAt": datetime.now(timezone.utc),
    }
    try:
        result = request.app.state.database.users.insert_one(document)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="用户名已存在")
    saved = request.app.state.database.users.find_one({"_id": result.inserted_id})
    return serialize_user(saved)


@router.post("/auth/token", response_model=TokenRead, tags=["账号"], summary="登录并获取访问令牌")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends()):
    user = request.app.state.database.users.find_one({"username": form.username.strip()})
    valid = password_hash.verify(form.password, user["passwordHash"] if user else dummy_hash)
    if not valid or user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误",
                            headers={"WWW-Authenticate": "Bearer"})
    return {"access_token": issue_token(str(user["_id"]), request.app.state.jwt_secret),
            "token_type": "bearer", "expires_in": TOKEN_SECONDS}


@router.get("/auth/me", response_model=UserRead, tags=["账号"], summary="查看当前登录用户")
def me(user: dict = Depends(current_user)):
    return serialize_user(user)


@router.post(
    "/surveys",
    response_model=SurveyRead,
    status_code=status.HTTP_201_CREATED,
    tags=["问卷"],
    summary="创建问卷草稿",
)
def create_survey(payload: SurveyCreate, request: Request, user: dict = Depends(current_user)):
    identifier = ObjectId()
    document = {
        **payload.model_dump(),
        "_id": identifier,
        "rootSurveyId": identifier,
        "parentSurveyId": None,
        "version": 1,
        "creatorId": user["_id"],
        "createdAt": datetime.now(timezone.utc),
        "status": "draft",
        "deadline": None,
        "shareToken": token_urlsafe(18),
        "questions": [],
    }
    result = request.app.state.database.surveys.insert_one(document)
    saved = request.app.state.database.surveys.find_one({"_id": result.inserted_id})
    return serialize_survey(saved)


@router.get("/surveys", response_model=list[SurveyRead], tags=["问卷"], summary="查看我的问卷列表")
def list_surveys(request: Request, user: dict = Depends(current_user),
                 skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    documents = (request.app.state.database.surveys.find({"creatorId": user["_id"]})
                 .sort([("createdAt", -1), ("_id", -1)]).skip(skip).limit(limit))
    return [serialize_survey(document) for document in documents]


@router.patch("/surveys/{survey_id}", response_model=SurveyRead,
           tags=["问卷"], summary="修改草稿基本信息（仅创建者）")
def update_survey(survey_id: str, request: Request, payload: SurveyUpdate,
                  user: dict = Depends(current_user)):
    survey = owned(request.app.state.database, survey_id, user["_id"])
    if survey["status"] != "draft":
        raise HTTPException(409, "只有草稿问卷可以修改基本信息")
    changes = payload.model_dump(exclude_unset=True)
    result = request.app.state.database.surveys.update_one(
        {"_id": survey["_id"], "creatorId": user["_id"], "status": "draft",
         **{field: survey[field] for field in changes}},
        {"$set": changes},
    )
    if not result.matched_count:
        raise HTTPException(409, "问卷已被其他请求修改或发布，请刷新后重试")
    return serialize_survey(request.app.state.database.surveys.find_one({"_id": survey["_id"]}))


@router.get(
    "/surveys/{survey_id}",
    response_model=SurveyRead,
    tags=["问卷"],
    summary="根据ID查询问卷",
    responses={400: {"description": "ID格式错误"}, 404: {"description": "问卷不存在"}},
)
def get_survey(survey_id: str, request: Request, user: dict = Depends(current_user)):
    if not ObjectId.is_valid(survey_id):
        raise HTTPException(status_code=400, detail="问卷ID必须是24位十六进制字符串")
    document = request.app.state.database.surveys.find_one(
        {"_id": ObjectId(survey_id), "creatorId": user["_id"]}
    )
    if document is None:
        raise HTTPException(status_code=404, detail="问卷不存在")
    return serialize_survey(document)


@router.post("/surveys/{survey_id}/questions", response_model=QuestionRead,
          response_model_exclude_none=True, status_code=201, tags=["题目"], summary="添加题目")
def add_question(survey_id: str, request: Request,
                 payload: QuestionInput = Body(openapi_examples=QUESTION_EXAMPLES),
                 user: dict = Depends(current_user)):
    question = edit_question(request.app.state.database, survey_id, user["_id"], payload)
    return jsonable_encoder(question, custom_encoder={ObjectId: str})


@router.post("/surveys/{survey_id}/questions/{before_question_id}/insert", response_model=QuestionRead,
          response_model_exclude_none=True, status_code=201, tags=["题目"], summary="在指定题目前插入，后续题序自动顺移")
def insert_question(survey_id: str, before_question_id: str, request: Request,
                    payload: QuestionInput, user: dict = Depends(current_user)):
    return jsonable_encoder(
        insert_question_before(request.app.state.database, survey_id, before_question_id, user["_id"], payload),
        custom_encoder={ObjectId: str},
    )


@router.put("/surveys/{survey_id}/questions/{question_id}", response_model=QuestionRead,
         response_model_exclude_none=True, tags=["题目"], summary="完整替换一道题（保留题目ID）")
def replace_question(survey_id: str, question_id: str, request: Request,
                     payload: QuestionInput = Body(openapi_examples=QUESTION_EXAMPLES),
                     user: dict = Depends(current_user)):
    question = edit_question(request.app.state.database, survey_id, user["_id"], payload, question_id)
    return jsonable_encoder(question, custom_encoder={ObjectId: str})


@router.delete("/surveys/{survey_id}/questions/{question_id}", status_code=204,
            tags=["题目"], summary="删除一道题")
def delete_question(survey_id: str, question_id: str, request: Request,
                    user: dict = Depends(current_user)):
    edit_question(request.app.state.database, survey_id, user["_id"], question_id=question_id, delete=True)


@router.put("/surveys/{survey_id}/questions/{question_id}/jump-rules", response_model=QuestionRead,
         response_model_exclude_none=True, tags=["跳转"], summary="替换跳转规则（空数组清空）")
def configure_jump_rules(survey_id: str, question_id: str, request: Request,
                         payload: JumpRulesInput = Body(openapi_examples={
                             "single": {"summary": "单选（替换示例中的选项和目标题目ID）", "value": {"rules": [
                                 {"operator": "selected", "value": "000000000000000000000001", "targetQuestionId": "000000000000000000000002"}]}},
                             "multiple": {"summary": "多选完全匹配（替换选项ID）", "value": {"rules": [
                                 {"operator": "exactly", "value": ["000000000000000000000001", "000000000000000000000002"], "targetQuestionId": None}]}},
                             "number": {"summary": "数字小于18则结束", "value": {"rules": [
                                 {"operator": "<", "value": 18, "targetQuestionId": None}]}},
                             "clear": {"summary": "清空规则", "value": {"rules": []}},
                         }),
                         user: dict = Depends(current_user)):
    return jsonable_encoder(set_rules(request.app.state.database, survey_id, question_id, user["_id"], payload),
                            custom_encoder={ObjectId: str})


@router.post("/surveys/{survey_id}/questions/{question_id}/preview", response_model=PreviewRead,
          tags=["跳转"], summary="校验当前答案并预览下一题（不保存答卷）")
def preview_next_question(survey_id: str, question_id: str, request: Request,
                          payload: PreviewAnswer = Body(openapi_examples={
                              "choice": {"summary": "选择题（替换选项ID）", "value": {"selectedOptionIds": ["000000000000000000000001"]}},
                              "number": {"summary": "数字答案", "value": {"value": 17}},
                              "text": {"summary": "文本答案", "value": {"value": "这是一条建议"}},
                              "skip": {"summary": "不回答非必答题", "value": {}},
                          }), user: dict = Depends(current_user)):
    return preview(request.app.state.database, survey_id, question_id, user["_id"], payload)


@router.post("/surveys/{survey_id}/publish", response_model=SurveyRead,
          tags=["发布管理"], summary="发布草稿并设置截止时间")
def publish_survey(survey_id: str, request: Request, payload: PublishInput,
                   user: dict = Depends(current_user)):
    return serialize_survey(publish(request.app.state.database, survey_id, user["_id"], payload))


@router.post("/surveys/{survey_id}/close", response_model=SurveyRead,
          tags=["发布管理"], summary="关闭已发布问卷")
def close_survey(survey_id: str, request: Request, user: dict = Depends(current_user)):
    return serialize_survey(close(request.app.state.database, survey_id, user["_id"]))


@router.get("/survey/{share_token}", response_model=FillSurveyRead,
         response_model_exclude_none=True, tags=["填写"], summary="通过分享标识获取可填写问卷")
def get_fill_survey(share_token: str, request: Request, user: dict = Depends(current_user)):
    survey = available(request.app.state.database, share_token)
    content = {key: survey[key] for key in ["title", "description", "deadline", "allowAnonymous", "allowRepeat", "questions"]}
    return jsonable_encoder({"id": str(survey["_id"]), **content}, custom_encoder={ObjectId: str})


@router.post("/survey/{share_token}/next", response_model=PreviewRead,
          tags=["填写"], summary="检查当前答案并获取下一题（不保存）")
def fill_next(share_token: str, request: Request, payload: FillStep,
              user: dict = Depends(current_user)):
    survey = available(request.app.state.database, share_token)
    question = next((q for q in survey["questions"] if q["questionId"] == ObjectId(payload.questionId)), None)
    if question is None:
        raise HTTPException(422, "题目不属于本问卷")
    answer = PreviewAnswer.model_validate(payload.model_dump(exclude={"questionId"}, exclude_unset=True))
    value = validate_answer(question, answer)
    return next_question(survey["questions"], question, value)


@router.post("/survey/{share_token}/responses", response_model=SubmissionReceipt, status_code=201,
          tags=["填写"], summary="提交完整答卷并保存到MongoDB")
def submit_response(share_token: str, request: Request, payload: SubmissionInput,
                    user: dict = Depends(current_user)):
    return receipt(submit(request.app.state.database, share_token, user["_id"], payload))


@router.get("/surveys/{survey_id}/responses", response_model=list[ResponseRead],
         response_model_exclude_none=True, tags=["答卷"], summary="创建者查看答卷（匿名身份隐藏）")
def list_responses(survey_id: str, request: Request, user: dict = Depends(current_user),
                   skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    survey = owned(request.app.state.database, survey_id, user["_id"])
    documents = (request.app.state.database.responses.find({"surveyId": survey["_id"]})
                 .sort([("submittedAt", -1), ("_id", -1)]).skip(skip).limit(limit))
    return jsonable_encoder([creator_response(doc) for doc in documents], custom_encoder={ObjectId: str})


@router.get("/surveys/{survey_id}/statistics", response_model=SurveyStatistics,
         tags=["统计"], summary="创建者查看整份问卷统计")
def get_survey_statistics(survey_id: str, request: Request, user: dict = Depends(current_user)):
    return survey_statistics(request.app.state.database, survey_id, user["_id"])


@router.get("/surveys/{survey_id}/questions/{question_id}/statistics", response_model=QuestionStatistics,
         tags=["统计"], summary="创建者查看单题统计")
def get_question_statistics(survey_id: str, question_id: str, request: Request,
                            user: dict = Depends(current_user)):
    return question_statistics(request.app.state.database, survey_id, question_id, user["_id"])


@router.get("/surveys/{survey_id}/questions/{question_id}/answers", response_model=AnswerPage,
         tags=["统计"], summary="分页查看填空内容（不含填写者身份）")
def get_answer_contents(survey_id: str, question_id: str, request: Request,
                        user: dict = Depends(current_user),
                        skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    return answer_contents(request.app.state.database, survey_id, question_id, user["_id"], skip, limit)


