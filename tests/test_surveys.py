"""作业第一阶段后端验收：真实MongoDB、隔离测试库，不依赖前端或已运行的服务。

运行：conda activate base 后执行 python -m unittest discover -s tests -v。
每个test方法下的中文说明给出测试场景、操作步骤及预期结果。
HTTP状态码：201创建成功、200成功、204删除成功、400格式错误、401未登录、
404不存在/无访问权、409状态或唯一性冲突、422内容校验失败。
"""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from bson import ObjectId
from fastapi.testclient import TestClient
import jwt
from pymongo import MongoClient

from app.main import app, prepare_database


class SurveyIntegrationTests(unittest.TestCase):
    """所有测试使用随机命名的独立数据库；结束后仅清理本轮创建的数据。"""
    def new_survey(self):
        response = self.client.post("/surveys", json={"title": "题目编辑测试"})
        self.assertEqual(response.status_code, 201)
        identifier = response.json()["id"]
        self.created_ids.append(ObjectId(identifier))
        return identifier

    def choice_payload(self, order=1, kind="single"):
        return {"type": kind, "title": "喜欢什么水果？", "order": order,
                "required": True, "options": [{"text": "苹果", "order": 1},
                                              {"text": "香蕉", "order": 2}]}

    def jump_fixture(self, kind="single"):
        survey = self.new_survey()
        path = f"/surveys/{survey}/questions"
        payload = self.choice_payload(kind=kind) if kind in {"single", "multiple"} else {
            "type": kind, "title": "测试", "order": 1, "required": True,
            "validation": {"minValue": 0, "maxValue": 120, "integerOnly": True} if kind == "number" else {},
        }
        source = self.client.post(path, json=payload).json()
        targets = [self.client.post(path, json={"type": "text", "title": "后续题", "order": order}).json()
                   for order in [2, 3]]
        return survey, source, targets, f"{path}/{source['questionId']}"

    def test_jump_single_first_match_fallback_and_clear(self):
        """场景：单选规则优先级、未命中及清空。
        步骤：配置两条相同条件，分别输入命中/未命中答案，再清空规则。
        预期：首条规则生效；未命中或清空后按顺序进入下一题。
        """
        survey, source, targets, path = self.jump_fixture()
        option = source["options"][0]["optionId"]
        rules = [{"operator": "selected", "value": option, "targetQuestionId": targets[1]["questionId"]},
                 {"operator": "selected", "value": option, "targetQuestionId": None}]
        response = self.client.put(path + "/jump-rules", json={"rules": rules})
        self.assertEqual(response.status_code, 200, response.text)
        preview = self.client.post(path + "/preview", json={"selectedOptionIds": [option]}).json()
        self.assertEqual(preview["nextQuestionId"], targets[1]["questionId"])
        self.assertEqual(preview["matchedRuleIndex"], 0)
        fallback = self.client.post(path + "/preview", json={"selectedOptionIds": [source["options"][1]["optionId"]]}).json()
        self.assertEqual(fallback["nextQuestionId"], targets[0]["questionId"])
        self.assertEqual(fallback["reason"], "sequential")
        self.assertEqual(self.client.put(path + "/jump-rules", json={"rules": []}).status_code, 200)
        self.assertEqual(self.client.post(path + "/preview", json={"selectedOptionIds": [option]}).json()["reason"], "sequential")

    def test_jump_multiple_exact_set_and_numeric_comparisons(self):
        """场景：多选集合相等与数字比较边界。
        步骤：交换选项顺序、少选一项，逐一配置五种数字比较符。
        预期：集合顺序不影响命中，子集不命中；数字在边界按比较符跳转。
        """
        _, source, targets, path = self.jump_fixture("multiple")
        ids = [o["optionId"] for o in source["options"]]
        response = self.client.put(path + "/jump-rules", json={"rules": [
            {"operator": "exactly", "value": ids, "targetQuestionId": None}]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(self.client.post(path + "/preview", json={"selectedOptionIds": ids[::-1]}).json()["ended"])
        self.assertEqual(self.client.post(path + "/preview", json={"selectedOptionIds": ids[:1]}).json()["nextQuestionId"], targets[0]["questionId"])
        _, _, targets, path = self.jump_fixture("number")
        for op, value, matched in [("<", 17, True), ("<", 18, False), ("<=", 18, True),
                                   ("=", 18, True), (">=", 18, True), (">", 19, True), (">", 18, False)]:
            with self.subTest(op=op, value=value):
                self.assertEqual(self.client.put(path + "/jump-rules", json={"rules": [
                    {"operator": op, "value": 18, "targetQuestionId": None}]}).status_code, 200)
                result = self.client.post(path + "/preview", json={"value": value}).json()
                self.assertEqual(result["ended"], matched)

    def test_jump_rule_validation_and_access(self):
        """场景：非法跳转配置与身份检查。
        步骤：提交错误题型规则、外来选项、自跳转和未知目标，再切换身份。
        预期：非法配置422、他人404、未登录401；合法引用以ObjectId保存。
        """
        _, source, targets, path = self.jump_fixture()
        option = source["options"][0]["optionId"]
        valid = {"operator": "selected", "value": option, "targetQuestionId": targets[1]["questionId"]}
        for rule in [{**valid, "operator": "exactly", "value": [option]},
                     {**valid, "value": str(ObjectId())},
                     {**valid, "targetQuestionId": source["questionId"]},
                     {**valid, "targetQuestionId": str(ObjectId())}]:
            self.assertEqual(self.client.put(path + "/jump-rules", json={"rules": [rule]}).status_code, 422)
        for headers, code in [(self.bob_headers, 404), ({"Authorization": ""}, 401)]:
            self.assertEqual(self.client.put(path + "/jump-rules", json={"rules": [valid]}, headers=headers).status_code, code)
            self.assertEqual(self.client.post(path + "/preview", json={"selectedOptionIds": [option]}, headers=headers).status_code, code)
        self.assertEqual(self.client.put(path + "/jump-rules", json={"rules": [valid]}).status_code, 200)
        # 规则真正保存在MongoDB中，引用仍为ObjectId。
        stored = self.collection.find_one({"questions.questionId": ObjectId(source["questionId"])})
        self.assertIsInstance(stored["questions"][0]["jumpRules"][0]["value"], ObjectId)

    def test_jump_reference_protection_on_question_edit(self):
        """场景：编辑不能破坏跳转引用。
        步骤：删除目标、重建条件选项、改变题型/顺序，再保留ID修改题干。
        预期：破坏引用返回409；合法编辑保留规则；清空引用后可删除目标。
        """
        survey, source, targets, path = self.jump_fixture()
        rule = {"operator": "selected", "value": source["options"][0]["optionId"], "targetQuestionId": targets[1]["questionId"]}
        self.client.put(path + "/jump-rules", json={"rules": [rule]})
        target_path = f"/surveys/{survey}/questions/{targets[1]['questionId']}"
        self.assertEqual(self.client.delete(target_path).status_code, 409)
        self.assertEqual(self.client.put(target_path, json={"type": "text", "title": "移动", "order": 0}).status_code, 422)
        self.assertEqual(self.client.put(path, json=self.choice_payload()).status_code, 409)
        self.assertEqual(self.client.put(path, json={"type": "number", "title": "年龄", "order": 1}).status_code, 409)
        payload = self.choice_payload()
        payload["options"] = source["options"]
        payload["title"] = "修改题干但保留规则"
        self.assertEqual(self.client.put(path, json=payload).status_code, 200)
        self.assertEqual(self.client.put(path, json={**payload, "order": 4}).status_code, 409)
        self.client.put(path + "/jump-rules", json={"rules": []})
        self.assertEqual(self.client.delete(target_path).status_code, 204)

    def test_preview_answer_validation_and_no_writes(self):
        """场景：预览先校验答案且不保存。
        步骤：输入缺答、错误类型、越界数值、非整数和非法选择项。
        预期：非法答案422，合法0正常；预览前后问卷不变，末题后结束。
        """
        survey, source, targets, path = self.jump_fixture("number")
        before = self.collection.find_one({"_id": ObjectId(survey)})
        for answer in [{}, {"value": "18"}, {"value": True}, {"value": 121}, {"value": 1.5}, {"selectedOptionIds": []}]:
            self.assertEqual(self.client.post(path + "/preview", json=answer).status_code, 422)
        self.assertEqual(self.client.post(path + "/preview", json={"value": 0}).status_code, 200)
        self.assertEqual(self.collection.find_one({"_id": ObjectId(survey)}), before)
        _, source, _, path = self.jump_fixture("single")
        ids = [o["optionId"] for o in source["options"]]
        for answer in [{}, {"selectedOptionIds": ids}, {"selectedOptionIds": [ids[0], ids[0]]},
                       {"selectedOptionIds": [str(ObjectId())]}]:
            self.assertEqual(self.client.post(path + "/preview", json=answer).status_code, 422)
        last_path = f"/surveys/{survey}/questions/{targets[-1]['questionId']}/preview"
        self.assertTrue(self.client.post(last_path, json={}).json()["ended"])

    @classmethod
    def setUpClass(cls):
        # 准备：单独创建随机测试数据库和alice/bob账号，不使用业务库里的用户。
        cls.previous_database = os.environ.get("MONGODB_DATABASE")
        os.environ["MONGODB_DATABASE"] = "questionnaire_test_" + uuid4().hex
        cls.context = TestClient(app)
        try:
            cls.client = cls.context.__enter__()
        except Exception:
            cls.restore_environment()
            raise
        cls.collection = app.state.database.surveys
        cls.created_ids = []
        cls.user_ids = []
        cls.accounts = {}
        for name in ["alice", "bob"]:
            response = cls.client.post("/auth/register", json={"username": name, "password": "test-password-123"})
            assert response.status_code == 201, response.text
            cls.accounts[name] = response.json()
            cls.user_ids.append(ObjectId(response.json()["id"]))
        response = cls.client.post("/auth/token", data={"username": "alice", "password": "test-password-123"})
        assert response.status_code == 200, response.text
        cls.alice_token = response.json()["access_token"]
        cls.client.headers["Authorization"] = "Bearer " + cls.alice_token
        response = cls.client.post("/auth/token", data={"username": "bob", "password": "test-password-123"})
        cls.bob_headers = {"Authorization": "Bearer " + response.json()["access_token"]}

    @classmethod
    def restore_environment(cls):
        if cls.previous_database is None:
            os.environ.pop("MONGODB_DATABASE", None)
        else:
            os.environ["MONGODB_DATABASE"] = cls.previous_database

    @classmethod
    def tearDownClass(cls):
        # 清理：先答卷、再问卷和用户，仅删除本轮记录；保留业务库与已有文件。
        try:
            if cls.created_ids:
                app.state.database.responses.delete_many({"surveyId": {"$in": cls.created_ids}})
                cls.collection.delete_many({"_id": {"$in": cls.created_ids}})
            app.state.database.users.delete_many({"_id": {"$in": cls.user_ids}})
        finally:
            cls.context.__exit__(None, None, None)
            cls.restore_environment()

    def test_health_and_documentation(self):
        """场景：运行检查和可视化调试入口。
        步骤：请求health、docs、openapi.json。
        预期：MongoDB已连接，Swagger及接口结构可正常访问。
        """
        self.assertEqual(self.client.get("/health").json()["database"], "connected")
        self.assertEqual(self.client.get("/docs").status_code, 200)
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)
        # 正式前端入口由同一FastAPI服务提供，Swagger继续保留。
        self.assertEqual(self.client.get("/", follow_redirects=False).headers["location"], "/ui/")
        self.assertEqual(self.client.get("/ui/").status_code, 200)
        self.assertEqual(self.client.get("/ui/app.js").status_code, 200)
        self.assertIn("javascript", self.client.get("/ui/logic.mjs").headers["content-type"])

    def test_create_persist_and_read(self):
        """场景：创建问卷并持久化查询。
        步骤：提交带空格标题，直接读取MongoDB，再按返回ID查询接口。
        预期：201创建、标题去首尾空格、创建者正确，查询内容与保存结果一致。
        """
        payload = {"title": "  生活习惯调查  ", "description": "测试问卷"}
        response = self.client.post("/surveys", json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        identifier = ObjectId(data["id"])
        self.created_ids.append(identifier)
        stored = self.collection.find_one({"_id": identifier})
        self.assertEqual(stored["title"], "生活习惯调查")
        self.assertEqual(stored["status"], "draft")
        self.assertEqual(stored["questions"], [])
        self.assertFalse(stored["allowRepeat"])
        self.assertEqual(stored["creatorId"], ObjectId(self.accounts["alice"]["id"]))
        self.assertIn("shareToken", stored)
        self.assertNotIn("accessToken", stored)
        self.assertEqual(self.client.get(f"/surveys/{identifier}").json(), data)

    def test_account_registration_and_login(self):
        """场景：注册登录、密码存储和用户信息。
        步骤：重复注册，使用错误账号密码登录，读取用户记录和当前用户接口。
        预期：重复409、错误登录401、无效注册422；只存Argon2哈希且响应无密码。
        """
        duplicate = self.client.post("/auth/register", json={"username": " alice ", "password": "test-password-123"})
        self.assertEqual(duplicate.status_code, 409)
        for name, password in [("alice", "wrong"), ("missing", "wrong")]:
            self.assertEqual(self.client.post("/auth/token", data={"username": name, "password": password}).status_code, 401)
        user = app.state.database.users.find_one({"username": "alice"})
        self.assertTrue(user["passwordHash"].startswith("$argon2"))
        self.assertNotIn("password", user)
        response = self.client.get("/auth/me")
        self.assertEqual(response.json()["id"], self.accounts["alice"]["id"])
        self.assertNotIn("passwordHash", response.json())
        for payload in [{"username": " ", "password": "12345678"},
                        {"username": "new", "password": "short"}]:
            self.assertEqual(self.client.post("/auth/register", json=payload).status_code, 422)

    def test_ownership_and_legacy_preservation(self):
        """场景：问卷归属、列表隔离及旧无主草稿保留。
        步骤：alice创建，bob查询；插入无主旧草稿并尝试伪造创建者。
        预期：bob不可访问，旧草稿保留但不归属任何账号，伪造字段422且不写入。
        """
        response = self.client.post("/surveys", json={"title": "private"})
        survey_id = response.json()["id"]
        self.created_ids.append(ObjectId(survey_id))
        self.assertEqual(self.client.get(f"/surveys/{survey_id}", headers=self.bob_headers).status_code, 404)
        alice_ids = {item["id"] for item in self.client.get("/surveys").json()}
        self.assertIn(survey_id, alice_ids)
        self.assertEqual(self.client.get("/surveys", headers=self.bob_headers).json(), [])
        legacy_id = self.collection.insert_one({"title": "legacy", "shareToken": uuid4().hex}).inserted_id
        self.created_ids.append(legacy_id)
        self.assertEqual(self.client.get(f"/surveys/{legacy_id}").status_code, 404)
        self.assertIsNotNone(self.collection.find_one({"_id": legacy_id}))
        self.assertNotIn(str(legacy_id), {item["id"] for item in self.client.get("/surveys").json()})
        before = self.collection.count_documents({})
        self.assertEqual(self.client.post("/surveys", json={"title": "spoof", "creatorId": self.accounts["bob"]["id"]}).status_code, 422)
        self.assertEqual(self.collection.count_documents({}), before)

    def test_missing_invalid_expired_tokens(self):
        """场景：缺失、乱码、过期及伪造签名的令牌。
        步骤：分别用四类无效凭证访问身份、列表、详情和创建接口。
        预期：所有请求均返回401，不能绕过登录要求。
        """
        now = datetime.now(timezone.utc)
        expired = jwt.encode({"sub": self.accounts["alice"]["id"], "iat": now - timedelta(hours=2),
                              "exp": now - timedelta(hours=1)}, app.state.jwt_secret, algorithm="HS256")
        forged = jwt.encode({"sub": self.accounts["alice"]["id"], "iat": now,
                             "exp": now + timedelta(hours=1)}, "x" * 48, algorithm="HS256")
        for token in ["", "Bearer garbage", "Bearer " + expired, "Bearer " + forged]:
            headers = {"Authorization": token}
            for path in ["/auth/me", "/surveys", f"/surveys/{ObjectId()}"]:
                self.assertEqual(self.client.get(path, headers=headers).status_code, 401)
            self.assertEqual(self.client.post("/surveys", json={"title": "denied"}, headers=headers).status_code, 401)

    def test_legacy_share_token_migration(self):
        """场景：旧访问标识字段迁移兼容。
        步骤：插入旧accessToken记录，连续执行两次初始化迁移。
        预期：改名shareToken且原值不变，不自动分配创建者，重复迁移不报错。
        """
        self.collection.drop_index("shareToken_1")
        token = uuid4().hex
        legacy_id = self.collection.insert_one({"title": "old draft", "accessToken": token}).inserted_id
        self.created_ids.append(legacy_id)
        self.collection.create_index("accessToken", unique=True, sparse=True)
        prepare_database(app.state.database)
        prepare_database(app.state.database)
        document = self.collection.find_one({"_id": legacy_id})
        self.assertEqual(document["shareToken"], token)
        self.assertNotIn("accessToken", document)
        self.assertNotIn("creatorId", document)

    def test_invalid_input_does_not_write(self):
        """场景：创建问卷的输入校验。
        步骤：提交空标题、缺标题、错误布尔值及尚不允许的字段。
        预期：全部422，数据库问卷数量保持不变。
        """
        before = self.collection.count_documents({})
        for payload in [
            {"title": "   "},
            {},
            {"title": "test", "allowRepeat": "yes"},
            {"title": "test", "questions": []},
        ]:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post("/surveys", json=payload).status_code, 422)
        self.assertEqual(self.collection.count_documents({}), before)

    def test_invalid_and_missing_ids(self):
        """场景：错误ID格式与不存在记录。
        步骤：查询非ObjectId字符串及未使用的合法ObjectId。
        预期：分别返回400、404，不发生服务器异常。
        """
        self.assertEqual(self.client.get("/surveys/not-an-id").status_code, 400)
        self.assertEqual(self.client.get(f"/surveys/{ObjectId()}").status_code, 404)

    def test_questions_all_types_persist_and_sort(self):
        """场景：四种题型配置和嵌入保存。
        步骤：乱序添加单选、多选、文本、数字题，查询接口及数据库。
        预期：按order排序、规则保存正确，内部ID为ObjectId且填空无选项。
        """
        survey_id = self.new_survey()
        path = f"/surveys/{survey_id}/questions"
        payloads = [self.choice_payload(2), self.choice_payload(1, "multiple"),
                    {"type": "text", "title": "建议", "order": 3, "validation": {"minLength": 2, "maxLength": 100}},
                    {"type": "number", "title": "年龄", "order": 4, "validation": {"minValue": 0, "maxValue": 120, "integerOnly": True}}]
        payloads[1]["validation"] = {"minChoices": 1, "maxChoices": 2}
        for payload in payloads:
            response = self.client.post(path, json=payload)
            self.assertEqual(response.status_code, 201, response.text)
            self.assertTrue(ObjectId.is_valid(response.json()["questionId"]))
        survey = self.client.get(f"/surveys/{survey_id}").json()
        self.assertEqual([q["order"] for q in survey["questions"]], [1, 2, 3, 4])
        stored = self.collection.find_one({"_id": ObjectId(survey_id)})
        self.assertIsInstance(stored["questions"][0]["questionId"], ObjectId)
        self.assertIsInstance(stored["questions"][0]["options"][0]["optionId"], ObjectId)
        self.assertNotIn("options", stored["questions"][2])

    def test_question_update_option_ids_type_change_and_delete(self):
        """场景：替换题目、保留ID、改变题型和删除。
        步骤：带回原选项ID修改文字，改为数字题，再删除两次。
        预期：题目/保留选项ID不变，旧选项移除，首次删除204、再次404。
        """
        survey_id = self.new_survey()
        path = f"/surveys/{survey_id}/questions"
        original = self.client.post(path, json=self.choice_payload()).json()
        question_id = original["questionId"]
        payload = self.choice_payload()
        payload["options"] = original["options"]
        payload["options"][0]["text"] = "梨"
        updated = self.client.put(f"{path}/{question_id}", json=payload)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["questionId"], question_id)
        self.assertEqual(updated.json()["options"][0]["optionId"], original["options"][0]["optionId"])
        updated = self.client.put(f"{path}/{question_id}", json={"type": "number", "title": "年龄", "order": 1, "validation": {"integerOnly": True}})
        self.assertEqual(updated.status_code, 200)
        self.assertNotIn("options", updated.json())
        self.assertEqual(updated.json()["questionId"], question_id)
        self.assertEqual(self.client.delete(f"{path}/{question_id}").status_code, 204)
        self.assertEqual(self.client.get(f"/surveys/{survey_id}").json()["questions"], [])
        self.assertEqual(self.client.delete(f"{path}/{question_id}").status_code, 404)

    def test_question_invalid_rules_do_not_write(self):
        """场景：题目配置不合法。
        步骤：提交空题干、重复顺序、过少选项、错配规则和倒置范围等。
        预期：每种非法配置均422，问卷的题目数组仍为空。
        """
        survey_id = self.new_survey()
        path = f"/surveys/{survey_id}/questions"
        invalid = [
            {**self.choice_payload(), "title": " "},
            {**self.choice_payload(), "order": 0},
            {**self.choice_payload(), "options": [{"text": "A", "order": 1}]},
            {**self.choice_payload(), "options": [{"text": "A", "order": 1}, {"text": "B", "order": 1}]},
            {**self.choice_payload(), "validation": {"minChoices": 1}},
            {**self.choice_payload(kind="multiple"), "validation": {"minChoices": 3}},
            {**self.choice_payload(kind="multiple"), "validation": {"minChoices": 2, "maxChoices": 1}},
            {"type": "text", "title": "建议", "order": 1, "validation": {"minLength": 10, "maxLength": 2}},
            {"type": "text", "title": "建议", "order": 1, "validation": {"minValue": 0}},
            {"type": "number", "title": "年龄", "order": 1, "validation": {"minValue": 120, "maxValue": 0}},
            {"type": "number", "title": "年龄", "order": 1, "validation": {"integerOnly": "yes"}},
            {**self.choice_payload(), "jumpRules": []},
            {**self.choice_payload(), "options": [{"text": "A", "order": 1, "optionId": str(ObjectId())}, {"text": "B", "order": 2}]},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                response = self.client.post(path, json=payload)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.get(f"/surveys/{survey_id}").json()["questions"], [])

    def test_question_order_conflicts_and_access_control(self):
        """场景：题序冲突及题目编辑权限/状态。
        步骤：重复题序、切换账号或取消登录，模拟发布后删除。
        预期：冲突409、他人404、未登录401，已发布问卷不可编辑。
        """
        survey_id = self.new_survey()
        path = f"/surveys/{survey_id}/questions"
        payload = self.choice_payload()
        original = self.client.post(path, json=payload).json()
        question_path = f"{path}/{original['questionId']}"
        self.assertEqual(self.client.post(path, json=payload).status_code, 409)
        for headers, code in [(self.bob_headers, 404), ({"Authorization": ""}, 401)]:
            self.assertEqual(self.client.post(path, json=payload, headers=headers).status_code, code)
            self.assertEqual(self.client.put(question_path, json=payload, headers=headers).status_code, code)
            self.assertEqual(self.client.delete(question_path, headers=headers).status_code, code)
        self.assertEqual(self.client.put(f"{path}/{ObjectId()}", json=payload).status_code, 404)
        self.assertEqual(self.client.delete(f"{path}/bad-id").status_code, 400)
        self.collection.update_one({"_id": ObjectId(survey_id)}, {"$set": {"status": "published"}})
        self.assertEqual(self.client.delete(question_path).status_code, 409)

    def published_fixture(self, repeat=False, anonymous=False):
        response = self.client.post("/surveys", json={"title": "发布提交测试", "allowRepeat": repeat, "allowAnonymous": anonymous})
        survey = response.json()
        self.created_ids.append(ObjectId(survey["id"]))
        question = self.client.post(f"/surveys/{survey['id']}/questions", json={
            "type": "number", "title": "年龄", "order": 1, "required": True,
            "validation": {"minValue": 0, "maxValue": 120, "integerOnly": True}}).json()
        response = self.client.post(f"/surveys/{survey['id']}/publish", json={})
        self.assertEqual(response.status_code, 200, response.text)
        payload = {"answers": [{"questionId": question["questionId"], "value": 20}]}
        return survey, question, payload

    def test_publish_fill_submit_and_anonymity(self):
        """场景：发布到匿名提交的完整流程。
        步骤：alice发布，bob读取/回答/匿名提交，alice查看答卷。
        预期：答卷真实保存、身份内部关联但外部隐藏；重复提交及发布后编辑被拒绝。
        """
        survey, question, payload = self.published_fixture(anonymous=True)
        path = f"/survey/{survey['shareToken']}"
        self.assertEqual(self.client.get(path, headers=self.bob_headers).status_code, 200)
        self.assertNotIn("creatorId", self.client.get(path, headers=self.bob_headers).json())
        step = self.client.post(path + "/next", json=payload["answers"][0], headers=self.bob_headers)
        self.assertEqual(step.status_code, 200, step.text)
        self.assertTrue(step.json()["ended"])
        response = self.client.post(path + "/responses", json={**payload, "isAnonymous": True}, headers=self.bob_headers)
        self.assertEqual(response.status_code, 201, response.text)
        saved = app.state.database.responses.find_one({"_id": ObjectId(response.json()["id"])})
        self.assertEqual(saved["respondentId"], ObjectId(self.accounts["bob"]["id"]))
        self.assertEqual(saved["answers"][0]["value"], 20)
        visible = self.client.get(f"/surveys/{survey['id']}/responses").json()
        self.assertNotIn("respondentId", visible[0])
        self.assertEqual(self.client.get(f"/surveys/{survey['id']}/responses", headers=self.bob_headers).status_code, 404)
        self.assertEqual(self.client.post(path + "/responses", json=payload, headers=self.bob_headers).status_code, 409)
        self.assertEqual(self.client.post(f"/surveys/{survey['id']}/questions", json={"type": "text", "title": "x", "order": 2}).status_code, 409)

    def test_submit_repetition_and_parallel_uniqueness(self):
        """场景：重复填写开关及同一用户并发提交。
        步骤：禁止重复时并发4次；另建允许重复问卷，连续提交2次。
        预期：前者1次201、3次409且只存1条；后者2次201且显示非匿名身份。
        """
        survey, _, payload = self.published_fixture()
        path = f"/survey/{survey['shareToken']}/responses"
        with ThreadPoolExecutor(max_workers=4) as executor:
            codes = list(executor.map(lambda _: self.client.post(path, json=payload, headers=self.bob_headers).status_code, range(4)))
        self.assertEqual(sorted(codes), [201, 409, 409, 409])
        self.assertEqual(app.state.database.responses.count_documents({"surveyId": ObjectId(survey["id"])}), 1)
        survey, _, payload = self.published_fixture(repeat=True)
        path = f"/survey/{survey['shareToken']}/responses"
        for _ in range(2):
            self.assertEqual(self.client.post(path, json=payload, headers=self.bob_headers).status_code, 201)
        visible = self.client.get(f"/surveys/{survey['id']}/responses").json()
        self.assertEqual(visible[0]["respondentId"], self.accounts["bob"]["id"])

    def test_publish_status_deadline_and_permission(self):
        """场景：发布/关闭权限、截止及生命周期。
        步骤：发布空问卷、他人发布/关闭、过期提交、关闭后提交或重发。
        预期：依次按内容/权限/状态拒绝；只有创建者能关闭已发布问卷。
        """
        survey_id = self.new_survey()
        self.assertEqual(self.client.post(f"/surveys/{survey_id}/publish", json={}).status_code, 422)
        self.assertEqual(self.client.post(f"/surveys/{survey_id}/publish", json={}, headers=self.bob_headers).status_code, 404)
        survey, _, payload = self.published_fixture()
        path = f"/survey/{survey['shareToken']}"
        self.assertEqual(self.client.post(path + "/responses", json=payload, headers={"Authorization": ""}).status_code, 401)
        self.collection.update_one({"_id": ObjectId(survey["id"])}, {"$set": {"deadline": datetime.now(timezone.utc) - timedelta(seconds=1)}})
        self.assertEqual(self.client.get(path).status_code, 409)
        self.assertEqual(self.client.post(path + "/responses", json=payload).status_code, 409)
        self.collection.update_one({"_id": ObjectId(survey["id"])}, {"$set": {"deadline": None}})
        self.assertEqual(self.client.post(f"/surveys/{survey['id']}/close", headers=self.bob_headers).status_code, 404)
        self.assertEqual(self.client.post(f"/surveys/{survey['id']}/close").status_code, 200)
        self.assertEqual(self.client.post(path + "/responses", json=payload).status_code, 409)
        self.assertEqual(self.client.post(f"/surveys/{survey['id']}/publish", json={}).status_code, 409)

    def test_submission_full_path_skips_required_and_rejects_extras(self):
        """场景：提交必须符合完整答题路径。
        步骤：跳过中间必答题，尝试漏答、重复、外来题、跳过题答案及非法匿名。
        预期：错误提交422且无答卷落库；合法跳过必答题仍可201提交。
        """
        survey, source, targets, path = self.jump_fixture()
        # 中间题改成必答；第1题选择A直接跳到第3题，因此中间必答题无须填写。
        self.client.put(f"/surveys/{survey}/questions/{targets[0]['questionId']}", json={
            "type": "text", "title": "被跳过的必答题", "order": 2, "required": True})
        option = source["options"][0]["optionId"]
        self.client.put(path + "/jump-rules", json={"rules": [{"operator": "selected", "value": option,
                                                            "targetQuestionId": targets[1]["questionId"]}]})
        token = self.client.post(f"/surveys/{survey}/publish", json={}).json()["shareToken"]
        submit_path = f"/survey/{token}/responses"
        answer = {"questionId": source["questionId"], "selectedOptionIds": [option]}
        for payload in [
            {"answers": []}, {"answers": [answer, answer]},
            {"answers": [answer, {"questionId": str(ObjectId()), "value": "x"}]},
            {"answers": [answer, {"questionId": targets[0]["questionId"], "value": "跳过题不能提交"}]},
            {"answers": [answer], "isAnonymous": True},
        ]:
            response = self.client.post(submit_path, json=payload, headers=self.bob_headers)
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(app.state.database.responses.count_documents({"surveyId": ObjectId(survey)}), 0)
        response = self.client.post(submit_path, json={"answers": [answer]}, headers=self.bob_headers)
        self.assertEqual(response.status_code, 201, response.text)

    def test_publish_deadline_and_draft_visibility(self):
        """场景：草稿不可填写及截止时间格式。
        步骤：访问草稿分享入口，提交过去/无时区时间，再用未来时间发布。
        预期：草稿404、错误时间422、正确发布200，发布后可填写且不可重复发布。
        """
        survey_id = self.new_survey()
        survey = self.client.get(f"/surveys/{survey_id}").json()
        share_path = f"/survey/{survey['shareToken']}"
        self.assertEqual(self.client.get(share_path, headers=self.bob_headers).status_code, 404)
        self.client.post(f"/surveys/{survey_id}/questions", json={"type": "text", "title": "建议", "order": 1})
        publish_path = f"/surveys/{survey_id}/publish"
        for deadline in ["2000-01-01T00:00:00Z", "2030-01-01T00:00:00"]:
            self.assertEqual(self.client.post(publish_path, json={"deadline": deadline}).status_code, 422)
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        response = self.client.post(publish_path, json={"deadline": future})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "published")
        self.assertIsNotNone(response.json()["deadline"])
        self.assertEqual(self.client.get(share_path, headers=self.bob_headers).status_code, 200)
        self.assertEqual(self.client.post(f"/surveys/{survey_id}/publish", json={}).status_code, 409)

    def test_statistics_known_counts_average_pagination_and_live_update(self):
        """场景：各题型统计、匿名内容分页、重复计数和实时更新。
        步骤：提交已知答案（含数字0、20及提前结束），核对整卷/单题并追加答卷。
        预期：单选2/1/0、多选1/2/0、均值10；分页不泄露身份，追加后更新，关闭后可查。
        """
        survey = self.client.post("/surveys", json={"title": "统计核对", "allowRepeat": True, "allowAnonymous": True}).json()
        survey_id = survey["id"]
        self.created_ids.append(ObjectId(survey_id))
        path = f"/surveys/{survey_id}"
        questions = []
        for kind, order in [("single", 1), ("multiple", 2), ("text", 3), ("number", 4)]:
            payload = {"type": kind, "title": kind, "order": order, "required": kind == "single"}
            if kind in {"single", "multiple"}:
                payload["options"] = [{"text": name, "order": index} for index, name in enumerate(["A", "B", "C"], 1)]
            response = self.client.post(path + "/questions", json=payload)
            self.assertEqual(response.status_code, 201, response.text)
            questions.append(response.json())
        single, multiple, text, number = questions
        single_ids = [o["optionId"] for o in single["options"]]
        multiple_ids = [o["optionId"] for o in multiple["options"]]
        self.client.put(path + f"/questions/{single['questionId']}/jump-rules", json={"rules": [
            {"operator": "selected", "value": single_ids[1], "targetQuestionId": None}]})
        self.assertEqual(self.client.post(path + "/publish", json={}).status_code, 200)
        submit_path = f"/survey/{survey['shareToken']}/responses"
        for selected, value, content in [(multiple_ids[:2], 0, "第一条"), (multiple_ids[1:2], 20, "第二条")]:
            payload = {"isAnonymous": True, "answers": [
                {"questionId": single["questionId"], "selectedOptionIds": single_ids[:1]},
                {"questionId": multiple["questionId"], "selectedOptionIds": selected},
                {"questionId": text["questionId"], "value": content},
                {"questionId": number["questionId"], "value": value},
            ]}
            self.assertEqual(self.client.post(submit_path, json=payload, headers=self.bob_headers).status_code, 201)
        self.assertEqual(self.client.post(submit_path, json={"answers": [
            {"questionId": single["questionId"], "selectedOptionIds": single_ids[1:2]}]}, headers=self.bob_headers).status_code, 201)
        stats = self.client.get(path + "/statistics")
        self.assertEqual(stats.status_code, 200, stats.text)
        summary = stats.json()
        self.assertEqual(summary["submissionCount"], 3)
        self.assertEqual([q["answerCount"] for q in summary["questions"]], [3, 2, 2, 2])
        self.assertEqual([o["count"] for o in summary["questions"][0]["options"]], [2, 1, 0])
        self.assertEqual([o["count"] for o in summary["questions"][1]["options"]], [1, 2, 0])
        self.assertEqual(summary["questions"][3]["average"], 10)
        for index, question in enumerate(questions):
            self.assertEqual(self.client.get(path + f"/questions/{question['questionId']}/statistics").json(), summary["questions"][index])
        contents_path = path + f"/questions/{text['questionId']}/answers"
        first = self.client.get(contents_path, params={"limit": 1}).json()
        second = self.client.get(contents_path, params={"skip": 1, "limit": 1}).json()
        self.assertEqual(first["total"], 2)
        self.assertEqual(first["items"][0]["value"], "第二条")
        self.assertEqual(second["items"][0]["value"], "第一条")
        self.assertEqual(set(first["items"][0]), {"value", "submittedAt"})
        self.assertEqual(self.client.get(contents_path, params={"skip": 100}).json()["items"], [])
        numeric = self.client.get(path + f"/questions/{number['questionId']}/answers").json()
        self.assertEqual([item["value"] for item in numeric["items"]], [20, 0])
        # 再提交一份，统计应立即变化，不需要刷新缓存或重建统计。
        self.assertEqual(self.client.post(submit_path, json={"answers": [
            {"questionId": single["questionId"], "selectedOptionIds": single_ids[:1]},
            {"questionId": number["questionId"], "value": 40}]}, headers=self.bob_headers).status_code, 201)
        changed = self.client.get(path + "/statistics").json()
        self.assertEqual(changed["submissionCount"], 4)
        self.assertEqual(changed["questions"][3]["average"], 20)
        self.assertEqual(changed["questions"][2]["answerCount"], 2)
        self.client.post(path + "/close")
        self.assertEqual(self.client.get(path + "/statistics").json(), changed)

    def test_statistics_empty_and_access_control(self):
        """场景：无答卷统计、权限、错题ID与分页限制。
        步骤：查询空问卷，切换账号/无令牌，使用错题ID和越界分页参数。
        预期：空统计为0、均值null；他人404、未登录401，非法参数被拒绝。
        """
        survey, question, _ = self.published_fixture()
        path = f"/surveys/{survey['id']}"
        stats = self.client.get(path + "/statistics").json()
        self.assertEqual(stats["submissionCount"], 0)
        self.assertEqual(stats["questions"][0]["answerCount"], 0)
        self.assertIsNone(stats["questions"][0]["average"])
        empty = self.new_survey()
        self.assertEqual(self.client.get(f"/surveys/{empty}/statistics").json()["questions"], [])
        endpoints = [path + "/statistics", path + f"/questions/{question['questionId']}/statistics",
                     path + f"/questions/{question['questionId']}/answers"]
        for endpoint in endpoints:
            self.assertEqual(self.client.get(endpoint, headers=self.bob_headers).status_code, 404)
            self.assertEqual(self.client.get(endpoint, headers={"Authorization": ""}).status_code, 401)
        self.assertEqual(self.client.get(path + "/questions/bad/statistics").status_code, 400)
        self.assertEqual(self.client.get(path + f"/questions/{ObjectId()}/statistics").status_code, 404)
        self.assertEqual(self.client.get(f"/surveys/{empty}/questions/{question['questionId']}/statistics").status_code, 404)
        self.assertEqual(self.client.get(endpoints[2], params={"skip": -1}).status_code, 422)
        self.assertEqual(self.client.get(endpoints[2], params={"limit": 101}).status_code, 422)
        _, choice, _, choice_path = self.jump_fixture()
        self.assertEqual(self.client.get(choice_path + "/answers").status_code, 400)


    def test_acceptance_text_length_and_exact_choice_boundaries(self):
        """场景：文本长度与恰选2项的边界校验。
        步骤：文本输入1/2/4/5字符；多选输入0/1/2/3项；最后测试非必答可不填。
        预期：长度2和4、恰好2项成功；越界422；非必答省略时顺序继续。
        """
        survey = self.new_survey()
        path = f"/surveys/{survey}/questions"
        text = self.client.post(path, json={"type": "text", "title": "长度测试", "order": 1,
                                          "required": True, "validation": {"minLength": 2, "maxLength": 4}}).json()
        text_path = path + f"/{text['questionId']}"
        for value, expected in [("中", 422), ("中文", 200), ("中文测试", 200), ("中文测试题", 422), (" ", 422), (12, 422)]:
            with self.subTest(kind="text", value=value):
                self.assertEqual(self.client.post(text_path + "/preview", json={"value": value}).status_code, expected)
        payload = {"type": "multiple", "title": "恰选2项", "order": 2, "required": True,
                   "options": [{"text": name, "order": order} for order, name in enumerate("ABC", 1)],
                   "validation": {"minChoices": 2, "maxChoices": 2}}
        choice = self.client.post(path, json=payload).json()
        ids = [o["optionId"] for o in choice["options"]]
        choice_path = path + f"/{choice['questionId']}"
        for count, expected in [(0, 422), (1, 422), (2, 200), (3, 422)]:
            with self.subTest(kind="multiple", count=count):
                self.assertEqual(self.client.post(choice_path + "/preview", json={"selectedOptionIds": ids[:count]}).status_code, expected)
        payload["required"] = False
        payload["options"] = choice["options"]
        self.assertEqual(self.client.put(choice_path, json=payload).status_code, 200)
        self.assertEqual(self.client.post(choice_path + "/preview", json={}).status_code, 200)

    def test_acceptance_multiple_and_numeric_full_submission_paths(self):
        """场景：正式提交中多选和数字跳转均由后端重新计算。
        步骤：A+B跳过数字；只选A后数字17直接结束；A+C、数字18则必须答文本。
        预期：三条合法路径各201；未达到结束条件却漏答必答文本时422且不落库。
        """
        survey = self.client.post("/surveys", json={"title": "混合路径验收", "allowRepeat": True}).json()
        self.created_ids.append(ObjectId(survey["id"]))
        path = f"/surveys/{survey['id']}/questions"
        multiple = self.client.post(path, json={"type": "multiple", "title": "分支", "order": 1, "required": True,
            "options": [{"text": name, "order": order} for order, name in enumerate("ABC", 1)]}).json()
        number = self.client.post(path, json={"type": "number", "title": "年龄", "order": 2, "required": True,
            "validation": {"minValue": 0, "maxValue": 120, "integerOnly": True}}).json()
        text = self.client.post(path, json={"type": "text", "title": "说明", "order": 3, "required": True}).json()
        ids = [o["optionId"] for o in multiple["options"]]
        self.assertEqual(self.client.put(path + f"/{multiple['questionId']}/jump-rules", json={"rules": [
            {"operator": "exactly", "value": ids[:2], "targetQuestionId": text["questionId"]}]}).status_code, 200)
        self.assertEqual(self.client.put(path + f"/{number['questionId']}/jump-rules", json={"rules": [
            {"operator": "<", "value": 18, "targetQuestionId": None}]}).status_code, 200)
        self.assertEqual(self.client.post(f"/surveys/{survey['id']}/publish", json={}).status_code, 200)
        endpoint = f"/survey/{survey['shareToken']}/responses"
        multi_answer = {"questionId": multiple["questionId"], "selectedOptionIds": ids[:1]}
        numeric_answer = {"questionId": number["questionId"], "value": 18}
        invalid = self.client.post(endpoint, json={"answers": [multi_answer, numeric_answer]}, headers=self.bob_headers)
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["detail"]["questionId"], text["questionId"])
        self.assertEqual(app.state.database.responses.count_documents({"surveyId": ObjectId(survey["id"])}), 0)
        valid_paths = [
            [{**multi_answer, "selectedOptionIds": ids[:2]}, {"questionId": text["questionId"], "value": "跳过年龄"}],
            [multi_answer, {**numeric_answer, "value": 17}],
            [{**multi_answer, "selectedOptionIds": [ids[0], ids[2]]}, numeric_answer,
             {"questionId": text["questionId"], "value": "完整路径"}],
        ]
        for answers in valid_paths:
            with self.subTest(answers=answers):
                response = self.client.post(endpoint, json={"answers": answers}, headers=self.bob_headers)
                self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(app.state.database.responses.count_documents({"surveyId": ObjectId(survey["id"])}), 3)

    def test_acceptance_distinct_users_submit_concurrently(self):
        """场景：禁止重复不应阻止不同用户同时填写。
        步骤：alice和bob并发提交同一问卷，各自只提交一次。
        预期：两个请求都201，保存2条答卷、2个不同用户ID。
        """
        survey, _, payload = self.published_fixture()
        endpoint = f"/survey/{survey['shareToken']}/responses"
        headers = [{"Authorization": "Bearer " + self.alice_token}, self.bob_headers]
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(lambda auth: self.client.post(endpoint, json=payload, headers=auth).status_code, headers))
        self.assertEqual(statuses, [201, 201])
        respondents = app.state.database.responses.distinct("respondentId", {"surveyId": ObjectId(survey["id"])})
        self.assertEqual(set(respondents), set(self.user_ids))

    def test_acceptance_malformed_json_and_missing_jump_target(self):
        """场景：Swagger输入错误应得到明确提示，不能改变规则。
        步骤：提交末尾多逗号的JSON，再提交缺少targetQuestionId的数字规则。
        预期：分别返回json_invalid和missing的422，数据库题目保持原样。
        """
        survey, _, _, path = self.jump_fixture("number")
        before = self.collection.find_one({"_id": ObjectId(survey)})
        response = self.client.put(path + "/jump-rules", content='{"rules": [{"operator": "<", "value": 18, "targetQuestionId": null,}]}',
                                   headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"][0]["type"], "json_invalid")
        response = self.client.put(path + "/jump-rules", json={"rules": [{"operator": "<", "value": 18}]})
        self.assertEqual(response.status_code, 422)
        self.assertTrue(any(error["type"] == "missing" and error["loc"][-1] == "targetQuestionId" for error in response.json()["detail"]))
        self.assertEqual(self.collection.find_one({"_id": ObjectId(survey)}), before)

    def test_acceptance_saved_answers_visible_from_fresh_database_connection(self):
        """场景：成功提交的数据真实持久化，不只存在于接口进程内存。
        步骤：bob提交数字20，使用全新的MongoClient连接读取该记录。
        预期：可查到ObjectId关联、数值20和日期；该测试不等同于断电恢复测试。
        """
        survey, question, payload = self.published_fixture()
        response = self.client.post(f"/survey/{survey['shareToken']}/responses", json=payload, headers=self.bob_headers)
        self.assertEqual(response.status_code, 201)
        with MongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017"), serverSelectionTimeoutMS=3000, tz_aware=True) as fresh:
            document = fresh[app.state.database.name].responses.find_one({"_id": ObjectId(response.json()["id"])})
            self.assertIsNotNone(document)
            self.assertEqual(document["answers"], [{"questionId": ObjectId(question["questionId"]), "value": 20}])
            self.assertEqual(document["respondentId"], ObjectId(self.accounts["bob"]["id"]))
            self.assertIsInstance(document["submittedAt"], datetime)

    def test_insert_question_before_first_and_middle_preserves_references(self):
        """场景：在第一题及中间插入新题，自动顺移且保留跳转引用。
        步骤：原第1题跳到第3题，先在第1题前插入，再在原第3题前插入。
        预期：均201，题序依次为1～5，原题目/选项ID及规则目标保持不变。
        """
        survey, source, targets, path = self.jump_fixture()
        rule = {"operator": "selected", "value": source["options"][0]["optionId"], "targetQuestionId": targets[1]["questionId"]}
        self.assertEqual(self.client.put(path + "/jump-rules", json={"rules": [rule]}).status_code, 200)
        response = self.client.post(path + "/insert", json={"type": "text", "title": "插入第一题", "order": 1, "required": False})
        self.assertEqual(response.status_code, 201, response.text)
        first_id = response.json()["questionId"]
        detail = self.client.get(f"/surveys/{survey}").json()
        self.assertEqual([q["order"] for q in detail["questions"]], [1, 2, 3, 4])
        self.assertEqual(detail["questions"][0]["questionId"], first_id)
        self.assertFalse(detail["questions"][0]["required"])
        self.assertEqual(detail["questions"][1]["questionId"], source["questionId"])
        self.assertEqual(detail["questions"][1]["options"], source["options"])
        self.assertEqual(detail["questions"][1]["jumpRules"], [rule])
        response = self.client.post(f"/surveys/{survey}/questions/{targets[1]['questionId']}/insert", json={
            "type": "text", "title": "插入中间", "order": 4, "required": True})
        self.assertEqual(response.status_code, 201, response.text)
        detail = self.client.get(f"/surveys/{survey}").json()
        self.assertEqual([q["order"] for q in detail["questions"]], [1, 2, 3, 4, 5])
        self.assertEqual(detail["questions"][-1]["questionId"], targets[1]["questionId"])
        self.assertTrue(detail["questions"][-2]["required"])
        preview = self.client.post(path + "/preview", json={"selectedOptionIds": [source["options"][0]["optionId"]]})
        self.assertEqual(preview.json()["nextQuestionId"], targets[1]["questionId"])

    def test_insert_question_invalid_stale_or_unauthorized_does_not_write(self):
        """场景：插入接口的权限、过期题序和非法配置。
        步骤：他人/未登录插入，错误题序、未知目标、空题干，最后模拟发布后插入。
        预期：404/401/409/422对应拒绝，失败不修改原题目数组。
        """
        survey, _, _, path = self.jump_fixture()
        payload = {"type": "text", "title": "新题", "order": 1}
        before = self.collection.find_one({"_id": ObjectId(survey)})["questions"]
        self.assertEqual(self.client.post(path + "/insert", json=payload, headers=self.bob_headers).status_code, 404)
        self.assertEqual(self.client.post(path + "/insert", json=payload, headers={"Authorization": ""}).status_code, 401)
        self.assertEqual(self.client.post(path + "/insert", json={**payload, "order": 2}).status_code, 409)
        self.assertEqual(self.client.post(path + "/insert", json={**payload, "title": " "}).status_code, 422)
        self.assertEqual(self.client.post(f"/surveys/{survey}/questions/{ObjectId()}/insert", json=payload).status_code, 404)
        self.assertEqual(self.collection.find_one({"_id": ObjectId(survey)})["questions"], before)
        self.assertEqual(self.client.post(f"/surveys/{survey}/publish", json={}).status_code, 200)
        self.assertEqual(self.client.post(path + "/insert", json=payload).status_code, 409)

    def test_insert_concurrent_requests_do_not_overwrite_questions(self):
        """场景：两个请求同时在相同位置插入。
        步骤：以相同旧题序并发提交两次插入请求。
        预期：一个201、一个409，最终仅新增一题，题序唯一且旧题均保留。
        """
        survey, _, _, path = self.jump_fixture()
        payload = {"type": "text", "title": "并发插入", "order": 1}
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(lambda _: self.client.post(path + "/insert", json=payload).status_code, range(2)))
        self.assertEqual(sorted(statuses), [201, 409])
        questions = self.collection.find_one({"_id": ObjectId(survey)})["questions"]
        self.assertEqual(len(questions), 4)
        self.assertEqual([q["order"] for q in questions], [1, 2, 3, 4])

    def test_draft_basic_info_partial_update_preserves_structure(self):
        """场景：创建者修改草稿标题、说明与填写开关。
        步骤：先创建有题目的草稿，分别局部更新标题和其他信息，再查询。
        预期：标题去首尾空格、开关正确，ID/创建者/时间/访问标识/题目不变。
        """
        survey, _, _, _ = self.jump_fixture()
        before = self.client.get(f"/surveys/{survey}").json()
        response = self.client.patch(f"/surveys/{survey}", json={"title": "  新标题  "})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["title"], "新标题")
        self.assertEqual(response.json()["description"], before["description"])
        response = self.client.patch(f"/surveys/{survey}", json={"description": "新说明", "allowAnonymous": True, "allowRepeat": True})
        self.assertEqual(response.status_code, 200, response.text)
        changed = response.json()
        self.assertEqual(changed["description"], "新说明")
        self.assertTrue(changed["allowAnonymous"])
        self.assertTrue(changed["allowRepeat"])
        for key in ["id", "creatorId", "createdAt", "shareToken", "questions", "status"]:
            self.assertEqual(changed[key], before[key])
        cleared = self.client.patch(f"/surveys/{survey}", json={"description": "", "allowAnonymous": False})
        self.assertEqual(cleared.json()["description"], "")
        self.assertFalse(cleared.json()["allowAnonymous"])

    def test_draft_basic_info_rejects_invalid_or_unauthorized_changes(self):
        """场景：修改接口不允许非法值、伪造归属或越权。
        步骤：发送空请求/null/空标题/错误布尔/额外字段，换账号或取消登录。
        预期：非法请求422、他人404、未登录401，数据库草稿保持不变。
        """
        survey = self.new_survey()
        endpoint = f"/surveys/{survey}"
        before = self.collection.find_one({"_id": ObjectId(survey)})
        for payload in [{}, {"title": None}, {"description": None}, {"allowRepeat": None},
                        {"title": " "}, {"allowAnonymous": "true"}, {"creatorId": self.accounts["bob"]["id"]},
                        {"questions": []}, {"status": "published"}]:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.patch(endpoint, json=payload).status_code, 422)
        self.assertEqual(self.client.patch(endpoint, json={"title": "x"}, headers=self.bob_headers).status_code, 404)
        self.assertEqual(self.client.patch(endpoint, json={"title": "x"}, headers={"Authorization": ""}).status_code, 401)
        self.assertEqual(self.client.patch('/surveys/bad-id', json={"title": "x"}).status_code, 400)
        self.assertEqual(self.collection.find_one({"_id": ObjectId(survey)}), before)

    def test_basic_info_locked_after_publish_and_updated_settings_take_effect(self):
        """场景：草稿设置修改后在提交时生效，发布/关闭后禁止再改。
        步骤：草稿开启匿名和重复填写，发布后匿名提交两次，再尝试修改。
        预期：两次201；发布和关闭后的修改均409，已有答卷保持两条。
        """
        survey = self.new_survey()
        endpoint = f"/surveys/{survey}"
        question = self.client.post(endpoint + '/questions', json={"type": "text", "title": "建议", "order": 1}).json()
        self.assertEqual(self.client.patch(endpoint, json={"allowAnonymous": True, "allowRepeat": True}).status_code, 200)
        published = self.client.post(endpoint + '/publish', json={}).json()
        payload = {"isAnonymous": True, "answers": [{"questionId": question['questionId'], "value": "建议内容"}]}
        for _ in range(2):
            self.assertEqual(self.client.post(f"/survey/{published['shareToken']}/responses", json=payload, headers=self.bob_headers).status_code, 201)
        self.assertEqual(self.client.patch(endpoint, json={"allowRepeat": False}).status_code, 409)
        self.client.post(endpoint + '/close')
        self.assertEqual(self.client.patch(endpoint, json={"title": "不应修改"}).status_code, 409)
        self.assertEqual(app.state.database.responses.count_documents({"surveyId": ObjectId(survey)}), 2)


if __name__ == "__main__":
    unittest.main()
