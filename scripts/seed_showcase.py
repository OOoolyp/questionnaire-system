"""在现有演示库增量创建完整成果账号；不清库，按操作记账以便重复运行。"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from app.main import app

MANIFEST = ROOT / 'var/showcase.json'
BASE = ROOT / 'var/analytics-demo.json'
USERNAME = 'showcase'
PASSWORD = 'Showcase-2026!'


def main():
    if not BASE.exists():
        raise RuntimeError('请先运行 scripts/seed_analytics_demo.py，使用已有演示数据库。')
    base = json.loads(BASE.read_text(encoding='utf-8'))
    os.environ['MONGODB_DATABASE'] = base['database']
    saved = json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.exists() else {
        'database': base['database'], 'username': USERNAME, 'password': PASSWORD, 'operations': {}}
    if saved['database'] != base['database']:
        raise RuntimeError('已有展示账号清单指向其他数据库，停止以免写错库。')

    def persist():
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding='utf-8')

    with TestClient(app) as client:
        headers = {}

        def login(who, password=PASSWORD):
            r = client.post('/auth/register', json={'username': who, 'password': password})
            if r.status_code not in (201, 409): r.raise_for_status()
            r = client.post('/auth/token', data={'username': who, 'password': password})
            r.raise_for_status()
            headers[who] = {'Authorization': 'Bearer ' + r.json()['access_token']}

        login(USERNAME)
        login('demo_owner', base['password'])
        login('demo_reader', base['password'])
        students = [f'showcase_student_{i:02}' for i in range(1, 25)]
        for student in students: login(student)

        def read(path, who=USERNAME):
            r = client.get(path, headers=headers[who]); r.raise_for_status(); return r.json()

        def once(key, method, path, body=None, who=USERNAME):
            if key in saved['operations']: return saved['operations'][key]
            r = client.request(method, path, headers=headers[who], **({'json': body} if body is not None else {}))
            if r.is_error: raise RuntimeError(f'{key}: {r.status_code} {r.text}')
            saved['operations'][key] = r.json()
            persist()
            return r.json()

        def question(key, title, kind, options=None, validation=None, parent=None):
            payload = {'title': title, 'type': kind, 'validation': validation or {}}
            if options is not None:
                payload['options'] = [{'text': t, 'order': i} for i, t in enumerate(options, 1)]
            elif parent and parent['options']:
                payload['options'] = parent['options']
            return once(key, 'POST', f"/library/questions/{parent['id']}/versions" if parent else '/library/questions', payload)

        satisfaction = question('satisfaction_v1', '你对学校目前的学习支持服务满意吗？', 'single', ['满意', '一般', '不满意'])
        sat2 = question('satisfaction_v2', '综合考虑答疑、空间与线上资源，你对学习支持服务满意吗？', 'single', parent=satisfaction)
        sat3 = question('satisfaction_v3', '【访谈分支】你对本学期学习支持服务的整体感受如何？', 'single', parent=satisfaction)
        sat4 = once('satisfaction_restore_v4', 'POST', f"/library/questions/{sat3['id']}/restore", {'restoredFromQuestionId': satisfaction['id']})
        hours = question('hours_v1', '你每周用于自主学习的时间是多少小时？', 'number', validation={'minValue': 0, 'maxValue': 80})
        hours2 = question('hours_v2', '不含课程作业，你每周课外自主学习多少小时？', 'number', validation={'minValue': 0, 'maxValue': 100}, parent=hours)
        support = question('support', '你希望优先增加哪些学习支持？（最多选三项）', 'multiple', ['课程答疑', '自习空间', '线上资源', '学习小组'], {'minChoices': 1, 'maxChoices': 3})
        advice = question('advice', '请写下你最希望改善的一件事', 'text', validation={'maxLength': 200})
        gate = question('library_gate', '你本学期使用过学校图书馆吗？', 'single', ['使用过', '没有使用过'])
        visits = question('library_visits', '你平均每周到图书馆几次？', 'number', validation={'minValue': 0, 'maxValue': 7, 'integerOnly': True})
        shared = once('share_satisfaction_v1', 'POST', f"/library/questions/{satisfaction['id']}/sharing", {'enabled': True})

        def survey(key, title, description, anonymous=True, repeat=False):
            return once(key, 'POST', '/surveys', {'title': title, 'description': description, 'allowAnonymous': anonymous, 'allowRepeat': repeat})

        def add(key, s, q, required=False, **proof):
            return once(key, 'POST', f"/surveys/{s['id']}/questions/from-library", {'sourceQuestionId': q['id'], 'required': required, **proof})

        def publish(key, s): return once(key, 'POST', f"/surveys/{s['id']}/publish", {})

        def submit(key, s, items, values, student, anonymous=False):
            answers = []
            for q, value in zip(items, values):
                if value is None: continue
                value_data = {'selectedOptionIds': [q['options'][i]['optionId'] for i in value]} if q['type'] in ('single', 'multiple') else {'value': value}
                answers.append({'questionId': q['questionId'], **value_data})
            return once(key, 'POST', f"/survey/{s['shareToken']}/responses", {'isAnonymous': anonymous, 'answers': answers}, student)

        common = [satisfaction, hours, support, advice]
        notes = ['延长图书馆开放时间', '增加期末答疑场次', '提供课程录像和字幕', '增加安静自习空间', '组织跨专业学习小组', '完善线上资料检索']
        s1 = survey('survey_main_v1', '01｜校园学习体验调研 · 秋季', '第一轮调研，保留旧版题目与历史答卷。查看统计后，可进入版本历史对比新版。')
        first_items = [add(f'main_v1_q{i}', s1, q, i != 3) for i, q in enumerate(common)]
        pub1 = publish('publish_main_v1', s1)
        for i in range(24):
            submit(f'main_v1_answer{i}', pub1, first_items, [[0 if i < 12 else 1 if i < 20 else 2], [2, 4, 6, 8, 10, 12, 16, 20][i % 8], [0, 2] if i % 2 else [1, 2, 3], notes[i % 6]], students[i], i % 4 == 0)
        once('close_main_v1', 'POST', f"/surveys/{s1['id']}/close", {})
        s2 = once('survey_main_v2', 'POST', f"/surveys/{s1['id']}/versions", {})
        qsat2 = once('main_v2_switch_sat', 'POST', f"/surveys/{s2['id']}/questions/{first_items[0]['questionId']}/switch-version", {'expectedSourceQuestionId': satisfaction['id'], 'sourceQuestionId': sat2['id']})
        qhours2 = once('main_v2_switch_hours', 'POST', f"/surveys/{s2['id']}/questions/{first_items[1]['questionId']}/switch-version", {'expectedSourceQuestionId': hours['id'], 'sourceQuestionId': hours2['id']})
        once('main_v2_description', 'PATCH', f"/surveys/{s2['id']}", {'description': '第二轮正在收集：满意度和时长题使用 v2，其他题继续复用原版本。每位用户在这个问卷版本可提交一次。'})
        pub2 = publish('publish_main_v2', s2)
        for i in range(18):
            submit(f'main_v2_answer{i}', pub2, [qsat2, qhours2, *first_items[2:]], [[0 if i < 13 else 1 if i < 17 else 2], [4, 6, 8, 10, 12, 15][i % 6], [0, 2] if i % 3 else [1, 3], notes[i % 4]], students[i], i % 5 == 0)
        s3 = once('survey_main_v3', 'POST', f"/surveys/{s2['id']}/versions", {})
        once('main_v3_description', 'PATCH', f"/surveys/{s3['id']}", {'description': '第三轮待完善草稿：可以继续编辑、选题、预览和发布。历史答卷不会复制进新版本。'})
        branch = once('survey_main_branch_v4', 'POST', f"/surveys/{s1['id']}/versions", {})
        once('main_branch_description', 'PATCH', f"/surveys/{branch['id']}", {'description': '从问卷 v1 分支创建的 v4，采用满意度题目 v3。版本编号递增，实际来源仍指向 v1。'})
        once('main_branch_switch', 'POST', f"/surveys/{branch['id']}/questions/{first_items[0]['questionId']}/switch-version", {'expectedSourceQuestionId': satisfaction['id'], 'sourceQuestionId': sat3['id']})

        college = survey('survey_college', '02｜研究生学习体验 · 对照样本', '同一组常用题用于另一份问卷，可从题目使用统计跨问卷汇总。')
        college_items = [add(f'college_q{i}', college, q, i != 3) for i, q in enumerate(common)]
        pub_college = publish('publish_college', college)
        for i in range(10):
            submit(f'college_answer{i}', pub_college, college_items, [[i % 3], 8 + i * 2, [0, 1] if i % 2 else [2, 3], notes[i % 6]], students[i], i % 3 == 0)

        workbench = survey('survey_workbench', '03｜题目复用工作台 · 可编辑', '演示独立题、指定版本复用、转为独立题、另存常用题，以及从共享题目选题。可在这份草稿中自由操作。')
        work_q1 = add('workbench_q1', workbench, satisfaction)
        switched = once('workbench_switch', 'POST', f"/surveys/{workbench['id']}/questions/{work_q1['questionId']}/switch-version", {'expectedSourceQuestionId': satisfaction['id'], 'sourceQuestionId': sat2['id']})
        once('workbench_detach', 'POST', f"/surveys/{workbench['id']}/questions/{switched['questionId']}/detach", {'expectedSourceQuestionId': sat2['id']})
        add('workbench_hours', workbench, hours2)
        add('workbench_support', workbench, support)
        local = once('workbench_local', 'POST', f"/surveys/{workbench['id']}/questions", {'title': '本次访谈还需要特别关注哪些事情？', 'type': 'text', 'order': 4, 'validation': {'maxLength': 150}})
        saved_local = once('save_local_to_library', 'POST', f"/surveys/{workbench['id']}/questions/{local['questionId']}/save-to-library")
        foreign_q = read(f"/library/questions/{base['questions']['number']}", 'demo_owner')
        foreign_share = once('foreign_share', 'POST', f"/library/questions/{foreign_q['id']}/sharing", {'enabled': True}, 'demo_owner')
        add('workbench_foreign', workbench, foreign_q, questionShareToken=foreign_share['shareToken'])

        jump = survey('survey_jump', '04｜图书馆服务调研 · 跳转体验', '选择“没有使用过”时跳过到馆频次与支持需求，直接进入建议题；使用过时继续回答。支持需求恰好选择“课程答疑＋线上资源”会提前结束。')
        jump_items = [add(f'jump_q{i}', jump, q, i < 3) for i, q in enumerate([gate, visits, support, advice])]
        once('jump_gate_rule', 'PUT', f"/surveys/{jump['id']}/questions/{jump_items[0]['questionId']}/jump-rules", {'rules': [{'operator': 'selected', 'value': gate['options'][1]['optionId'], 'targetQuestionId': jump_items[3]['questionId']}]})
        once('jump_support_rule', 'PUT', f"/surveys/{jump['id']}/questions/{jump_items[2]['questionId']}/jump-rules", {'rules': [{'operator': 'exactly', 'value': [support['options'][i]['optionId'] for i in [0, 2]], 'targetQuestionId': None}]})
        pub_jump = publish('publish_jump', jump)
        for i in range(8):
            values = [[1], None, None, '希望增加新生入馆导览'] if i % 3 == 0 else [[0], i % 7 + 1, [0, 2], None] if i % 3 == 1 else [[0], i % 7 + 1, [1, 3], '希望预约座位更方便']
            submit(f'jump_answer{i}', pub_jump, jump_items, values, students[i], i % 2 == 0)

        repeat = survey('survey_repeat', '05｜每周学习打卡 · 允许重复提交', '同一用户可以多次打卡。两处时长题引用同一个常用题版本，用于演示提交数与答案数的区别。', repeat=True)
        repeat_items = [add(f'repeat_q{i}', repeat, q) for i, q in enumerate([hours2, hours2, advice])]
        pub_repeat = publish('publish_repeat', repeat)
        for i in range(6): submit(f'repeat_answer{i}', pub_repeat, repeat_items, [5 + i, 8 + i * 2, f'第 {i + 1} 周：保持规律学习'], students[0], i % 2 == 0)

        public_bank = once('public_bank', 'POST', '/library/banks', {'name': '01｜校园学习调研 · 共享标准题库', 'description': '公开分享自己的四类题目。满意度推荐 v2、时长推荐 v2，也可以查看和选用旧版本。'})
        private_bank = once('private_bank', 'POST', '/library/banks', {'name': '02｜访谈与图书馆 · 私人备选', 'description': '私人题库：含满意度分支 v3、图书馆筛选与频次、从问卷另存的访谈题。'})
        collected_bank = once('collected_bank', 'POST', '/library/banks', {'name': '03｜外来共享题目 · 我的收藏', 'description': '保留他人题目的原始来源。只能管理自己的收录，不能修改他人原题，也不能转为共享题库。'})
        for bank, qs in [(public_bank, [sat2, hours2, support, advice]), (private_bank, [sat3, gate, visits, saved_local]), (collected_bank, [foreign_q])]:
            for i, q in enumerate(qs, 1):
                proof = {'questionShareToken': foreign_share['shareToken']} if bank['id'] == collected_bank['id'] else {}
                once(f"bank_{bank['id']}_item{i}", 'PUT', f"/library/banks/{bank['id']}/items/{q['rootQuestionId']}", {'recommendedVersionId': q['id'], 'order': i, 'category': '共用指标' if bank['id'] == public_bank['id'] else '访谈备选' if bank['id'] == private_bank['id'] else '外部来源', **proof})
        public_share = once('public_bank_share', 'POST', f"/library/banks/{public_bank['id']}/sharing", {'enabled': True})

        external = once('external_survey', 'POST', '/surveys', {'title': '其他作者的共享题目使用示例', 'allowRepeat': True}, 'demo_reader')
        once('external_add', 'POST', f"/surveys/{external['id']}/questions/from-library", {'sourceQuestionId': satisfaction['id'], 'questionShareToken': shared['shareToken']}, 'demo_reader')

        saved['links'] = {'home': '/ui/#/', 'mainResults': f"/ui/#/results/{s1['id']}", 'mainVersions': f"/ui/#/survey-versions/{s1['id']}", 'liveFill': f"/ui/#/fill/{pub2['shareToken']}", 'draft': f"/ui/#/edit/{workbench['id']}", 'jumpFill': f"/ui/#/fill/{pub_jump['shareToken']}", 'repeatFill': f"/ui/#/fill/{pub_repeat['shareToken']}", 'questionVersions': f"/ui/#/questions/{satisfaction['id']}", 'questionShare': f"/ui/#/shared-question/{shared['shareToken']}", 'bankShare': f"/ui/#/shared-bank/{public_share['shareToken']}", 'usage': f"/ui/#/question-analysis/{satisfaction['id']}", 'numbers': f"/ui/#/question-analysis/{hours2['id']}", 'multiple': f"/ui/#/question-analysis/{support['id']}", 'texts': f"/ui/#/question-analysis/{advice['id']}"}
        from tests.backend.showcase_acceptance import verify_showcase
        saved['summary'] = verify_showcase(read, satisfaction, hours2, shared, public_share)
        saved['complete'] = True
        persist()
        print(json.dumps({'database': saved['database'], 'username': USERNAME, 'password': PASSWORD, 'summary': saved['summary'], 'links': saved['links']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
