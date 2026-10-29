import {api, $, esc, date, statuses, renderShell, confirmAction, closeModal, toast} from '../shared/common.js?v=4';

export function createSurveyVersion(parent) {
  confirmAction('创建问卷新版本', `从 v${parent.version}「${parent.title}」复制题目和设置，生成独立草稿与分享链接。截止时间清空，已有答卷不会复制。`, async () => {
    const saved = await api(`/surveys/${parent.id}/versions`, {method: 'POST', body: {}});
    await closeModal({saved: true});
    location.hash = `#/edit/${saved.id}`;
    toast(`已创建问卷 v${saved.version} 草稿`);
  }, '创建新草稿');
}

export async function renderSurveyVersions(id, isCurrent = () => true) {
  const selected = await api(`/surveys/${id}`);
  const versions = [];
  for (let skip = 0; ; skip += 100) {
    if (!isCurrent()) return;
    const batch = await api(`/surveys/${id}/versions?skip=${skip}&limit=100`);
    versions.push(...batch);
    if (batch.length < 100) break;
  }
  if (!isCurrent()) return;
  const byId = new Map(versions.map(v => [v.id, v]));
  const parentName = v => v.parentSurveyId ? `来自 v${byId.get(v.parentSurveyId)?.version ?? '?'}` : '初始版本';
  const latestId = versions.at(-1)?.id;
  renderShell('问卷版本', `<section class="heading"><div><div class="eyebrow">SURVEY VERSIONS</div><h1>${esc(selected.title)}</h1><p>从 v${selected.version} 查看系列历史 · 共 ${versions.length} 个版本</p></div><div class="actions"><a class="secondary" href="#/edit/${selected.id}">← 返回当前问卷</a><button class="primary" id="create-survey-version">从 v${selected.version} 创建新版本</button></div></section>
    <p class="note">版本号按创建顺序递增，修改来源可以是任意旧版本。草稿保存不会增加版本号；新问卷默认沿用原来的题目版本。</p>
    <section aria-label="问卷版本列表">${[...versions].reverse().map(v => `<article class="question-item"><div class="question-meta"><span>v${v.version}</span><span>${parentName(v)}</span>${v.id === latestId ? '<span>最新创建</span>' : ''}${v.id === selected.id ? '<span>当前查看</span>' : ''}<span class="badge ${v.status}">${statuses[v.status]}</span></div><h3>${esc(v.title)}</h3><p class="muted">创建于 ${date(v.createdAt)}</p><div class="question-actions"><a class="secondary" href="#/edit/${v.id}">${v.status === 'draft' ? '编辑草稿' : '管理问卷'}</a><a class="secondary" href="#/results/${v.id}">查看本版数据</a><button class="secondary" data-derive-survey="${v.id}">从 v${v.version} 创建新版本</button></div></article>`).join('')}</section>`);
  $('#create-survey-version').onclick = () => createSurveyVersion(selected);
  document.querySelectorAll('[data-derive-survey]').forEach(button => {
    button.onclick = () => createSurveyVersion(byId.get(button.dataset.deriveSurvey));
  });
}
