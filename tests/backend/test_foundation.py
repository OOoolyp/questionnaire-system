"""第二阶段第一批：真实隔离数据库的迁移、索引和兼容验证。"""
import os
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from bson import ObjectId
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from pydantic import ValidationError, TypeAdapter
from fastapi import HTTPException

from app.core.database import prepare_database
from app.library.schemas import LibraryQuestionContent, LibraryQuestionRead, QuestionBankRead
from app.surveys.questions import QuestionInput, build_question


class FoundationModelsTests(unittest.TestCase):
    def test_library_type_validation_and_saved_version(self):
        identifier = str(ObjectId())
        saved = LibraryQuestionRead(id=identifier, rootQuestionId=identifier,
            parentQuestionId=None, version=1, creatorId=str(ObjectId()),
            title="年龄", type="number", validation={"minValue": 0},
            shareToken="token", createdAt=datetime.now(timezone.utc))
        self.assertFalse(saved.sharingEnabled)
        self.assertFalse(saved.validation["integerOnly"])
        for payload in [dict(title="年龄", type="number", validation={"minValue": 20, "maxValue": 10}),
                        dict(title="选项", type="single", options=[]),
                        dict(title="文本", type="text", options=[])]:
            with self.assertRaises(ValidationError):
                LibraryQuestionContent(**payload)
        with self.assertRaises(ValidationError):
            LibraryQuestionRead.model_validate({**saved.model_dump(), "version": 2})

    def test_bank_duplicate_roots(self):
        now = datetime.now(timezone.utc)
        root = str(ObjectId())
        payload = dict(id=str(ObjectId()), creatorId=str(ObjectId()), name="题库",
            shareToken="bank", createdAt=now, updatedAt=now)
        item = dict(rootQuestionId=root, recommendedVersionId=root, order=1, addedAt=now)
        with self.assertRaises(ValidationError):
            QuestionBankRead(**payload, items=[item, {**item, "order": 2}])

    def test_edit_reference_preserved_and_content_protected(self):
        adapter = TypeAdapter(QuestionInput)
        payload = dict(type="text", title="建议", order=1)
        question = build_question(adapter.validate_python(payload))
        question["sourceQuestionId"] = ObjectId()
        edited = build_question(adapter.validate_python({**payload, "order": 2}), question)
        self.assertEqual(edited["sourceQuestionId"], question["sourceQuestionId"])
        with self.assertRaises(HTTPException) as error:
            build_question(adapter.validate_python({**payload, "title": "改题"}), question)
        self.assertEqual(error.exception.status_code, 409)
        with self.assertRaises(ValidationError):
            adapter.validate_python({**payload, "sourceQuestionId": str(ObjectId())})


class FoundationDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.client = MongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017"),
                                  serverSelectionTimeoutMS=3000)
        self.client.admin.command("ping")
        self.db = self.client["questionnaire_test_foundation_" + uuid4().hex]

    def tearDown(self):
        if os.environ.get("KEEP_TEST_DATA") == "0":
            self.client.drop_database(self.db.name)
        self.client.close()

    def test_migration_is_repeatable_and_preserves_existing_data(self):
        old = {"_id": ObjectId(), "shareToken": "old", "status": "published",
               "questions": [{"questionId": ObjectId(), "title": "原题"}]}
        future = {"_id": ObjectId(), "rootSurveyId": ObjectId(), "parentSurveyId": ObjectId(),
                  "version": 4, "shareToken": "future", "questions": []}
        response = {"_id": ObjectId(), "surveyId": old["_id"], "answers": []}
        self.db.surveys.insert_many([old, future])
        self.db.responses.insert_one(response)
        prepare_database(self.db)
        prepare_database(self.db)
        self.assertEqual(self.db.surveys.find_one({"_id": old["_id"]}),
            {**old, "rootSurveyId": old["_id"], "parentSurveyId": None, "version": 1})
        self.assertEqual(self.db.surveys.find_one({"_id": future["_id"]}), future)
        self.assertEqual(self.db.responses.find_one(), response)

    def test_partial_migration_is_not_silently_reset(self):
        partial = {"_id": ObjectId(), "version": 3}
        self.db.surveys.insert_one(partial)
        with self.assertRaises(RuntimeError):
            prepare_database(self.db)
        self.assertEqual(self.db.surveys.find_one(), partial)

    def test_indexes_enforce_versions_shares_and_partial_uniqueness(self):
        prepare_database(self.db)
        root = ObjectId()
        for collection, root_field in [(self.db.questions, "rootQuestionId"),
                                        (self.db.surveys, "rootSurveyId")]:
            collection.insert_one({root_field: root, "version": 1, "shareToken": "one"})
            with self.assertRaises(DuplicateKeyError):
                collection.insert_one({root_field: root, "version": 1, "shareToken": "two"})
            with self.assertRaises(DuplicateKeyError):
                collection.insert_one({root_field: root, "version": 2, "shareToken": "one"})
            collection.insert_one({root_field: root, "version": 2, "shareToken": "two"})
        self.db.question_banks.insert_one({"shareToken": "bank"})
        with self.assertRaises(DuplicateKeyError):
            self.db.question_banks.insert_one({"shareToken": "bank"})
        record = {"surveyId": ObjectId(), "respondentId": ObjectId(), "repeatRestricted": True}
        self.db.responses.insert_one(dict(record))
        with self.assertRaises(DuplicateKeyError):
            self.db.responses.insert_one(dict(record))
        for _ in range(2):
            self.db.responses.insert_one({**record, "repeatRestricted": False})
        indexes = self.db.surveys.index_information()
        self.assertIn("questions.sourceQuestionId_1", indexes)
        self.assertEqual(self.db.responses.index_information()["one_response_per_user"]["partialFilterExpression"],
                         {"repeatRestricted": True})

    def test_source_index_finds_versions_in_embedded_array(self):
        prepare_database(self.db)
        source = ObjectId()
        identifiers = [ObjectId(), ObjectId()]
        for i, identifier in enumerate(identifiers):
            self.db.surveys.insert_one({"_id": identifier, "rootSurveyId": identifier,
                "version": 1, "shareToken": str(identifier), "questions": [
                    {"questionId": ObjectId(), **({"sourceQuestionId": source} if i == 0 else {})}]})
        found = list(self.db.surveys.find({"questions.sourceQuestionId": source})
                     .hint("questions.sourceQuestionId_1"))
        self.assertEqual([row["_id"] for row in found], identifiers[:1])
