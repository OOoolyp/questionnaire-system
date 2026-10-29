import {api, $, esc, date, types, renderShell, modal, closeModal, bindForm, toast, confirmAction} from '../shared/common.js?v=4';
import {sharingDialog, collectDialog, questionContext, run} from '../shared/library-access.js';
import {pickContext} from '../shared/reuse-picker.js?v=2';
import {libraryPayload} from '../shared/library-form.mjs';

const endpoint = '/library/questions';

export async function renderLibrary(isCurrent = () => true, skip = 0) {
  const batch = await api(`${endpoint}?skip=${skip}&limit=21`);
  if (!isCurrent()) return;
  const items = batch.slice(0, 20);
  renderShell('常用题', `<section class="heading"><div><div class="eyebrow">QUESTION LIBRARY</div><h1>我的常用题</h1><p>保存可复用题目，保留每次修改的版本。</p></div><button class="primary" id="new-library-question">＋ 创建常用题</button></section>
    <p class="status-note">每张卡片代表一道题，显示最初的题干；打开后查看最新版本和完整历史。</p>
    <div class="cards">${items.length ? items.map(q => `<article class="card"><div class="card-main"><span class="badge draft">${types[q.type]}</span><h3>${esc(q.title)}</h3><p class="muted">创建于 ${date(q.createdAt)}</p></div><div class="card-footer"><a href="#/questions/${q.id}/latest">查看题目与版本 →</a></div></article>`).join('') : '<div class="panel empty">还没有常用题，先创建一道题。</div>'}</div>
    <div class="actions library-pagination"><button class="secondary" id="library-prev" ${skip === 0 ? 'disabled' : ''}>上一页</button><span>第 ${Math.floor(skip / 20) + 1} 页</span><button class="secondary" id="library-next" ${batch.length <= 20 ? 'disabled' : ''}>下一页</button></div><p class="error-banner" id="library-error" hidden></p>`);
  $('#new-library-question').onclick = () => questionDialog();
  const changePage = async offset => {
    try { await renderLibrary(isCurrent, offset); }
    catch (error) { if (isCurrent() && $('#library-error')) { $('#library-error').textContent = error.message; $('#library-error').hidden = false; } }
  };
  $('#library-prev').onclick = () => changePage(Math.max(0, skip - 20));
  $('#library-next').onclick = () => changePage(skip + 20);
}

export async function renderLibraryQuestion(id, isCurrent = () => true, preferLatest = false) {
  let selected = await api(`${endpoint}/${id}`);
  const versions = [];
  for (let skip = 0; ; skip += 100) {
    if (!isCurrent()) return;
    const batch = await api(`${endpoint}/${id}/versions?skip=${skip}&limit=100`);
    versions.push(...batch);
    if (batch.length < 100) break;
  }
  if (!isCurrent()) return;
  const latest = versions.at(-1);
  if (preferLatest && latest) selected = latest;
  const byId = new Map(versions.map(q => [q.id, q]));
  const versionName = identifier => byId.has(identifier) ? `v${byId.get(identifier).version}` : '未知版本';
  renderShell('题目版本', `<section class="heading"><div><div class="eyebrow">QUESTION VERSIONS</div><h1>${esc(selected.title)}</h1><p>正在查看 v${selected.version} · 共 ${versions.length} 个版本</p></div><div class="actions"><a class="secondary" href="#/questions">← 常用题</a><a class="secondary" href="#/question-analysis/${selected.id}">使用情况与统计</a><button class="secondary" id="share-question">分享此版本</button><button class="secondary" id="collect-question">收录到题库</button><button class="secondary" id="use-question">加入问卷</button><button class="primary" id="derive-question">基于此版本修改</button></div></section>
    <div class="editor-layout"><section><article class="panel library-content"><div class="question-meta"><span>${types[selected.type]}</span><span>v${selected.version}${selected.id === latest?.id ? ' · 最新创建' : ''}</span></div><h2>${esc(selected.title)}</h2>
    ${selected.options?.length ? `<ol class="question-options">${selected.options.map(o => `<li>${esc(o.text)}</li>`).join('')}</ol>` : ''}
    <p class="muted">${esc(validationText(selected))}</p><p class="status-note">创建于 ${date(selected.createdAt)}${selected.parentQuestionId ? ` · 修改来源：${versionName(selected.parentQuestionId)}` : ' · 初始版本'}${selected.restoredFromQuestionId ? ` · 恢复内容：${versionName(selected.restoredFromQuestionId)}` : ''}</p></article>
    <p class="note">已保存的题目内容不会被覆盖。修改或恢复都会创建新版本，不会改变旧问卷。</p>
    ${selected.id !== latest?.id ? '<button class="secondary" id="restore-question">将此版本内容恢复为新版本</button>' : ''}</section>
    <aside class="panel library-history"><h3>版本历史</h3><p class="muted">版本号按创建顺序递增，修改来源可以是任意旧版本。</p><nav aria-label="题目版本历史">${[...versions].reverse().map(q => `<a class="version-link ${q.id === selected.id ? 'selected' : ''}" href="#/questions/${q.id}" ${q.id === selected.id ? 'aria-current="page"' : ''}><strong>v${q.version}</strong><span>${q.parentQuestionId ? `来自 ${versionName(q.parentQuestionId)}` : '初始版本'}${q.restoredFromQuestionId ? ` · 恢复 ${versionName(q.restoredFromQuestionId)}` : ''}</span><small>${esc(q.title)}</small></a>`).join('')}</nav></aside></div>`);
  $('#share-question').onclick=()=>sharingDialog('questions',selected,()=>renderLibraryQuestion(selected.id,isCurrent));
  $('#collect-question').onclick=()=>run(()=>collectDialog(questionContext(selected)));
  $('#use-question').onclick=()=>run(()=>pickContext(questionContext(selected)));
  $('#derive-question').onclick = () => questionDialog(selected);
  if ($('#restore-question')) $('#restore-question').onclick = () => confirmAction('恢复为新版本',
    `将 v${selected.version} 的内容复制为新版本，修改来源记录为当前最新的 v${latest.version}。已有版本和问卷不变。`, async () => {
      const saved = await api(`${endpoint}/${latest.id}/restore`, {method: 'POST', body: {restoredFromQuestionId: selected.id}});
      await closeModal({saved: true});
      location.hash = `#/questions/${saved.id}`;
      toast(`已恢复为 v${saved.version}`);
    }, '创建恢复版本');
}

function validationText(question) {
  const v = question.validation;
  if (question.type === 'single') return '单选题，每次选择一个选项。';
  if (question.type === 'multiple') return `选择数量：${v.minChoices ?? 0}～${v.maxChoices ?? question.options.length} 项`;
  if (question.type === 'text') return `文本长度：${v.minLength ?? 0}～${v.maxLength ?? '不限'} 个字符`;
  return `${v.integerOnly ? '整数' : '数字'}范围：${v.minValue ?? '不限'}～${v.maxValue ?? '不限'}`;
}

function questionDialog(parent = null) {
  const current = parent || {title: '', type: 'single', validation: {}, options: []};
  const element = modal(parent ? `基于 v${parent.version} 创建新版本` : '创建常用题', `<form><label class="field">题干<input name="title" value="${esc(current.title)}" required placeholder="请输入问题"></label>
    <label class="field">题型<select name="type">${Object.entries(types).map(([value, label]) => `<option value="${value}" ${value === current.type ? 'selected' : ''}>${label}</option>`).join('')}</select></label>
    <div id="library-fields"></div><p class="note">${parent ? '保存后创建新版本，保留当前版本及其内容。' : '保存后成为第一版，后续修改会另存为新版本。'}</p><p class="error-banner" data-error hidden></p><div class="dialog-actions"><button class="primary">${parent ? '保存新版本' : '保存常用题'}</button></div></form>`);
  const form = element.querySelector('form');
  const drafts = new Map();
  let activeType = current.type;
  const readFields = () => {
    const data = new FormData(form), validation = {};
    for (const key of ['minChoices', 'maxChoices', 'minLength', 'maxLength', 'minValue', 'maxValue']) if (data.has(key)) validation[key] = data.get(key);
    validation.integerOnly = data.has('integerOnly');
    return {validation, options: [...form.querySelectorAll('.option-row')].map(row => ({text: row.querySelector('input').value, optionId: row.dataset.id}))};
  };
  function renderFields(type, source) {
    const v = source?.validation || {};
    const choice = ['single', 'multiple'].includes(type);
    const fields = {single: [], multiple: [['minChoices', '最少选择数'], ['maxChoices', '最多选择数']], text: [['minLength', '最小字符数'], ['maxLength', '最大字符数']], number: [['minValue', '最小值'], ['maxValue', '最大值']]}[type];
    element.querySelector('#library-fields').innerHTML = (choice ? '<label class="field">选项（至少两项）</label><div id="library-options"></div><button type="button" class="secondary" id="library-add-option">＋ 添加选项</button>' : '') +
      `<div class="row">${fields.map(([key, label]) => `<label class="field">${label}<input name="${key}" type="number" ${type === 'number' ? 'step="any"' : 'min="0" max="2147483647" step="1"'} value="${esc(v[key] ?? '')}" placeholder="不限"></label>`).join('')}</div>` +
      (type === 'number' ? `<label class="check-label"><input name="integerOnly" type="checkbox" ${v.integerOnly ? 'checked' : ''}>仅允许整数</label>` : '');
    if (choice) {
      const add = option => {
        const row = document.createElement('div'); row.className = 'option-row';
        if (option.optionId) row.dataset.id = option.optionId;
        row.innerHTML = `<input aria-label="选项文字" required placeholder="选项文字" value="${esc(option.text || '')}"><button type="button" aria-label="删除选项" class="remove-option">×</button>`;
        row.querySelector('button').onclick = () => row.remove();
        element.querySelector('#library-options').append(row);
      };
      (source?.options ?? [{}, {}]).forEach(add);
      element.querySelector('#library-add-option').onclick = () => add({});
    }
  }
  renderFields(current.type, {...current, options: current.options?.length ? current.options : [{}, {}]});
  form.elements.type.onchange = () => {
    drafts.set(activeType, readFields()); activeType = form.elements.type.value;
    renderFields(activeType, drafts.get(activeType) || null);
  };
  bindForm(form, async data => {
    const payload = libraryPayload(data, readFields().options);
    const saved = await api(parent ? `${endpoint}/${parent.id}/versions` : endpoint, {method: 'POST', body: payload});
    await closeModal({saved: true});
    location.hash = `#/questions/${saved.id}`;
    toast(`已保存 v${saved.version}`);
  });
}
