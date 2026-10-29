"""题目复用验收：来源固定、跳转一致、权限、草稿边界与并发保护。"""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

from bson import ObjectId
from fastapi.testclient import TestClient

from app.main import app
from app.surveys.reuse import save_questions


class ReuseIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = os.environ.get("MONGODB_DATABASE")
        cls.name = "questionnaire_test_reuse_" + uuid4().hex
        os.environ["MONGODB_DATABASE"] = cls.name
        cls.context = TestClient(app)
        try:
            cls.client = cls.context.__enter__()
        except Exception:
            cls.restore_env()
            raise
        cls.db = app.state.database
        cls.headers = {}
        for name in ["owner", "other"]:
            assert cls.client.post("/auth/register", json={"username": name, "password": "test-password-123"}).status_code == 201
            result = cls.client.post("/auth/token", data={"username": name, "password": "test-password-123"})
            cls.headers[name] = {"Authorization": "Bearer " + result.json()["access_token"]}
        cls.client.headers.update(cls.headers["owner"])

    @classmethod
    def restore_env(cls):
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
            cls.restore_env()

    def setUp(self):
        for name in ["questions", "surveys", "responses"]:
            self.db[name].delete_many({})

    def post(self, path, body=None, status=201):
        response = self.client.post(path, json=body) if body is not None else self.client.post(path)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def survey(self):
        return self.post("/surveys", {"title": "复用调查"})["id"]

    def source(self, kind="single", **validation):
        payload = {"title": "喜欢的水果" if kind in ["single", "multiple"] else "年龄", "type": kind, "validation": validation}
        if kind in ["single", "multiple"]:
            payload["options"] = [{"text": "苹果", "order": 1}, {"text": "香蕉", "order": 2}]
        return self.post("/library/questions", payload)

    def derive(self, source, **changes):
        payload = {key: source[key] for key in ["title", "type", "validation"]}
        if source["options"]:
            payload["options"] = source["options"]
        return self.post(f"/library/questions/{source['id']}/versions", {**payload, **changes})

    def add(self, survey, source, **settings):
        return self.post(f"/surveys/{survey}/questions/from-library", {"sourceQuestionId": source["id"], **settings})

    def stored(self, survey):
        return self.db.surveys.find_one({"_id": ObjectId(survey)})

    def switch(self, survey, question, source, **extra):
        return self.client.post(f"/surveys/{survey}/questions/{question['questionId']}/switch-version", json={
            "expectedSourceQuestionId": question["sourceQuestionId"], "sourceQuestionId": source["id"], **extra})

    def test_save_independent_copy_without_changing_survey_or_rules(self):
        survey = self.survey()
        question = self.post(f"/surveys/{survey}/questions", {"title": "水果", "type": "single", "order": 1,
            "required": True, "options": [{"text": "苹果", "order": 1}, {"text": "香蕉", "order": 2}]})
        self.client.put(f"/surveys/{survey}/questions/{question['questionId']}/jump-rules", json={"rules": [
            {"operator": "selected", "value": question["options"][0]["optionId"], "targetQuestionId": None}]})
        before = self.stored(survey)
        copied = self.post(f"/surveys/{survey}/questions/{question['questionId']}/save-to-library")
        self.assertEqual(copied["version"], 1)
        self.assertEqual(copied["rootQuestionId"], copied["id"])
        self.assertEqual(copied["title"], question["title"])
        self.assertFalse(copied["sharingEnabled"])
        self.assertTrue(set(o["optionId"] for o in copied["options"]).isdisjoint(o["optionId"] for o in question["options"]))
        stored_copy = self.db.questions.find_one({"_id": ObjectId(copied["id"])})
        for key in ["questionId", "sourceQuestionId", "order", "required", "jumpRules"]:
            self.assertNotIn(key, stored_copy)
        self.assertEqual(self.stored(survey), before)

    def test_add_fixed_version_multiple_instances_and_full_submission(self):
        survey = self.survey()
        v1 = self.source()
        v2 = self.derive(v1, title="新版水果题")
        first = self.add(survey, v1, required=True)
        second = self.add(survey, v1)
        self.assertNotEqual(first["questionId"], second["questionId"])
        self.assertEqual(first["options"], v1["options"])
        self.assertEqual(first["sourceQuestionId"], v1["id"])
        self.assertEqual([first["order"], second["order"]], [1, 2])
        self.assertEqual(first["jumpRules"], [])
        self.assertEqual(self.db.questions.count_documents({}), 2)
        published = self.post(f"/surveys/{survey}/publish", {}, status=200)
        token = published["shareToken"]
        result = self.post(f"/survey/{token}/responses", {"answers": [{"questionId": first["questionId"],
            "selectedOptionIds": [first["options"][0]["optionId"]]}]})
        answer = self.db.responses.find_one({"_id": ObjectId(result["id"])})["answers"][0]
        self.assertEqual(answer["questionId"], ObjectId(first["questionId"]))
        self.assertNotEqual(first["sourceQuestionId"], v2["id"])

    def test_insert_before_preserves_ids_and_rejects_stale_order(self):
        survey = self.survey()
        source = self.source("text")
        target = self.add(survey, source, order=5)
        inserted = self.add(survey, source, beforeQuestionId=target["questionId"], order=5)
        self.assertEqual(inserted["order"], 5)
        self.assertEqual(self.stored(survey)["questions"][1]["questionId"], ObjectId(target["questionId"]))
        self.assertEqual(self.stored(survey)["questions"][1]["order"], 6)
        before = self.stored(survey)
        response = self.client.post(f"/surveys/{survey}/questions/from-library", json={"sourceQuestionId": source["id"],
            "beforeQuestionId": target["questionId"], "order": 5})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.stored(survey), before)
        self.assertEqual(self.client.post(f"/surveys/{survey}/questions/from-library", json={
            "sourceQuestionId": source["id"], "order": 5}).status_code, 409)

    def test_switch_preserves_instance_incoming_and_outgoing_rules(self):
        survey = self.survey()
        source = self.source()
        previous = self.add(survey, source)
        question = self.add(survey, source, required=True)
        target = self.add(survey, source)
        for q, dest in [(previous, question), (question, target)]:
            response = self.client.put(f"/surveys/{survey}/questions/{q['questionId']}/jump-rules", json={"rules": [
                {"operator": "selected", "value": q["options"][0]["optionId"], "targetQuestionId": dest["questionId"]}]})
            self.assertEqual(response.status_code, 200, response.text)
        before = self.stored(survey)
        v2 = self.derive(source, title="更新题干")
        result = self.switch(survey, question, v2)
        self.assertEqual(result.status_code, 200, result.text)
        saved = result.json()
        self.assertEqual(saved["questionId"], question["questionId"])
        self.assertEqual(saved["order"], question["order"])
        self.assertTrue(saved["required"])
        self.assertEqual(saved["jumpRules"][0]["targetQuestionId"], target["questionId"])
        self.assertEqual(self.stored(survey)["questions"][0], before["questions"][0])
        self.assertEqual(self.stored(survey)["questions"][2], before["questions"][2])
        self.assertEqual(self.client.get(f"/library/questions/{source['id']}").json(), source)

    def test_switch_rejects_broken_rules_and_can_explicitly_clear(self):
        survey = self.survey()
        source = self.source()
        question = self.add(survey, source)
        self.client.put(f"/surveys/{survey}/questions/{question['questionId']}/jump-rules", json={"rules": [
            {"operator": "selected", "value": question["options"][0]["optionId"], "targetQuestionId": None}]})
        v2 = self.derive(source, options=[source["options"][1], {"text": "梨", "order": 3}])
        before = self.stored(survey)
        self.assertEqual(self.switch(survey, question, v2).status_code, 409)
        self.assertEqual(self.stored(survey), before)
        result = self.switch(survey, question, v2, clearJumpRules=True)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["jumpRules"], [])
        v3 = self.derive(v2, type="text", options=None, validation={})
        self.assertEqual(self.switch(survey, result.json(), v3).status_code, 200)
        self.assertNotIn("options", self.stored(survey)["questions"][0])

    def test_detach_keeps_content_and_allows_edit_but_stale_request_fails(self):
        survey = self.survey()
        source = self.source()
        question = self.add(survey, source)
        path = f"/surveys/{survey}/questions/{question['questionId']}"
        before = self.stored(survey)["questions"][0]
        detached = self.post(path + "/detach", {"expectedSourceQuestionId": source["id"]}, status=200)
        self.assertNotIn("sourceQuestionId", detached)
        expected = {k: v for k, v in before.items() if k != "sourceQuestionId"}
        self.assertEqual(self.stored(survey)["questions"][0], expected)
        self.assertEqual(self.client.post(path + "/detach", json={"expectedSourceQuestionId": source["id"]}).status_code, 409)
        payload = {k: detached[k] for k in ["title", "type", "order", "required", "options", "validation"]}
        result = self.client.put(path, json={**payload, "title": "仅本问卷修改"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get(f"/library/questions/{source['id']}").json(), source)

    def test_cross_series_stale_reference_and_required_constraints(self):
        survey = self.survey()
        source = self.source("multiple", maxChoices=2)
        question = self.add(survey, source, required=True)
        self.assertEqual(self.switch(survey, question, self.source()).status_code, 422)
        zero = self.derive(source, validation={"maxChoices": 0})
        self.assertEqual(self.switch(survey, question, zero).status_code, 422)
        count = len(self.stored(survey)["questions"])
        self.assertEqual(self.client.post(f"/surveys/{survey}/questions/from-library", json={
            "sourceQuestionId": zero["id"], "required": True}).status_code, 422)
        self.assertEqual(len(self.stored(survey)["questions"]), count)
        v2 = self.derive(source, title="新版")
        self.assertEqual(self.switch(survey, question, v2).status_code, 200)
        self.assertEqual(self.switch(survey, question, source).status_code, 409)
        self.assertEqual(self.client.post(f"/surveys/{survey}/questions/{question['questionId']}/detach", json={
            "expectedSourceQuestionId": source["id"]}).status_code, 409)

    def test_permission_and_published_closed_lock_but_copy_is_allowed(self):
        survey = self.survey()
        source = self.source()
        question = self.add(survey, source)
        base = f"/surveys/{survey}/questions"
        operations = [(base + "/from-library", {"sourceQuestionId": source["id"]}),
            (base + f"/{question['questionId']}/switch-version", {"sourceQuestionId": source["id"], "expectedSourceQuestionId": source["id"]}),
            (base + f"/{question['questionId']}/detach", {"expectedSourceQuestionId": source["id"]})]
        for headers, expected in [(self.headers["other"], 404), ({"Authorization": ""}, 401)]:
            for path, payload in operations:
                self.assertEqual(self.client.post(path, json=payload, headers=headers).status_code, expected)
            self.assertEqual(self.client.post(base + f"/{question['questionId']}/save-to-library", headers=headers).status_code, expected)
        self.post(f"/surveys/{survey}/publish", {}, status=200)
        for state in ["published", "closed"]:
            if state == "closed":
                self.post(f"/surveys/{survey}/close", status=200)
            before = self.stored(survey)
            for path, payload in operations:
                self.assertEqual(self.client.post(path, json=payload).status_code, 409)
            self.post(base + f"/{question['questionId']}/save-to-library")
            self.assertEqual(self.stored(survey), before)

    def test_source_permission_invalid_payload_and_order_upper_bound(self):
        survey = self.survey()
        source = self.source("text")
        # 他人的题目即使ID已知也不能选用；本批尚未开放共享授权。
        other = self.client.post("/surveys", json={"title": "别人的问卷"}, headers=self.headers["other"]).json()
        self.assertEqual(self.client.post(f"/surveys/{other['id']}/questions/from-library", json={
            "sourceQuestionId": source["id"]}, headers=self.headers["other"]).status_code, 404)
        base = f"/surveys/{survey}/questions/from-library"
        for extra in [{"title": "伪造快照"}, {"questionId": str(ObjectId())}, {"order": 0}, {"required": "true"}, {"sourceQuestionId": "bad"}]:
            self.assertEqual(self.client.post(base, json={"sourceQuestionId": source["id"], **extra}).status_code, 422)
        self.assertEqual(self.client.post(base, json={"sourceQuestionId": str(ObjectId())}).status_code, 404)
        self.assertEqual(self.client.post("/surveys/bad/questions/from-library", json={"sourceQuestionId": source["id"]}).status_code, 400)
        question = self.add(survey, source, order=2**31 - 1)
        before = self.stored(survey)
        self.assertEqual(self.client.post(base, json={"sourceQuestionId": source["id"]}).status_code, 422)
        self.assertEqual(self.client.post(base, json={"sourceQuestionId": source["id"], "beforeQuestionId": question["questionId"]}).status_code, 422)
        self.assertEqual(self.stored(survey), before)

    def test_parallel_append_does_not_overwrite_or_duplicate_ids(self):
        survey = self.survey()
        source = self.source("text")
        def append(_):
            return self.client.post(f"/surveys/{survey}/questions/from-library", json={"sourceQuestionId": source["id"]})
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(append, range(6)))
        self.assertTrue(all(result.status_code in [201, 409] for result in results))
        success = [result.json() for result in results if result.status_code == 201]
        stored = self.stored(survey)["questions"]
        self.assertGreater(len(stored), 0)
        self.assertEqual(len(stored), len(success))
        self.assertEqual(len({q["questionId"] for q in stored}), len(stored))
        self.assertEqual(len({q["order"] for q in stored}), len(stored))

    def test_publish_between_read_and_write_is_not_overwritten(self):
        survey = self.survey()
        source = self.source("text")
        self.add(survey, source)
        before = self.stored(survey)
        def publish_then_save(database, snapshot, user_id, questions):
            database.surveys.update_one({"_id": snapshot["_id"]}, {"$set": {"status": "published"}})
            return save_questions(database, snapshot, user_id, questions)
        with patch("app.surveys.reuse.save_questions", side_effect=publish_then_save):
            response = self.client.post(f"/surveys/{survey}/questions/from-library", json={"sourceQuestionId": source["id"]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.stored(survey)["questions"], before["questions"])
        self.assertEqual(self.stored(survey)["status"], "published")
