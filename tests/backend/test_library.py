"""常用题版本管理：真实 MongoDB、HTTP 权限、不可变性与并发取号。"""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from bson import ObjectId
from fastapi.testclient import TestClient

from app.main import app


class LibraryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = os.environ.get("MONGODB_DATABASE")
        cls.database_name = "questionnaire_test_library_" + uuid4().hex
        os.environ["MONGODB_DATABASE"] = cls.database_name
        cls.context = TestClient(app)
        try:
            cls.client = cls.context.__enter__()
        except Exception:
            cls.restore_environment()
            raise
        cls.database = app.state.database
        cls.headers = {}
        for name in ["author", "other"]:
            response = cls.client.post("/auth/register", json={"username": name, "password": "test-password-123"})
            assert response.status_code == 201, response.text
            token = cls.client.post("/auth/token", data={"username": name, "password": "test-password-123"}).json()["access_token"]
            cls.headers[name] = {"Authorization": "Bearer " + token}
        cls.client.headers.update(cls.headers["author"])

    @classmethod
    def restore_environment(cls):
        if cls.previous is None:
            os.environ.pop("MONGODB_DATABASE", None)
        else:
            os.environ["MONGODB_DATABASE"] = cls.previous

    @classmethod
    def tearDownClass(cls):
        try:
            if os.environ.get("KEEP_TEST_DATA") == "0":
                cls.database.client.drop_database(cls.database_name)
        finally:
            cls.context.__exit__(None, None, None)
            cls.restore_environment()

    def setUp(self):
        # 只清理本测试类随机创建的数据库，不涉及业务库。
        self.database.questions.delete_many({})
        self.database.surveys.delete_many({})

    def create(self, payload=None):
        response = self.client.post("/library/questions", json=payload or {
            "title": "你的年龄", "type": "number", "validation": {"minValue": 0, "integerOnly": True}})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def derive(self, parent, title="你的周岁年龄"):
        response = self.client.post(f"/library/questions/{parent['id']}/versions", json={
            "title": title, "type": "number", "validation": {"minValue": 0}})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_create_four_types_and_server_owned_metadata(self):
        payloads = [
            {"title": " 单选 ", "type": "single", "options": [{"text": "甲", "order": 2}, {"text": "乙", "order": 1}]},
            {"title": "多选", "type": "multiple", "options": [{"text": "甲", "order": 1}, {"text": "乙", "order": 2}], "validation": {"maxChoices": 2}},
            {"title": "建议", "type": "text", "validation": {"maxLength": 50}},
            {"title": "年龄", "type": "number", "validation": {"minValue": 0}},
        ]
        for payload in payloads:
            data = self.create(payload)
            self.assertEqual(data["rootQuestionId"], data["id"])
            self.assertIsNone(data["parentQuestionId"])
            self.assertEqual(data["version"], 1)
            self.assertFalse(data["sharingEnabled"])
            self.assertTrue(data["shareToken"])
            stored = self.database.questions.find_one({"_id": ObjectId(data["id"])})
            self.assertIsInstance(stored["creatorId"], ObjectId)
            self.assertNotIn("required", stored)
            self.assertNotIn("order", stored)
            self.assertEqual(self.client.get(f"/library/questions/{data['id']}").json(), data)
            if data["options"]:
                self.assertEqual([o["order"] for o in data["options"]], [1, 2])
                self.assertTrue(all(ObjectId.is_valid(o["optionId"]) for o in data["options"]))
        self.assertEqual(self.database.questions.count_documents({}), 4)

    def test_invalid_content_and_metadata_injection_do_not_write(self):
        base = {"title": "年龄", "type": "number"}
        invalid = [{**base, "title": " "}, {**base, "validation": {"minValue": 20, "maxValue": 10}},
                   {"title": "选项", "type": "single", "options": []},
                   {"title": "文本", "type": "text", "validation": {"maxChoices": 2}}]
        for key, value in [("version", 10), ("creatorId", str(ObjectId())), ("rootQuestionId", str(ObjectId())),
                           ("parentQuestionId", str(ObjectId())), ("shareToken", "injected"), ("sharingEnabled", True),
                           ("required", True), ("order", 1), ("restoredFromQuestionId", str(ObjectId()))]:
            invalid.append({**base, key: value})
        for payload in invalid:
            self.assertEqual(self.client.post("/library/questions", json=payload).status_code, 422, payload)
        self.assertEqual(self.database.questions.count_documents({}), 0)

    def test_branching_history_pagination_and_original_unchanged(self):
        root = self.create()
        v2 = self.derive(root)
        v3 = self.derive(v2, "新版")
        v4 = self.derive(v2, "从旧版分支")
        self.assertEqual([root["version"], v2["version"], v3["version"], v4["version"]], [1, 2, 3, 4])
        self.assertEqual(v4["parentQuestionId"], v2["id"])
        self.assertEqual(v4["rootQuestionId"], root["id"])
        self.assertEqual(self.client.get(f"/library/questions/{root['id']}").json(), root)
        history = self.client.get(f"/library/questions/{v2['id']}/versions?skip=1&limit=2").json()
        self.assertEqual([q["version"] for q in history], [2, 3])
        self.assertEqual(len(self.client.get("/library/questions").json()), 1)
        self.assertEqual(self.client.get("/library/questions?skip=1").json(), [])
        self.assertEqual(self.client.get("/library/questions?limit=101").status_code, 422)

    def test_restore_records_both_sources_and_leaves_surveys_unchanged(self):
        root = self.create()
        v2 = self.derive(root)
        survey = {"_id": ObjectId(), "shareToken": "old-survey", "rootSurveyId": ObjectId(), "version": 1,
                  "questions": [{"questionId": ObjectId(), "sourceQuestionId": ObjectId(root["id"]), "title": root["title"]}]}
        self.database.surveys.insert_one(survey)
        result = self.client.post(f"/library/questions/{v2['id']}/restore", json={"restoredFromQuestionId": root["id"]})
        self.assertEqual(result.status_code, 201, result.text)
        saved = result.json()
        self.assertEqual(saved["version"], 3)
        self.assertEqual(saved["parentQuestionId"], v2["id"])
        self.assertEqual(saved["restoredFromQuestionId"], root["id"])
        self.assertEqual(saved["validation"], root["validation"])
        self.assertEqual(saved["title"], root["title"])
        self.assertNotEqual(saved["shareToken"], root["shareToken"])
        self.assertEqual(self.client.get(f"/library/questions/{v2['id']}").json(), v2)
        self.assertEqual(self.database.surveys.find_one({"_id": survey["_id"]}), survey)
        other_root = self.create()
        self.assertEqual(self.client.post(f"/library/questions/{v2['id']}/restore", json={
            "restoredFromQuestionId": other_root["id"]}).status_code, 422)

    def test_ownership_and_immutable_http_contract(self):
        root = self.create()
        path = f"/library/questions/{root['id']}"
        for headers, expected in [(self.headers["other"], 404), ({"Authorization": ""}, 401)]:
            for suffix in ["", "/versions"]:
                self.assertEqual(self.client.get(path + suffix, headers=headers).status_code, expected)
            self.assertEqual(self.client.post(path + "/versions", json={"type": "text", "title": "越权"}, headers=headers).status_code, expected)
            self.assertEqual(self.client.post(path + "/restore", json={"restoredFromQuestionId": root["id"]}, headers=headers).status_code, expected)
        self.assertEqual(self.client.get("/library/questions", headers=self.headers["other"]).json(), [])
        for method in ["PUT", "PATCH", "DELETE"]:
            self.assertEqual(self.client.request(method, path, json={"title": "覆盖"}).status_code, 405)
        self.assertEqual(self.client.get("/library/questions/not-an-id").status_code, 400)
        self.assertEqual(self.client.get(f"/library/questions/{ObjectId()}").status_code, 404)
        self.assertEqual(self.database.questions.count_documents({}), 1)

    def test_options_can_preserve_parent_ids_but_not_inject_foreign_ids(self):
        root = self.create({"type": "single", "title": "水果", "options": [
            {"text": "苹果", "order": 1}, {"text": "香蕉", "order": 2}]})
        payload = {"type": "multiple", "title": "喜欢的水果", "options": root["options"] + [{"text": "梨", "order": 3}]}
        response = self.client.post(f"/library/questions/{root['id']}/versions", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        v2 = response.json()
        self.assertEqual(v2["options"][:2], root["options"])
        self.assertNotIn(v2["options"][2]["optionId"], [o["optionId"] for o in root["options"]])
        self.assertEqual(self.client.post("/library/questions", json=payload).status_code, 422)
        bad = {**payload, "options": [{**root["options"][0], "optionId": str(ObjectId())}, root["options"][1]]}
        self.assertEqual(self.client.post(f"/library/questions/{root['id']}/versions", json=bad).status_code, 422)
        restored = self.client.post(f"/library/questions/{v2['id']}/restore", json={"restoredFromQuestionId": root["id"]}).json()
        self.assertEqual(restored["options"], root["options"])

    def test_concurrent_versions_have_unique_numbers_and_keep_parent(self):
        root = self.create()
        def create_branch(number):
            return self.client.post(f"/library/questions/{root['id']}/versions", json={"title": f"并发版本{number}", "type": "text"})
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(create_branch, range(8)))
        for response in responses:
            self.assertEqual(response.status_code, 201, response.text)
        versions = [response.json() for response in responses]
        self.assertEqual(sorted(item["version"] for item in versions), list(range(2, 10)))
        self.assertTrue(all(item["parentQuestionId"] == root["id"] for item in versions))
        self.assertEqual(len({item["shareToken"] for item in versions}), 8)
