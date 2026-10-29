"""分享与题库：推荐版本、跨用户授权、撤销和不可变问卷快照。"""
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from bson import ObjectId
from fastapi.testclient import TestClient

from app.main import app
from app.library.banks import update_bank


class SharingBankIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = os.environ.get("MONGODB_DATABASE")
        cls.name = "questionnaire_test_shares_" + uuid4().hex
        os.environ["MONGODB_DATABASE"] = cls.name
        cls.context = TestClient(app)
        try:
            cls.client = cls.context.__enter__()
        except Exception:
            cls.restore_env()
            raise
        cls.db = app.state.database
        cls.headers = {}
        for name in ["author", "reader"]:
            r = cls.client.post("/auth/register", json={"username": name, "password": "test-password-123"})
            assert r.status_code == 201, r.text
            token = cls.client.post("/auth/token", data={"username": name, "password": "test-password-123"}).json()["access_token"]
            cls.headers[name] = {"Authorization": "Bearer " + token}

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
        for name in ["questions", "question_banks", "surveys", "responses"]:
            self.db[name].delete_many({})

    def call(self, method, path, body=None, who="author", expected=200):
        r = self.client.request(method, path, headers=self.headers[who], **({"json": body} if body is not None else {}))
        self.assertEqual(r.status_code, expected, r.text)
        return r.json() if expected != 204 else None

    def question(self):
        return self.call("POST", "/library/questions", {"title": "年龄v1", "type": "number", "validation": {"minValue": 0}}, expected=201)

    def version(self, q):
        return self.call("POST", f"/library/questions/{q['id']}/versions", {"title": "年龄v2", "type": "number", "validation": {"minValue": 10}}, expected=201)

    def bank(self, who="author"):
        return self.call("POST", "/library/banks", {"name": "常用调查", "description": "题库说明"}, who, 201)

    def item(self, bank, q, who="author", **extra):
        return self.call("PUT", f"/library/banks/{bank['id']}/items/{q['rootQuestionId']}",
                         {"recommendedVersionId": q["id"], "order": 1, "category": "基础信息", **extra}, who)

    def share_question(self, q, enabled=True):
        return self.call("POST", f"/library/questions/{q['id']}/sharing", {"enabled": enabled})

    def survey(self):
        return self.call("POST", "/surveys", {"title": "接收者问卷"}, "reader", 201)

    def add(self, survey, q, expected=201, **proof):
        return self.call("POST", f"/surveys/{survey['id']}/questions/from-library", {"sourceQuestionId": q["id"], **proof}, "reader", expected)

    def test_bank_crud_owner_only_and_does_not_delete_questions(self):
        bank = self.bank()
        self.assertFalse(bank["sharingEnabled"])
        self.assertEqual(bank["items"], [])
        q = self.question()
        self.item(bank, q)
        updated = self.call("PATCH", f"/library/banks/{bank['id']}", {"name": "新题库名", "description": ""})
        self.assertEqual(updated["name"], "新题库名")
        self.assertEqual(len(updated["items"]), 1)
        self.assertEqual(len(self.call("GET", "/library/banks")), 1)
        self.assertEqual(self.call("GET", "/library/banks", who="reader"), [])
        for method, suffix, body in [("GET", "", None), ("PATCH", "", {"name": "越权"}),
                                      ("DELETE", "", None), ("POST", "/sharing", {"enabled": True})]:
            self.call(method, f"/library/banks/{bank['id']}" + suffix, body, "reader", 404)
        self.call("DELETE", f"/library/banks/{bank['id']}", expected=204)
        self.assertEqual(self.db.questions.count_documents({}), 1)
        self.call("GET", f"/library/banks/{bank['id']}", expected=404)

    def test_recommendation_updates_classification_and_order_but_not_survey(self):
        bank = self.bank()
        q1 = self.question(); q2 = self.version(q1)
        saved = self.item(bank, q1)
        reader_survey = self.survey()
        self.call("POST", f"/library/banks/{bank['id']}/sharing", {"enabled": True})
        selected = self.add(reader_survey, q1, bankShareToken=bank["shareToken"])
        original = self.db.surveys.find_one({"_id": ObjectId(reader_survey["id"])})
        updated = self.item(bank, q2, expectedRecommendedVersionId=q1["id"], category="新版分类", order=5)
        self.assertEqual(updated["items"][0]["recommendedVersionId"], q2["id"])
        self.assertEqual(updated["items"][0]["category"], "新版分类")
        self.assertEqual(updated["items"][0]["addedAt"], saved["items"][0]["addedAt"])
        self.assertEqual(updated["items"][0]["question"]["title"], q2["title"])
        self.assertEqual(self.db.surveys.find_one({"_id": original["_id"]}), original)
        self.assertEqual(selected["sourceQuestionId"], q1["id"])

    def test_item_series_duplicates_orders_and_stale_edit_are_checked(self):
        bank = self.bank(); q1 = self.question(); q2 = self.version(q1); other = self.question()
        self.item(bank, q1)
        path = f"/library/banks/{bank['id']}/items/{q1['id']}"
        self.call("PUT", path, {"recommendedVersionId": q1["id"], "order": 1}, expected=409)
        self.call("PUT", path, {"recommendedVersionId": other["id"], "expectedRecommendedVersionId": q1["id"], "order": 1}, expected=422)
        self.call("PUT", f"/library/banks/{bank['id']}/items/{other['id']}", {"recommendedVersionId": other["id"], "order": 1}, expected=409)
        self.item(bank, q2, expectedRecommendedVersionId=q1["id"])
        self.call("PUT", path, {"recommendedVersionId": q1["id"], "expectedRecommendedVersionId": q1["id"], "order": 1}, expected=409)
        self.call("DELETE", path, {"expectedRecommendedVersionId": q1["id"]}, expected=409)
        result = self.call("DELETE", path, {"expectedRecommendedVersionId": q2["id"]})
        self.assertEqual(result["items"], [])

    def test_question_share_recommends_anchor_and_allows_other_versions_without_tokens(self):
        q1 = self.question(); q2 = self.version(q1)
        token = q1["shareToken"]
        self.call("GET", f"/shared/questions/{token}", who="reader", expected=404)
        before = self.db.questions.find_one({"_id": ObjectId(q1["id"])})
        self.share_question(q1)
        shared = self.call("GET", f"/shared/questions/{token}", who="reader")
        self.assertEqual(shared["recommendedVersionId"], q1["id"])
        versions = self.call("GET", f"/shared/questions/{token}/versions", who="reader")
        self.assertEqual([q["id"] for q in versions], [q1["id"], q2["id"]])
        for q in versions:
            self.assertNotIn("shareToken", q)
            self.assertNotIn("creatorId", q)
        self.assertEqual(self.call("GET", f"/shared/questions/{token}/versions?skip=1&limit=1", who="reader")[0]["id"], q2["id"])
        self.add(self.survey(), q2, questionShareToken=token)
        after = self.db.questions.find_one({"_id": before["_id"]})
        self.assertEqual({**before, "sharingEnabled": True}, after)

    def test_question_sharing_does_not_grant_editing_or_unrelated_series(self):
        q1 = self.question(); other = self.question(); self.share_question(q1)
        for suffix, body in [("/sharing", {"enabled": True}), ("/versions", {"title": "改题", "type": "text"}),
                              ("/restore", {"restoredFromQuestionId": q1["id"]})]:
            self.call("POST", f"/library/questions/{q1['id']}" + suffix, body, "reader", 404)
        self.add(self.survey(), other, expected=404, questionShareToken=q1["shareToken"])
        self.call("GET", f"/library/questions/{q1['id']}", who="reader", expected=404)

    def test_revocation_blocks_new_use_but_keeps_used_snapshot_detachable(self):
        q1 = self.question(); q2 = self.version(q1); self.share_question(q1)
        survey = self.survey(); instance = self.add(survey, q1, questionShareToken=q1["shareToken"])
        original = self.db.surveys.find_one({"_id": ObjectId(survey["id"])})
        self.share_question(q1, False)
        self.call("GET", f"/shared/questions/{q1['shareToken']}", who="reader", expected=404)
        self.add(survey, q1, expected=404, questionShareToken=q1["shareToken"])
        base = f"/surveys/{survey['id']}/questions/{instance['questionId']}"
        self.call("POST", base + "/switch-version", {"sourceQuestionId": q2["id"], "expectedSourceQuestionId": q1["id"],
            "questionShareToken": q1["shareToken"]}, "reader", 404)
        self.assertEqual(self.db.surveys.find_one({"_id": original["_id"]}), original)
        current = self.call("GET", base + "/source", who="reader")
        self.assertEqual(current["id"], q1["id"])
        self.assertNotIn("shareToken", current)
        detached = self.call("POST", base + "/detach", {"expectedSourceQuestionId": q1["id"]}, "reader")
        self.assertNotIn("sourceQuestionId", detached)

    def test_bank_share_grants_versions_without_individual_share_and_revokes(self):
        bank = self.bank(); q1 = self.question(); q2 = self.version(q1); self.item(bank, q1)
        self.call("POST", f"/library/banks/{bank['id']}/sharing", {"enabled": True})
        shared = self.call("GET", f"/shared/banks/{bank['shareToken']}", who="reader")
        self.assertNotIn("shareToken", shared)
        self.assertNotIn("creatorId", shared)
        self.assertEqual(shared["items"][0]["question"]["id"], q1["id"])
        versions_path = f"/shared/banks/{bank['shareToken']}/questions/{q1['id']}/versions"
        self.assertEqual(len(self.call("GET", versions_path, who="reader")), 2)
        survey = self.survey()
        instance = self.add(survey, q2, bankShareToken=bank["shareToken"])
        self.call("POST", f"/library/banks/{bank['id']}/sharing", {"enabled": False})
        self.call("GET", versions_path, who="reader", expected=404)
        self.add(survey, q2, expected=404, bankShareToken=bank["shareToken"])
        self.assertEqual(self.db.surveys.find_one({"_id": ObjectId(survey["id"])})["questions"][0]["sourceQuestionId"], ObjectId(q2["id"]))
        self.assertEqual(instance["title"], q2["title"])

    def test_private_foreign_collection_tracks_permission_and_cannot_reshare(self):
        q = self.question(); self.share_question(q)
        private = self.bank("reader")
        saved = self.item(private, q, "reader", questionShareToken=q["shareToken"])
        self.assertNotIn("accessProof", saved["items"][0])
        self.assertNotIn(q["shareToken"], str(saved))
        self.call("POST", f"/library/banks/{private['id']}/sharing", {"enabled": True}, "reader", 409)
        survey = self.survey(); self.add(survey, q, bankId=private["id"])
        self.share_question(q, False)
        detail = self.call("GET", f"/library/banks/{private['id']}", who="reader")
        self.assertIsNone(detail["items"][0]["question"])
        self.add(survey, q, expected=404, bankId=private["id"])
        self.call("DELETE", f"/library/banks/{private['id']}/items/{q['id']}", {"expectedRecommendedVersionId": q["id"]}, "reader")

    def test_shared_bank_cannot_receive_foreign_items_and_uncollected_root_is_blocked(self):
        q = self.question(); self.share_question(q)
        bank = self.bank("reader")
        self.call("POST", f"/library/banks/{bank['id']}/sharing", {"enabled": True}, "reader")
        self.call("PUT", f"/library/banks/{bank['id']}/items/{q['id']}", {"recommendedVersionId": q["id"], "order": 1,
            "questionShareToken": q["shareToken"]}, "reader", 409)
        author_bank = self.bank(); self.call("POST", f"/library/banks/{author_bank['id']}/sharing", {"enabled": True})
        self.add(self.survey(), q, expected=404, bankShareToken=author_bank["shareToken"])
        self.call("GET", f"/shared/banks/{author_bank['shareToken']}/questions/{q['id']}/versions", who="reader", expected=404)

    def test_removal_or_deletion_invalidates_bank_grant_without_changing_instances(self):
        q = self.question(); bank = self.bank(); self.item(bank, q)
        self.call("POST", f"/library/banks/{bank['id']}/sharing", {"enabled": True})
        survey = self.survey(); self.add(survey, q, bankShareToken=bank["shareToken"])
        snapshot = self.db.surveys.find_one({"_id": ObjectId(survey["id"])})
        self.call("DELETE", f"/library/banks/{bank['id']}/items/{q['id']}", {"expectedRecommendedVersionId": q["id"]})
        self.add(survey, q, expected=404, bankShareToken=bank["shareToken"])
        self.item(bank, q)
        self.call("DELETE", f"/library/banks/{bank['id']}", expected=204)
        self.add(survey, q, expected=404, bankShareToken=bank["shareToken"])
        self.assertEqual(self.db.surveys.find_one({"_id": snapshot["_id"]}), snapshot)

    def test_shared_version_switch_requires_valid_grant_and_same_series(self):
        q1 = self.question(); q2 = self.version(q1); self.share_question(q1)
        survey = self.survey(); instance = self.add(survey, q1, questionShareToken=q1["shareToken"])
        body = {"sourceQuestionId": q2["id"], "expectedSourceQuestionId": q1["id"], "questionShareToken": q1["shareToken"]}
        result = self.call("POST", f"/surveys/{survey['id']}/questions/{instance['questionId']}/switch-version", body, "reader")
        self.assertEqual(result["sourceQuestionId"], q2["id"])
        self.assertEqual(result["questionId"], instance["questionId"])

    def test_bank_conditional_write_preserves_concurrent_change(self):
        bank = self.bank(); q = self.question()
        def concurrent(database, snapshot, changes):
            database.question_banks.update_one({"_id": snapshot["_id"]}, {"$set": {"name": "另一个请求已修改"}})
            return update_bank(database, snapshot, changes)
        with patch("app.library.banks.update_bank", side_effect=concurrent):
            self.call("PUT", f"/library/banks/{bank['id']}/items/{q['id']}", {"recommendedVersionId": q["id"], "order": 1}, expected=409)
        row = self.db.question_banks.find_one({"_id": ObjectId(bank["id"])})
        self.assertEqual(row["name"], "另一个请求已修改")
        self.assertEqual(row["items"], [])

    def test_recommendations_are_entry_specific_and_do_not_follow_latest(self):
        q1 = self.question(); self.share_question(q1)
        q2 = self.version(q1); self.share_question(q2)
        q3 = self.version(q2)
        for anchor in [q1, q2]:
            shared = self.call("GET", f"/shared/questions/{anchor['shareToken']}", who="reader")
            self.assertEqual(shared["recommendedVersionId"], anchor["id"])
            self.assertEqual(len(self.call("GET", f"/shared/questions/{anchor['shareToken']}/versions", who="reader")), 3)
        b1 = self.bank(); b2 = self.bank()
        self.item(b1, q1); self.item(b2, q2)
        self.item(b1, q3, expectedRecommendedVersionId=q1["id"])
        self.assertEqual(self.call("GET", f"/library/banks/{b2['id']}")["items"][0]["recommendedVersionId"], q2["id"])

    def test_strict_input_and_login_requirements(self):
        q = self.question(); bank = self.bank()
        self.call("POST", f"/library/questions/{q['id']}/sharing", {"enabled": "true"}, expected=422)
        self.call("POST", "/library/banks", {"name": "伪造", "creatorId": str(ObjectId())}, expected=422)
        self.call("PATCH", f"/library/banks/{bank['id']}", {}, expected=422)
        self.call("PATCH", f"/library/banks/{bank['id']}", {"name": None}, expected=422)
        self.call("GET", "/library/banks?limit=101", expected=422)
        self.call("GET", "/library/banks/bad", expected=400)
        self.call("PUT", f"/library/banks/{bank['id']}/items/{q['id']}", {"recommendedVersionId": q["id"], "order": 1,
            "questionShareToken": "x", "bankShareToken": "y"}, expected=422)
        self.share_question(q)
        self.assertEqual(self.client.get(f"/shared/questions/{q['shareToken']}").status_code, 401)
