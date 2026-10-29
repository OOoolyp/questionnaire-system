"""真实 MongoDB 验收；默认保留本批数据库，KEEP_TEST_DATA=0 才清理。"""
import os
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


class QuestionAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.previous = os.environ.get('MONGODB_DATABASE')
        self.name = 'qa_analytics_' + uuid4().hex
        os.environ['MONGODB_DATABASE'] = self.name
        self.context = TestClient(app)
        self.client = self.context.__enter__()
        self.db = app.state.database
        self.headers = {}
        for who in ['owner', 'other']:
            self.client.post('/auth/register', json={'username': who, 'password': 'test-password-123'}).raise_for_status()
            token = self.client.post('/auth/token', data={'username': who, 'password': 'test-password-123'}).json()['access_token']
            self.headers[who] = {'Authorization': 'Bearer ' + token}

    def tearDown(self):
        try:
            if os.environ.get('KEEP_TEST_DATA') == '0':
                self.db.client.drop_database(self.name)
        finally:
            self.context.__exit__(None, None, None)
            if self.previous is None:
                os.environ.pop('MONGODB_DATABASE', None)
            else:
                os.environ['MONGODB_DATABASE'] = self.previous

    def call(self, method, path, body=None, who='owner', expected=200):
        r = self.client.request(method, path, headers=self.headers[who], **({'json': body} if body is not None else {}))
        self.assertEqual(r.status_code, expected, r.text)
        return r.json()

    def source(self, kind='number'):
        body = {'title': '统计题', 'type': kind, 'validation': {}}
        if kind in ['single', 'multiple']:
            body['options'] = [{'text': t, 'order': i} for i, t in enumerate(['甲', '乙', '丙'], 1)]
        return self.call('POST', '/library/questions', body, expected=201)

    def version(self, q):
        return self.call('POST', f"/library/questions/{q['id']}/versions", {
            'title': '统计题新版', 'type': q['type'], 'validation': {}, **({'options': q['options']} if q['options'] else {})}, expected=201)

    def survey(self, q, who='owner', copies=1, **proof):
        s = self.call('POST', '/surveys', {'title': '保密标题' if who == 'other' else '我的调查', 'allowRepeat': True}, who, 201)
        items = [self.call('POST', f"/surveys/{s['id']}/questions/from-library", {'sourceQuestionId': q['id'], **proof}, who, 201) for _ in range(copies)]
        return s, items

    def publish(self, s, who='owner'):
        return self.call('POST', f"/surveys/{s['id']}/publish", {}, who)

    def submit(self, s, items, values, who='owner'):
        answers = []
        for q, value in zip(items, values):
            if value is None:
                continue
            answers.append({'questionId': q['questionId'], **({'selectedOptionIds': value} if q['type'] in ['single', 'multiple'] else {'value': value})})
        return self.call('POST', f"/survey/{s['shareToken']}/responses", {'answers': answers}, who, 201)

    def stats(self, q, who='owner', query=''):
        return self.call('GET', f"/analytics/questions/{q['id']}/statistics{query}", who=who)

    def usages(self, q, who='owner', query=''):
        return self.call('GET', f"/analytics/questions/{q['id']}/usage{query}", who=who)

    def test_numeric_cross_surveys_repeated_instances_closed_and_draft(self):
        q = self.source()
        s, items = self.survey(q, copies=2)
        s = self.publish(s)
        self.submit(s, items, [10, 20]); self.submit(s, items, [30, None])
        self.call('POST', f"/surveys/{s['id']}/close", {})
        second, second_items = self.survey(q); second = self.publish(second)
        self.submit(second, second_items, [40]); self.submit(second, second_items, [None])
        self.survey(q)
        data = self.stats(q)
        self.assertEqual([data[k] for k in ['surveyVersionCount', 'surveySeriesCount', 'instanceCount', 'submissionCount', 'answeredSubmissionCount', 'answerCount']], [3, 3, 4, 4, 3, 4])
        self.assertEqual([data[k] for k in ['average', 'minimum', 'maximum']], [25, 10, 40])
        self.assertEqual(sum(b['count'] for b in data['distribution']), 4)
        use = self.usages(q)
        self.assertEqual((use['totalSurveyVersions'], use['totalInstances']), (3, 4))

    def test_survey_versions_same_local_id_never_mix_source_versions(self):
        v1 = self.source(); v2 = self.version(v1)
        s1, items1 = self.survey(v1); s1 = self.publish(s1); self.submit(s1, items1, [10])
        s2 = self.call('POST', f"/surveys/{s1['id']}/versions", {}, expected=201)
        q2 = self.call('POST', f"/surveys/{s2['id']}/questions/{items1[0]['questionId']}/switch-version", {
            'sourceQuestionId': v2['id'], 'expectedSourceQuestionId': v1['id']})
        s2 = self.publish(s2); self.submit(s2, [q2], [90])
        self.assertEqual(self.stats(v1)['average'], 10)
        self.assertEqual(self.stats(v2)['average'], 90)
        series = self.usages(v1, query='?scope=series')
        self.assertEqual((series['totalSurveyVersions'], series['totalSurveySeries']), (2, 1))
        self.assertEqual(self.usages(v1)['totalSurveyVersions'], 1)

    def test_multiple_versions_inside_same_survey_and_detach(self):
        v1 = self.source(); v2 = self.version(v1)
        s, items = self.survey(v1, copies=3)
        q2 = self.call('POST', f"/surveys/{s['id']}/questions/{items[1]['questionId']}/switch-version", {'sourceQuestionId': v2['id'], 'expectedSourceQuestionId': v1['id']})
        detached = self.call('POST', f"/surveys/{s['id']}/questions/{items[2]['questionId']}/detach", {'expectedSourceQuestionId': v1['id']})
        s = self.publish(s); self.submit(s, [items[0], q2, detached], [5, 50, 500])
        self.assertEqual(self.stats(v1)['average'], 5)
        self.assertEqual(self.stats(v2)['average'], 50)
        self.assertEqual(self.usages(v1, query='?scope=series')['totalInstances'], 2)

    def test_choice_distribution_includes_zero_and_multiple_counts(self):
        for kind in ['single', 'multiple']:
            q = self.source(kind); s, items = self.survey(q); s = self.publish(s)
            ids = [o['optionId'] for o in q['options']]
            self.submit(s, items, [[ids[0]]]); self.submit(s, items, [ids[:2] if kind == 'multiple' else [ids[1]]])
            data = self.stats(q)
            self.assertEqual(data['answerCount'], 2)
            self.assertEqual([o['count'] for o in data['options']], [2, 1, 0] if kind == 'multiple' else [1, 1, 0])
            self.assertIsNone(data['average'])

    def test_text_top_twenty_and_escaped_content_preserved_as_data(self):
        q = self.source('text'); s, items = self.survey(q); s = self.publish(s)
        for value in ['<script>alert(1)</script>'] * 3 + [f'文本{i:02}' for i in range(21)]:
            self.submit(s, items, [value])
        data = self.stats(q)
        self.assertEqual(data['answerCount'], 24)
        self.assertEqual(len(data['textFrequencies']), 20)
        self.assertEqual(data['textFrequencies'][0], {'value': '<script>alert(1)</script>', 'count': 3})
        self.assertEqual(data['otherTextAnswerCount'], 2)

    def test_decimal_negative_boundaries_and_distribution_limit(self):
        q = self.source(); s, items = self.survey(q); s = self.publish(s)
        for value in [-0.11, -0.1, 0, 0.1, 0.3]:
            self.submit(s, items, [value])
        data = self.stats(q, query='?bucket_size=0.1')
        self.assertEqual([float(b['lower']) for b in data['distribution']], [-0.2, -0.1, 0, 0.1, 0.3])
        for value in range(1, 102):
            self.submit(s, items, [value])
        data = self.stats(q, query='?bucket_size=0.1')
        self.assertTrue(data['distributionTruncated']); self.assertEqual(len(data['distribution']), 100)
        self.assertEqual(self.stats(q, query='?bucket_size=1000')['distributionTruncated'], False)

    def test_author_tracks_external_use_but_cannot_read_external_answers(self):
        q = self.source()
        shared = self.call('POST', f"/library/questions/{q['id']}/sharing", {'enabled': True})
        s, items = self.survey(q, 'other', questionShareToken=shared['shareToken']); s = self.publish(s, 'other')
        self.submit(s, items, [900], 'other')
        usage = self.usages(q)
        self.assertEqual(usage['restrictedSurveyVersions'], 1)
        row = usage['items'][0]
        self.assertIsNone(row['title']); self.assertIsNone(row['createdAt']); self.assertFalse(row['canViewResults'])
        self.assertNotIn('保密标题', str(usage)); self.assertNotIn('shareToken', str(usage))
        self.assertEqual(self.stats(q)['answerCount'], 0)
        self.call('GET', f"/surveys/{s['id']}/statistics", expected=404)
        self.assertEqual(self.stats(q, 'other')['average'], 900)

    def test_consumer_own_reference_survives_revocation_and_only_sees_own_usage(self):
        q = self.source(); self.survey(q)
        shared = self.call('POST', f"/library/questions/{q['id']}/sharing", {'enabled': True})
        s, items = self.survey(q, 'other', questionShareToken=shared['shareToken']); s = self.publish(s, 'other'); self.submit(s, items, [7], 'other')
        self.call('POST', f"/library/questions/{q['id']}/sharing", {'enabled': False})
        self.assertEqual(self.usages(q, 'other', '?scope=series')['totalSurveyVersions'], 1)
        self.assertEqual(self.stats(q, 'other')['average'], 7)
        v2 = self.version(q)
        self.call('GET', f"/analytics/questions/{v2['id']}/statistics", who='other', expected=404)

    def test_pagination_empty_and_query_authorization(self):
        q = self.source()
        self.assertEqual(self.usages(q)['items'], [])
        self.assertEqual(self.stats(q)['answerCount'], 0)
        for _ in range(3): self.survey(q)
        a = self.usages(q, query='?limit=2'); b = self.usages(q, query='?limit=2&skip=2')
        self.assertEqual((len(a['items']), len(b['items']), b['totalSurveyVersions']), (2, 1, 3))
        self.assertTrue({s['surveyId'] for s in a['items']}.isdisjoint(s['surveyId'] for s in b['items']))
        for tail in ['usage?scope=all', 'usage?skip=-1', 'usage?limit=101', 'statistics?bucket_size=0', 'statistics?bucket_size=-1', 'statistics?bucket_size=nan', 'statistics?bucket_size=inf']:
            self.call('GET', f"/analytics/questions/{q['id']}/{tail}", expected=422)
        self.call('GET', f"/analytics/questions/{q['id']}/usage", who='other', expected=404)
        self.assertEqual(self.client.get(f"/analytics/questions/{q['id']}/statistics").status_code, 401)
        self.call('GET', '/analytics/questions/invalid/usage', expected=400)

    def test_large_finite_numbers_and_tiny_bucket_remain_json_serializable(self):
        q = self.source(); s, items = self.survey(q); s = self.publish(s)
        for value in [1e308, 1e308]: self.submit(s, items, [value])
        data = self.stats(q, query='?bucket_size=1e-300')
        self.assertEqual(data['average'], 1e308)
        self.assertEqual(data['distribution'][0]['count'], 2)


if __name__ == '__main__':
    unittest.main()
