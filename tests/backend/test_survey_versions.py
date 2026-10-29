"""问卷版本：复制快照、分支关系、答卷隔离、权限和并发编号。"""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from bson import ObjectId
from fastapi.testclient import TestClient

from app.main import app


class SurveyVersionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = os.environ.get("MONGODB_DATABASE")
        cls.name = "questionnaire_test_sv_" + uuid4().hex
        os.environ["MONGODB_DATABASE"] = cls.name
        cls.context = TestClient(app)
        try:
            cls.client = cls.context.__enter__()
        except Exception:
            cls.restore_environment()
            raise
        cls.db = app.state.database
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
                cls.db.client.drop_database(cls.name)
        finally:
            cls.context.__exit__(None, None, None)
            cls.restore_environment()

    def setUp(self):
        for collection in ["surveys", "responses", "questions"]:
            self.db[collection].delete_many({})

    def post(self, path, body=None, expected=201):
        result = self.client.post(path, json={} if body is None else body)
        self.assertEqual(result.status_code, expected, result.text)
        return result.json()

    def survey(self):
        return self.post("/surveys", {"title": "原问卷", "description": "原说明", "allowAnonymous": True})

    def derive(self, parent):
        return self.post(f"/surveys/{parent['id']}/versions")

    def stored(self, survey):
        return self.db.surveys.find_one({"_id": ObjectId(survey["id"])})

    def fixture(self):
        root = self.survey()
        base = f"/surveys/{root['id']}/questions"
        choice = self.post(base, {"type": "single", "title": "选择", "order": 1, "required": True,
            "options": [{"text": "跳转", "order": 1}, {"text": "继续", "order": 2}]})
        self.post(base, {"type": "text", "title": "可跳过的题", "order": 2})
        source = self.post("/library/questions", {"title": "年龄v1", "type": "number", "validation": {"minValue": 0}})
        linked = self.post(base + "/from-library", {"sourceQuestionId": source["id"], "required": True})
        rule = {"operator": "selected", "value": choice["options"][0]["optionId"], "targetQuestionId": linked["questionId"]}
        result = self.client.put(base + f"/{choice['questionId']}/jump-rules", json={"rules": [rule]})
        self.assertEqual(result.status_code, 200, result.text)
        answers = [{"questionId": choice["questionId"], "selectedOptionIds": [choice["options"][0]["optionId"]]},
                   {"questionId": linked["questionId"], "value": 20}]
        return root, source, answers

    def test_copy_published_snapshot_resets_lifecycle_and_retains_question_versions(self):
        root, source, answers = self.fixture()
        self.post("/library/questions/" + source["id"] + "/versions", {"title": "年龄v2", "type": "number"})
        deadline = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        published = self.post(f"/surveys/{root['id']}/publish", {"deadline": deadline}, expected=200)
        receipt = self.post(f"/survey/{published['shareToken']}/responses", {"answers": answers})
        before = self.stored(root)
        response_before = self.db.responses.find_one({"_id": ObjectId(receipt["id"])})
        clone = self.derive(root)
        self.assertNotEqual(clone["id"], root["id"])
        self.assertNotEqual(clone["shareToken"], root["shareToken"])
        self.assertEqual(clone["version"], 2)
        self.assertEqual(clone["rootSurveyId"], root["id"])
        self.assertEqual(clone["parentSurveyId"], root["id"])
        self.assertEqual(clone["status"], "draft")
        self.assertIsNone(clone["deadline"])
        self.assertEqual(clone["creatorId"], root["creatorId"])
        self.assertEqual(self.stored(clone)["questions"], before["questions"])
        self.assertEqual(clone["questions"][-1]["sourceQuestionId"], source["id"])
        self.assertEqual(self.stored(root), before)
        self.assertEqual(self.db.responses.find_one({"_id": response_before["_id"]}), response_before)
        self.assertEqual(self.db.responses.count_documents({"surveyId": ObjectId(clone["id"])}), 0)
        self.assertEqual(self.client.get(f"/survey/{clone['shareToken']}").status_code, 404)
        old_link = self.client.get(f"/survey/{root['shareToken']}")
        self.assertEqual(old_link.status_code, 200)
        self.assertEqual(old_link.json()["id"], root["id"])

    def test_empty_draft_clone_and_edit_do_not_create_extra_versions(self):
        root = self.survey()
        clone = self.derive(root)
        self.assertEqual(clone["questions"], [])
        result = self.client.patch(f"/surveys/{clone['id']}", json={"title": "仅修改新草稿", "description": "新版说明"})
        self.assertEqual(result.status_code, 200, result.text)
        self.post(f"/surveys/{clone['id']}/questions", {"type": "text", "title": "新题", "order": 1})
        current = self.client.get(f"/surveys/{clone['id']}").json()
        self.assertEqual(current["version"], 2)
        self.assertEqual(self.db.surveys.count_documents({}), 2)
        self.assertEqual(self.client.get(f"/surveys/{root['id']}").json(), root)

    def test_branching_history_and_pagination_keep_real_parent(self):
        root = self.survey()
        v2 = self.derive(root)
        v3 = self.derive(v2)
        v4 = self.derive(v2)
        self.survey()  # 其他系列不能混入历史。
        self.assertEqual([root["version"], v2["version"], v3["version"], v4["version"]], [1, 2, 3, 4])
        self.assertEqual(v4["parentSurveyId"], v2["id"])
        history = self.client.get(f"/surveys/{v4['id']}/versions").json()
        self.assertEqual([v["id"] for v in history], [root["id"], v2["id"], v3["id"], v4["id"]])
        self.assertTrue(all(v["rootSurveyId"] == root["id"] for v in history))
        self.assertTrue(all("questions" not in v and "shareToken" not in v for v in history))
        page = self.client.get(f"/surveys/{root['id']}/versions?skip=1&limit=2").json()
        self.assertEqual([v["version"] for v in page], [2, 3])
        self.assertEqual(self.client.get(f"/surveys/{root['id']}/versions?skip=4").json(), [])

    def test_closed_parent_can_create_draft_without_reopening_old_link(self):
        root, _, _ = self.fixture()
        self.post(f"/surveys/{root['id']}/publish", expected=200)
        self.post(f"/surveys/{root['id']}/close", expected=200)
        before = self.stored(root)
        clone = self.derive(root)
        self.assertEqual(clone["status"], "draft")
        self.assertEqual(self.stored(root), before)
        self.assertEqual(self.client.get(f"/survey/{root['shareToken']}").status_code, 409)
        history = self.client.get(f"/surveys/{root['id']}/versions").json()
        self.assertEqual([v["status"] for v in history], ["closed", "draft"])

    def test_answers_statistics_and_repeat_restriction_are_per_version(self):
        root, _, answers = self.fixture()
        self.post(f"/surveys/{root['id']}/publish", expected=200)
        self.post(f"/survey/{root['shareToken']}/responses", {"answers": answers})
        clone = self.derive(root)
        self.post(f"/surveys/{clone['id']}/publish", expected=200)
        result = self.post(f"/survey/{clone['shareToken']}/responses", {"answers": answers})
        self.assertEqual(result["surveyId"], clone["id"])
        for survey in [root, clone]:
            stats = self.client.get(f"/surveys/{survey['id']}/statistics").json()
            self.assertEqual(stats["submissionCount"], 1)
            self.assertEqual(stats["questions"][0]["answerCount"], 1)
            self.assertEqual(self.client.post(f"/survey/{survey['shareToken']}/responses", json={"answers": answers}).status_code, 409)
        # 新草稿后续再编辑，只影响它自己的副本。
        third = self.derive(clone)
        q = third["questions"][0]
        payload = {k: q[k] for k in ["title", "type", "order", "required", "options", "validation"]}
        updated = self.client.put(f"/surveys/{third['id']}/questions/{q['questionId']}", json={**payload, "title": "新版题干"})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(self.client.get(f"/surveys/{root['id']}").json()["questions"][0]["title"], "选择")
        self.assertEqual(self.client.get(f"/surveys/{clone['id']}").json()["questions"][0]["title"], "选择")

    def test_permissions_invalid_ids_pagination_and_metadata_injection(self):
        root = self.survey()
        path = f"/surveys/{root['id']}/versions"
        for headers, expected in [(self.headers["other"], 404), ({"Authorization": ""}, 401)]:
            self.assertEqual(self.client.get(path, headers=headers).status_code, expected)
            self.assertEqual(self.client.post(path, json={}, headers=headers).status_code, expected)
        for identifier, expected in [("bad", 400), (str(ObjectId()), 404)]:
            self.assertEqual(self.client.get(f"/surveys/{identifier}/versions").status_code, expected)
            self.assertEqual(self.client.post(f"/surveys/{identifier}/versions", json={}).status_code, expected)
        for query in ["skip=-1", "limit=0", "limit=101"]:
            self.assertEqual(self.client.get(path + "?" + query).status_code, 422)
        for key, value in [("version", 10), ("rootSurveyId", str(ObjectId())), ("parentSurveyId", str(ObjectId())),
                           ("creatorId", str(ObjectId())), ("status", "published"), ("shareToken", "forged"),
                           ("questions", []), ("deadline", None)]:
            self.assertEqual(self.client.post(path, json={key: value}).status_code, 422)
        self.assertEqual(self.db.surveys.count_documents({}), 1)

    def test_concurrent_branches_have_distinct_versions_and_share_tokens(self):
        root = self.survey()
        def derive(_):
            return self.client.post(f"/surveys/{root['id']}/versions", json={})
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(derive, range(8)))
        for result in results:
            self.assertEqual(result.status_code, 201, result.text)
        versions = [result.json() for result in results]
        self.assertEqual(sorted(v["version"] for v in versions), list(range(2, 10)))
        self.assertEqual(len({v["shareToken"] for v in versions}), 8)
        self.assertTrue(all(v["parentSurveyId"] == root["id"] and v["status"] == "draft" for v in versions))

    def test_share_token_collision_retries_and_returns_saved_document(self):
        root = self.survey()
        with patch("app.surveys.versions.token_urlsafe", side_effect=[root["shareToken"], "new-unique-token"]):
            clone = self.derive(root)
        self.assertEqual(clone["version"], 2)
        self.assertEqual(clone["shareToken"], "new-unique-token")
        self.assertEqual(self.client.get(f"/surveys/{clone['id']}").json(), clone)
        self.assertEqual(self.db.surveys.count_documents({}), 2)

    def test_repeated_collision_returns_conflict_without_partial_clone(self):
        root = self.survey()
        before = self.stored(root)
        with patch("app.surveys.versions.token_urlsafe", return_value=root["shareToken"]) as token:
            result = self.client.post(f"/surveys/{root['id']}/versions", json={})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(token.call_count, 16)
        self.assertEqual(self.db.surveys.count_documents({}), 1)
        self.assertEqual(self.stored(root), before)
