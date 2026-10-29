import {api, $, esc, renderShell} from '../shared/common.js?v=4';
import {allPages, preview, questionContext, collectDialog, run} from '../shared/library-access.js';
import {pickContext} from '../shared/reuse-picker.js?v=2';

export async function renderSharedQuestion(token, isCurrent = () => true) {
  const [share, versions] = await Promise.all([api(`/shared/questions/${token}`), allPages(`/shared/questions/${token}/versions`)]);
  if (!isCurrent()) return;
  const recommended = versions.find(q => q.id === share.recommendedVersionId);
  renderShell('共享题目', `<section class="heading"><div><div class="eyebrow">SHARED QUESTION</div><h1>${esc(share.question.title)}</h1><p>分享者推荐 v${recommended.version}。可以查看并选用同系列其他版本。</p></div><a class="secondary" href="#/banks">我的题库</a></section><section class="panel library-content"><label class="field">查看版本<select id="shared-version">${[...versions].reverse().map(q => `<option value="${q.id}" ${q.id === recommended.id ? 'selected' : ''}>v${q.version} · ${esc(q.title)}${q.id === recommended.id ? '（分享者推荐）' : ''}</option>`).join('')}</select></label><div id="shared-question-preview"></div><div class="actions"><button class="primary" id="use-shared-question">加入我的问卷</button><button class="secondary" id="collect-shared-question">收录到我的题库</button></div></section>`);
  const selected = () => versions.find(q => q.id === $('#shared-version').value);
  const context = () => ({...questionContext(share.question, {questionShareToken: token}, `/shared/questions/${token}/versions`, recommended.id), selectedVersionId: selected().id});
  const draw = () => { $('#shared-question-preview').innerHTML = preview(selected()); };
  $('#shared-version').onchange = draw; draw();
  $('#use-shared-question').onclick = () => run(() => pickContext(context()));
  $('#collect-shared-question').onclick = () => run(() => collectDialog(context()));
}

export async function renderSource(surveyId, questionId, isCurrent = () => true) {
  const question = await api(`/surveys/${surveyId}/questions/${questionId}/source`);
  if (!isCurrent()) return;
  renderShell('已使用的来源版本', `<section class="heading"><h1>已使用的常用题版本</h1><a class="secondary" href="#/edit/${surveyId}">← 返回问卷</a></section><article class="panel library-content">${preview(question)}<a class="secondary" href="#/question-analysis/${question.id}">在我的问卷中的使用情况与统计</a></article><p class="note">这里展示当前问卷已使用的固定版本。选用或切换其他版本，需要有效的题目或题库分享入口。</p>`);
}
