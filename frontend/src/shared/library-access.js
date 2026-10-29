import {api, esc, modal, closeModal, bindForm, toast} from './common.js?v=4';

export async function allPages(path) {
  const result = [];
  for (let skip = 0; ; skip += 100) {
    const rows = await api(`${path}${path.includes('?') ? '&' : '?'}skip=${skip}&limit=100`);
    result.push(...rows);
    if (rows.length < 100) return result;
  }
}

export function questionContext(question, proof = {}, versionsPath = null, recommendedVersionId = question.id) {
  return {rootQuestionId: question.rootQuestionId, title: question.title, proof, recommendedVersionId,
    versionsPath: versionsPath || `/library/questions/${question.id}/versions`};
}

export function bankContext(bank, item, token = null) {
  return questionContext(item.question, token ? {bankShareToken: token} : {bankId: bank.id},
    token ? `/shared/banks/${token}/questions/${item.rootQuestionId}/versions` : `/library/banks/${bank.id}/questions/${item.rootQuestionId}/versions`, item.recommendedVersionId);
}

export function preview(question) {
  const v = question.validation;
  const limit = question.type === 'single' ? '选择一项' : question.type === 'multiple' ? `选择 ${v.minChoices ?? 0}～${v.maxChoices ?? question.options.length} 项` :
    question.type === 'text' ? `长度 ${v.minLength ?? 0}～${v.maxLength ?? '不限'} 字符` : `${v.integerOnly ? '整数' : '数字'}范围 ${v.minValue ?? '不限'}～${v.maxValue ?? '不限'}`;
  return `<strong>v${question.version} · ${esc(question.title)}</strong><p>${limit}</p>${question.options?.length ? `<ol>${question.options.map(o => `<li>${esc(o.text)}</li>`).join('')}</ol>` : ''}`;
}

export function run(action) {
  return Promise.resolve().then(action).catch(error => { if (error.status !== 401) toast(error.message); });
}

export function sharingDialog(kind, resource, refresh = async () => {}) {
  const url = `${location.origin}${location.pathname}#/shared-${kind === 'questions' ? 'question' : 'bank'}/${resource.shareToken}`;
  const element = modal('分享设置', `<form><p class="note">分享允许查看和选用版本，编辑权限仍归创作者。${kind === 'questions' ? '此链接固定推荐当前版本，允许查看同系列已有和以后新增的版本。' : '此链接允许选用库内题目的各个版本，默认使用各题推荐版本。'}关闭只停用此入口，已经创建的问卷保留原内容。</p><label class="check-label"><input name="enabled" type="checkbox" ${resource.sharingEnabled ? 'checked' : ''}>开启此分享入口</label><p>当前状态：${resource.sharingEnabled ? '已开启' : '已关闭'}。更改开关后请保存。</p><label class="field">分享链接<input readonly name="link" value="${esc(url)}"></label><button type="button" class="secondary" id="copy-library-link">复制链接</button><p class="error-banner" data-error hidden></p><div class="dialog-actions"><button class="primary">保存分享设置</button></div></form>`);
  element.querySelector('#copy-library-link').onclick = () => run(async () => { await navigator.clipboard.writeText(url); toast('链接已复制；请确认分享入口已开启'); });
  bindForm(element.querySelector('form'), async data => {
    await api(`/library/${kind}/${resource.id}/sharing`, {method: 'POST', body: {enabled: data.has('enabled')}});
    await closeModal({saved: true}); await refresh(); toast('分享设置已保存');
  });
}

export async function collectDialog(context, defaultBankId = null, refresh = async () => {}) {
  const [banks, versions] = await Promise.all([allPages('/library/banks'), allPages(context.versionsPath)]);
  if (!banks.length) { modal('先创建题库', '<p>创建个人题库后即可收录这道题。</p><a class="secondary" href="#/banks">前往题库</a>'); return; }
  const selectedBank = banks.find(b => b.id === defaultBankId) || banks[0];
  const preferredVersionId = context.selectedVersionId || context.recommendedVersionId;
  const element = modal('收录到我的题库', `<form><label class="field">题库<select name="bankId">${banks.map(b => `<option value="${b.id}" ${b.id === selectedBank.id ? 'selected' : ''}>${esc(b.name)}</option>`).join('')}</select></label><label class="field">推荐版本<select name="recommendedVersionId">${[...versions].reverse().map(q => `<option value="${q.id}" ${q.id === preferredVersionId ? 'selected' : ''}>v${q.version} · ${esc(q.title)}</option>`).join('')}</select></label><div class="row"><label class="field">分类<input name="category" placeholder="未分类"></label><label class="field">顺序<input name="order" type="number" min="1" max="2147483647" step="1" value="${Math.max(0, ...selectedBank.items.map(i => i.order)) + 1}" required></label></div><p class="note">同一题库每道题收录一项。外来原题只能收录到未共享的个人题库，选用时仍需有效授权。</p><p class="error-banner" data-error hidden></p><div class="dialog-actions"><button class="primary">收录题目</button></div></form>`);
  const form = element.querySelector('form');
  form.elements.bankId.onchange = () => { form.elements.order.value = Math.max(0, ...banks.find(b => b.id === form.elements.bankId.value).items.map(i => i.order)) + 1; };
  bindForm(form, async data => {
    await api(`/library/banks/${data.get('bankId')}/items/${context.rootQuestionId}`, {method: 'PUT', body: {recommendedVersionId: data.get('recommendedVersionId'), category: data.get('category'), order: Number(data.get('order')), ...context.proof}});
    await closeModal({saved: true}); await refresh(); toast('已收录到题库');
  });
}
