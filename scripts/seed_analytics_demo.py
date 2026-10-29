"""保留的前端验收数据：只创建一次，不清库、不覆盖已有记录。

运行：python scripts/seed_analytics_demo.py
随后用 MONGODB_DATABASE=questionnaire_demo_usage 启动应用。
本地 manifest 位于 var/analytics-demo.json，不包含登录令牌。
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from app.main import app

DATABASE = 'questionnaire_demo_usage'
PASSWORD = 'Demo-usage-2026!'
MANIFEST = ROOT / 'var' / 'analytics-demo.json'


def main():
    os.environ['MONGODB_DATABASE'] = DATABASE
    with TestClient(app) as client:
        if MANIFEST.exists():
            saved = json.loads(MANIFEST.read_text(encoding='utf-8'))
            from bson import ObjectId
            if all(app.state.database.questions.find_one({'_id': ObjectId(q)}) for q in saved['questions'].values()):
                print(json.dumps(saved, ensure_ascii=False, indent=2))
                return
            raise RuntimeError('已有演示清单与数据库不一致，请检查；脚本不会覆盖或清空数据。')
        headers = {}
        for who in ['demo_owner', 'demo_reader', 'demo_respondent']:
            result = client.post('/auth/register', json={'username': who, 'password': PASSWORD})
            if result.status_code not in [201, 409]: result.raise_for_status()
            login = client.post('/auth/token', data={'username': who, 'password': PASSWORD})
            login.raise_for_status()
            headers[who] = {'Authorization': 'Bearer ' + login.json()['access_token']}

        def call(method, path, body=None, who='demo_owner'):
            response = client.request(method, path, headers=headers[who], **({'json': body} if body is not None else {}))
            if response.is_error: raise RuntimeError(f'{method} {path}: {response.status_code} {response.text}')
            return response.json()

        def question(title, kind, options=None, parent=None):
            body = {'title': title, 'type': kind, 'validation': {}}
            if options: body['options'] = [{'text': text, 'order': i} for i, text in enumerate(options, 1)]
            return call('POST', f"/library/questions/{parent['id']}/versions" if parent else '/library/questions', body)

        hours = question('每周自主学习时长（小时）', 'number')
        hours_v2 = question('每周课外自主学习时长（小时，不含课程作业）', 'number', parent=hours)
        channel = question('最常使用的学习资源', 'single', ['教学视频', '教材与书籍', '同学讨论', '其他'])
        needs = question('希望学校增加哪些学习支持？', 'multiple', ['答疑辅导', '安静自习室', '线上资源', '学习小组'])
        advice = question('你最希望改善的一件事', 'text')
        questions = [hours, channel, needs, advice]
        bank = call('POST', '/library/banks', {'name': '学习体验调查题库', 'description': '使用追踪与统计演示；数字题推荐 v2，历史问卷仍保留 v1。'})
        for order, q in enumerate([hours_v2, channel, needs, advice], 1):
            call('PUT', f"/library/banks/{bank['id']}/items/{q['rootQuestionId']}", {'recommendedVersionId': q['id'], 'category': '学习体验', 'order': order})
        call('POST', f"/library/banks/{bank['id']}/sharing", {'enabled': True})
        shared = call('POST', f"/library/questions/{hours['id']}/sharing", {'enabled': True})

        def survey(title, qs, who='demo_owner', proof=None):
            s = call('POST', '/surveys', {'title': title, 'description': '保留的验收演示数据，可查看统计、来源版本与引用记录。', 'allowRepeat': True}, who)
            items = [call('POST', f"/surveys/{s['id']}/questions/from-library", {'sourceQuestionId': q['id'], **(proof or {})}, who) for q in qs]
            return s, items

        def submit(s, items, row, who='demo_respondent'):
            answers = []
            for q, value in zip(items, row):
                if value is None: continue
                selected = [q['options'][i]['optionId'] for i in value] if q['type'] in ['single', 'multiple'] else None
                answers.append({'questionId': q['questionId'], **({'selectedOptionIds': selected} if selected is not None else {'value': value})})
            call('POST', f"/survey/{s['shareToken']}/responses", {'answers': answers}, who)

        surveys = []
        for cohort, values in [('计算机学院', [0, 2, 4, 6, 8, 10, 12, 15, 20, 25, 30, None]), ('管理学院', [3, 5, 7, 9, 12, 18, 24, 36])]:
            s, items = survey(f'{cohort} · 学习体验调查', questions)
            s = call('POST', f"/surveys/{s['id']}/publish", {})
            for i, hours_value in enumerate(values):
                submit(s, items, [hours_value, [i % 3], [0, 2] if i % 2 else [1, 2, 3], ['增加自习空间', '延长图书馆开放时间', '提供课程回放', '增加自习空间', '更多答疑机会'][i % 5]])
            surveys.append(s['id'])
            if cohort == '计算机学院':
                call('POST', f"/surveys/{s['id']}/close", {})
                draft = call('POST', f"/surveys/{s['id']}/versions", {})
                call('POST', f"/surveys/{draft['id']}/questions/{items[0]['questionId']}/switch-version", {'sourceQuestionId': hours_v2['id'], 'expectedSourceQuestionId': hours['id']})
                surveys.append(draft['id'])
        double, items = survey('期中与期末学习时长 · 同题两处引用', [hours, hours])
        double = call('POST', f"/surveys/{double['id']}/publish", {})
        for row in [[8, 16], [12, 20], [None, 24]]: submit(double, items, row)
        surveys.append(double['id'])
        other, items = survey('其他作者的问卷（不开放答卷）', [hours], 'demo_reader', {'questionShareToken': shared['shareToken']})
        other = call('POST', f"/surveys/{other['id']}/publish", {}, 'demo_reader')
        for row in [[100], [200]]: submit(other, items, row)
        draft, _ = survey('下学期调查 · 待发布草稿', [hours, needs]); surveys.append(draft['id'])

        saved = {'database': DATABASE, 'username': 'demo_owner', 'password': PASSWORD,
                 'readerUsername': 'demo_reader', 'questions': {'number': hours['id'], 'numberV2': hours_v2['id'], 'single': channel['id'], 'multiple': needs['id'], 'text': advice['id']},
                 'surveys': surveys, 'bankId': bank['id'],
                 'analysisPath': f"/ui/#/question-analysis/{hours['id']}",
                 'expectedNumber': {'answerCount': 24, 'submissionCount': 23, 'answeredSubmissionCount': 22, 'average': 326 / 24},
                 'note': '演示库及答卷持续保留。外部问卷的 100 和 200 不计入 demo_owner 的统计。'}
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(saved, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
