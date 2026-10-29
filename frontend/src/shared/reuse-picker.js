import {api, esc, modal, closeModal, bindForm, toast} from './common.js?v=4';
import {allPages, questionContext, bankContext, preview, run} from './library-access.js';
import {parseShareLink} from './library-links.mjs';

export async function pickContext(context, survey = null, refresh = async () => {}, question = null) {
  const openedFrom = location.hash;
  const [versions, targets] = await Promise.all([allPages(context.versionsPath), survey ? Promise.resolve([survey]) : allPages('/surveys')]);
  if (location.hash !== openedFrom) return;
  const drafts = targets.filter(s => s.status === 'draft');
  if (!drafts.length) { modal('没有可编辑的草稿', '<p>请先创建问卷草稿，再选用题目。</p><a class="secondary" href="#/">前往问卷</a>'); return; }
  const switching = Boolean(question);
  const selectedId = versions.some(v => v.id === question?.sourceQuestionId) ? question.sourceQuestionId : (context.selectedVersionId || context.recommendedVersionId);
  const element = modal(switching ? '切换题目版本' : '选择版本加入问卷', `<form><label class="field">版本<select name="sourceQuestionId">${[...versions].reverse().map(q => `<option value="${q.id}" ${q.id === selectedId ? 'selected' : ''}>v${q.version} · ${esc(q.title)}${q.id === context.recommendedVersionId ? '（推荐）' : ''}${q.id === question?.sourceQuestionId ? '（当前使用）' : ''}</option>`).join('')}</select></label><div class="reuse-preview"></div>${!survey ? `<label class="field">目标草稿<select name="surveyId">${drafts.map(s => `<option value="${s.id}">v${s.version} · ${esc(s.title)}</option>`).join('')}</select></label>` : ''}${switching ? '<label class="check-label"><input type="checkbox" name="clearJumpRules">清空本题跳转规则后切换</label><p class="note">题序与必答设置保留；不兼容的跳转规则会阻止切换。</p>' : '<label class="field">加入位置<select name="beforeQuestionId"></select></label><label class="check-label"><input type="checkbox" name="required">设为必答</label>'}<p class="error-banner" data-error hidden></p><div class="dialog-actions"><button class="primary">${switching ? '确认切换' : '加入问卷'}</button></div></form>`);
  const form = element.querySelector('form');
  const draw = () => { element.querySelector('.reuse-preview').innerHTML = preview(versions.find(q => q.id === form.elements.sourceQuestionId.value)); };
  const target = () => survey || drafts.find(s => s.id === form.elements.surveyId.value);
  function positions() {
    if (!switching) form.elements.beforeQuestionId.innerHTML = '<option value="">问卷末尾</option>' + target().questions.map(q => `<option value="${q.questionId}">第 ${q.order} 题之前：${esc(q.title)}</option>`).join('');
  }
  draw(); positions(); form.elements.sourceQuestionId.onchange = draw;
  if (form.elements.surveyId) form.elements.surveyId.onchange = positions;
  bindForm(form, async data => {
    const destination = target();
    const body = {sourceQuestionId: data.get('sourceQuestionId'), ...context.proof};
    if (switching) { body.expectedSourceQuestionId = question.sourceQuestionId; body.clearJumpRules = data.has('clearJumpRules'); }
    else { body.required = data.has('required'); const before = destination.questions.find(q => q.questionId === data.get('beforeQuestionId')); if (before) { body.beforeQuestionId = before.questionId; body.order = before.order; } }
    await api(`/surveys/${destination.id}/questions/${switching ? `${question.questionId}/switch-version` : 'from-library'}`, {method: 'POST', body});
    await closeModal({saved: true});
    if (survey) await refresh(); else location.hash = `#/edit/${destination.id}`;
    toast(switching ? '版本已切换' : '已加入选定版本');
  });
}

export async function pickBank(bank, token = null, survey = null, refresh = async () => {}, question = null) {
  const items = bank.items.filter(item => item.question);
  if (!items.length) { modal('没有可选题目', '<p>此题库为空或收录题目的授权已失效。</p>'); return; }
  const element = modal('从题库选题', `<form><label class="field">题目<select name="root">${items.map(item => `<option value="${item.rootQuestionId}">${esc(item.category || '未分类')} · ${esc(item.question.title)}</option>`).join('')}</select></label><p class="error-banner" data-error hidden></p><div class="dialog-actions"><button class="primary">查看版本</button></div></form>`);
  bindForm(element.querySelector('form'), async data => {
    const context = bankContext(bank, items.find(i => i.rootQuestionId === data.get('root')), token);
    await api(context.versionsPath + '?limit=1');
    await closeModal({saved: true}); await run(() => pickContext(context, survey, refresh, question));
  });
}

export async function openReusePicker(survey, refresh, question = null) {
  if (question) {
    try { const source = await api(`/library/questions/${question.sourceQuestionId}`); return pickContext(questionContext(source), survey, refresh, question); }
    catch (error) { if (error.status !== 404) throw error; }
  }
  const openedFrom = location.hash;
  const [roots, banks] = await Promise.all([allPages('/library/questions'), allPages('/library/banks')]);
  if (location.hash !== openedFrom) return;
  const element = modal(question ? '选择同一题目的授权入口' : '选择题目来源', `<form><label class="field">来源<select name="entry"><optgroup label="我的常用题">${roots.map(q => `<option value="q:${q.id}">${esc(q.title)}</option>`).join('')}</optgroup><optgroup label="我的题库">${banks.map(b => `<option value="b:${b.id}">${esc(b.name)}</option>`).join('')}</optgroup><option value="share">使用分享链接</option></select></label><label class="field">题目或题库分享链接<input name="share" placeholder="选择分享链接来源后，在这里粘贴链接"></label>${question ? `<p class="note">当前题目：${esc(question.title)}。切换时仍需同系列的有效授权。</p>` : ''}<p class="error-banner" data-error hidden></p><div class="dialog-actions"><button class="primary">继续选题</button></div></form>`);
  bindForm(element.querySelector('form'), async data => {
    const entry = data.get('entry'); let context, bank, token = null;
    if (entry.startsWith('q:')) { const q = roots.find(q => q.id === entry.slice(2)); const versions = await allPages(`/library/questions/${q.id}/versions`); context = questionContext(versions.at(-1)); }
    else if (entry.startsWith('b:')) bank = await api(`/library/banks/${entry.slice(2)}`);
    else { const share = parseShareLink(data.get('share')); if (share.kind === 'bank') { token = share.token; bank = await api(`/shared/banks/${token}`); }
      else { const result = await api(`/shared/questions/${share.token}`); context = questionContext(result.question, {questionShareToken: share.token}, `/shared/questions/${share.token}/versions`, result.recommendedVersionId); } }
    await closeModal({saved: true}); await run(() => bank ? pickBank(bank, token, survey, refresh, question) : pickContext(context, survey, refresh, question));
  });
}
