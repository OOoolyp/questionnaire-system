"""可配置跳转及创建者预览，不保存答卷。"""

import operator
from typing import Annotated, Literal

from bson import ObjectId
from fastapi import HTTPException
from pydantic import Field

from app.surveys.questions import Identifier, Number, StrictModel


class RuleBase(StrictModel):
    targetQuestionId: Identifier | None = Field(description="后面的题目ID；null表示结束")


class SelectedRule(RuleBase):
    operator: Literal["selected"]
    value: Identifier


class ExactlyRule(RuleBase):
    operator: Literal["exactly"]
    value: list[Identifier] = Field(min_length=1)


class NumericRule(RuleBase):
    operator: Literal["<", "<=", "=", ">=", ">"]
    value: Number


JumpRule = Annotated[SelectedRule | ExactlyRule | NumericRule, Field(discriminator="operator")]


class JumpRulesInput(StrictModel):
    rules: list[JumpRule] = Field(description="依次匹配，首条命中生效；空数组清空规则")


class PreviewAnswer(StrictModel):
    selectedOptionIds: list[Identifier] | None = None
    value: str | Number | None = None


class PreviewRead(StrictModel):
    questionId: str
    nextQuestionId: str | None
    ended: bool
    reason: Literal["matched_rule", "sequential"]
    matchedRuleIndex: int | None = Field(description="从0开始的规则下标；未匹配为null")


def validate_rules(questions, code=422):
    by_id = {q["questionId"]: q for q in questions}
    for question in questions:
        option_ids = {o["optionId"] for o in question.get("options", [])}
        for rule in question.get("jumpRules", []):
            kind, op, value = question["type"], rule["operator"], rule["value"]
            allowed = {"single": {"selected"}, "multiple": {"exactly"},
                       "number": {"<", "<=", "=", ">=", ">"}, "text": set()}
            if op not in allowed[kind]:
                raise HTTPException(code, "跳转判断符与题型不匹配，请先清空或修正规则")
            if kind in {"single", "multiple"}:
                ids = [value] if kind == "single" else value
                if not ids or len(ids) != len(set(ids)) or not set(ids) <= option_ids:
                    raise HTTPException(code, "跳转规则引用的选项必须属于本题且不能重复")
                if kind == "multiple":
                    limits = question["validation"]
                    if len(ids) < limits.get("minChoices", 0) or len(ids) > limits.get("maxChoices", len(option_ids)):
                        raise HTTPException(code, "跳转条件的选项数量不符合本题校验规则")
            target = rule["targetQuestionId"]
            if target is not None:
                if target not in by_id:
                    raise HTTPException(code, "跳转目标题目不存在或不属于本问卷")
                if by_id[target]["order"] <= question["order"]:
                    raise HTTPException(code, "只能跳转到后面的题目或结束问卷")


def load_question(database, survey_id, question_id, user_id):
    if not ObjectId.is_valid(survey_id) or not ObjectId.is_valid(question_id):
        raise HTTPException(400, "问卷ID和题目ID格式错误")
    survey = database.surveys.find_one({"_id": ObjectId(survey_id), "creatorId": user_id})
    if survey is None:
        raise HTTPException(404, "问卷不存在")
    if survey["status"] != "draft":
        raise HTTPException(409, "当前接口仅用于草稿配置和预览")
    question = next((q for q in survey["questions"] if q["questionId"] == ObjectId(question_id)), None)
    if question is None:
        raise HTTPException(404, "题目不存在")
    return survey, question


def set_rules(database, survey_id, question_id, user_id, payload):
    survey, question = load_question(database, survey_id, question_id, user_id)
    rules = []
    for item in payload.rules:
        rule = item.model_dump()
        target = rule["targetQuestionId"]
        rule["targetQuestionId"] = ObjectId(target) if target else None
        if item.operator == "selected":
            rule["value"] = ObjectId(rule["value"])
        elif item.operator == "exactly":
            rule["value"] = [ObjectId(v) for v in rule["value"]]
        rules.append(rule)
    updated = {**question, "jumpRules": rules}
    questions = [updated if q["questionId"] == question["questionId"] else q for q in survey["questions"]]
    validate_rules(questions)
    result = database.surveys.update_one(
        {"_id": survey["_id"], "creatorId": user_id, "status": "draft", "questions": survey["questions"]},
        {"$set": {"questions": questions}},
    )
    if not result.matched_count:
        raise HTTPException(409, "问卷已被其他请求修改，请重新查询后再试")
    return updated


def validate_answer(question, answer):
    kind, limits = question["type"], question["validation"]
    if kind in {"single", "multiple"}:
        if "value" in answer.model_fields_set:
            raise HTTPException(422, "选择题请使用selectedOptionIds，不要提供value")
        values = [ObjectId(v) for v in (answer.selectedOptionIds or [])]
        options = {o["optionId"] for o in question["options"]}
        if len(values) != len(set(values)) or not set(values) <= options:
            raise HTTPException(422, "答案选项必须属于本题且不能重复")
        if not values:
            if question["required"]:
                raise HTTPException(422, "本题必答")
            return None
        if kind == "single" and len(values) != 1:
            raise HTTPException(422, "单选题只能选择一项")
        if kind == "multiple" and not limits.get("minChoices", 0) <= len(values) <= limits.get("maxChoices", len(options)):
            raise HTTPException(422, "选择数量不符合限制")
        return set(values)
    if "selectedOptionIds" in answer.model_fields_set:
        raise HTTPException(422, "填空题请使用value，不要提供selectedOptionIds")
    value = answer.value
    if value is None or (isinstance(value, str) and not value.strip()):
        if question["required"]:
            raise HTTPException(422, "本题必答")
        return None
    if kind == "text":
        if not isinstance(value, str):
            raise HTTPException(422, "文本题答案必须是字符串")
        if len(value) < limits.get("minLength", 0) or ("maxLength" in limits and len(value) > limits["maxLength"]):
            raise HTTPException(422, "文本长度不符合限制")
    else:
        if isinstance(value, str):
            raise HTTPException(422, "数字题答案必须是数字")
        if limits.get("integerOnly") and value != int(value):
            raise HTTPException(422, "必须填写整数")
        if ("minValue" in limits and value < limits["minValue"]) or ("maxValue" in limits and value > limits["maxValue"]):
            raise HTTPException(422, "数字不在允许范围内")
    return value


def preview(database, survey_id, question_id, user_id, answer):
    survey, question = load_question(database, survey_id, question_id, user_id)
    validate_rules(survey["questions"], code=409)
    value = validate_answer(question, answer)
    return next_question(survey["questions"], question, value)


def next_question(questions, question, value):
    question_id = str(question["questionId"])
    comparisons = {"<": operator.lt, "<=": operator.le, "=": operator.eq,
                   ">=": operator.ge, ">": operator.gt}
    if value is not None:
        for index, rule in enumerate(question["jumpRules"]):
            op = rule["operator"]
            if op == "selected":
                matched = rule["value"] in value
            elif op == "exactly":
                matched = set(rule["value"]) == value
            else:
                matched = comparisons[op](value, rule["value"])
            if matched:
                return result(question_id, rule["targetQuestionId"], "matched_rule", index)
    remaining = sorted((q for q in questions if q["order"] > question["order"]), key=lambda q: q["order"])
    return result(question_id, remaining[0]["questionId"] if remaining else None, "sequential", None)


def result(question_id, target, reason, index):
    return {"questionId": question_id, "nextQuestionId": str(target) if target else None,
            "ended": target is None, "reason": reason, "matchedRuleIndex": index}
