"""成果展示数据的只读验收；由 seed_showcase.py 创建完成后及重复运行时调用。"""


def verify_showcase(read, satisfaction, hours2, shared, public_share):
    surveys = read('/surveys?limit=100')
    counts = {s['id']: read(f"/surveys/{s['id']}/statistics")['submissionCount'] for s in surveys}
    assert len(surveys) == 8, len(surveys)
    assert sum(counts.values()) == 66, counts
    assert sorted(s['status'] for s in surveys) == sorted(['closed', 'published', 'published', 'published', 'published', 'draft', 'draft', 'draft'])
    assert len(read('/library/banks?limit=100')) == 3
    history = read(f"/library/questions/{satisfaction['id']}/versions")
    assert [q['version'] for q in history] == [1, 2, 3, 4]
    assert history[2]['parentQuestionId'] == satisfaction['id']
    assert history[3]['restoredFromQuestionId'] == satisfaction['id']
    stats = read(f"/analytics/questions/{hours2['id']}/statistics")
    assert (stats['submissionCount'], stats['answerCount']) == (24, 30), stats
    assert abs(stats['average'] - 9.6) < 1e-9, stats
    use = read(f"/analytics/questions/{satisfaction['id']}/usage?scope=series")
    assert use['restrictedSurveyVersions'] == 1
    assert read(f"/shared/questions/{shared['shareToken']}")['recommendedVersionId'] == satisfaction['id']
    assert len(read(f"/shared/banks/{public_share['shareToken']}")['items']) == 4
    roots = read('/library/questions?limit=100')
    version_count = sum(len(read(f"/library/questions/{q['id']}/versions?limit=100")) for q in roots)
    assert (len(roots), version_count) == (7, 11)
    jump = next(s for s in surveys if s['title'].startswith('04｜'))
    answers = read(f"/surveys/{jump['id']}/responses?limit=100")
    assert len(answers) == 8
    assert sorted(len(r['answers']) for r in answers) == [2, 2, 2, 3, 3, 3, 4, 4]
    workbench = next(s for s in surveys if s['title'].startswith('03｜'))
    detail = read(f"/surveys/{workbench['id']}")
    assert [bool(q.get('sourceQuestionId')) for q in detail['questions']] == [False, True, True, False, True]
    main = next(s for s in surveys if s['title'].startswith('01｜'))
    versions = read(f"/surveys/{main['id']}/versions?limit=100")
    assert [s['version'] for s in versions] == [1, 2, 3, 4]
    assert versions[3]['parentSurveyId'] == versions[0]['id']
    return {'surveys': len(surveys), 'surveySeries': len({s['rootSurveyId'] for s in surveys}),
            'responses': sum(counts.values()), 'banks': 3, 'questionSeries': len(roots),
            'questionVersions': version_count, 'published': 4, 'draft': 3, 'closed': 1}
