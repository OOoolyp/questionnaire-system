import {api, $, esc, renderShell, modal, closeModal, bindForm, toast, confirmAction} from '../shared/common.js?v=4';
import {allPages, bankContext, questionContext, preview, run, sharingDialog, collectDialog} from '../shared/library-access.js';
import {pickContext} from '../shared/reuse-picker.js?v=2';
import {parseShareLink} from '../shared/library-links.mjs';

export async function renderBanks(isCurrent = () => true) {
  const banks = await allPages('/library/banks');
  if (!isCurrent()) return;
  renderShell('我的题库', `<section class="heading"><div><div class="eyebrow">QUESTION BANKS</div><h1>我的题库</h1><p>按分类整理题目，设置推荐版本，分享给其他用户选用。</p></div><button class="primary" id="new-bank">＋ 创建题库</button></section>
    <form class="toolbar" id="open-library-share"><label class="field">打开题目或题库分享<input name="share" placeholder="粘贴分享链接" required></label><button class="secondary">打开分享</button><p class="error-banner" data-error hidden></p></form>
    <div class="cards">${banks.length ? banks.map(b => `<article class="card"><div class="card-main"><span class="badge draft">${b.sharingEnabled ? '分享已开启' : '个人题库'}</span><h3>${esc(b.name)}</h3><p>${esc(b.description || '暂无说明')}</p><small>${b.items.length} 道题</small></div><div class="card-footer"><a href="#/banks/${b.id}">管理与选题 →</a></div></article>`).join('') : '<div class="panel empty">还没有题库，创建一个开始整理题目。</div>'}</div>`);
  $('#new-bank').onclick = () => bankDialog();
  bindForm($('#open-library-share'), async data => {
    const share = parseShareLink(data.get('share')); location.hash = `#/shared-${share.kind}/${share.token}`;
  });
}

export async function renderBank(id, isCurrent = () => true, shared = false) {
  const bank = await api(shared ? `/shared/banks/${id}` : `/library/banks/${id}`);
  if (!isCurrent()) return;
  const refresh = () => renderBank(id, isCurrent, shared);
  renderShell(shared ? '共享题库' : '题库管理', `<section class="heading"><div><div class="eyebrow">${shared ? 'SHARED BANK' : 'QUESTION BANK'}</div><h1>${esc(bank.name)}</h1><p>${esc(bank.description || '暂无说明')}</p></div><div class="actions"><a class="secondary" href="#/banks">← 我的题库</a>${shared ? '' : '<button class="secondary" id="edit-bank">编辑信息</button><button class="secondary" id="share-bank">分享设置</button><button class="primary" id="add-bank-item">收录常用题</button><button class="danger" id="delete-bank">删除题库</button>'}</div></section>
    <p class="note">推荐版本默认选中，选题时可以查看并使用其他版本。${shared ? '分享只授予查看和选用权限。' : '更新推荐版本不会改变已创建的问卷。'}</p>
    <div class="toolbar"><label class="field">按分类查看<select id="bank-category"><option value="">全部分类</option>${[...new Set(bank.items.map(i => i.category || '未分类'))].map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('')}</select></label></div>
    <section id="bank-items">${bank.items.length ? bank.items.map(item => `<article class="question-item" data-category="${esc(item.category || '未分类')}"><div class="question-meta"><span>顺序 ${item.order}</span><span>${esc(item.category || '未分类')}</span>${item.question ? `<span>推荐 v${item.question.version}</span>` : '<span>授权已失效</span>'}</div><h3>${esc(item.question?.title || '不可访问的题目')}</h3>${item.question ? `<div class="reuse-preview">${preview(item.question)}</div>` : '<p>无法读取原题内容，可移除收录项或请分享者重新授权。</p>'}<div class="question-actions">${item.question ? `<button class="primary" data-pick-item="${item.rootQuestionId}">选择版本加入问卷</button><button class="secondary" data-collect-item="${item.rootQuestionId}">收录到我的题库</button>${shared ? '' : `<button class="secondary" data-edit-item="${item.rootQuestionId}">推荐版本与分类排序</button>`}` : ''}${shared ? '' : `<button class="danger" data-remove-item="${item.rootQuestionId}">移除收录</button>`}</div></article>`).join('') : '<div class="panel empty">题库还没有收录题目。</div>'}</section>`);
  $('#bank-category').onchange = () => document.querySelectorAll('[data-category]').forEach(row => { row.hidden = Boolean($('#bank-category').value && row.dataset.category !== $('#bank-category').value); });
  const itemFor = root => bank.items.find(i => i.rootQuestionId === root);
  const contextFor = root => bankContext(bank, itemFor(root), shared ? id : null);
  document.querySelectorAll('[data-pick-item]').forEach(b => b.onclick = () => run(() => pickContext(contextFor(b.dataset.pickItem))));
  document.querySelectorAll('[data-collect-item]').forEach(b => b.onclick = () => run(() => collectDialog(contextFor(b.dataset.collectItem))));
  if (shared) return;
  $('#edit-bank').onclick = () => bankDialog(bank, refresh);
  $('#share-bank').onclick = () => sharingDialog('banks', bank, refresh);
  $('#add-bank-item').onclick = () => run(() => selectOwnQuestion(bank, refresh));
  $('#delete-bank').onclick = () => confirmAction('删除题库', '只删除题库及收录关系，保留常用题、历史版本和已创建的问卷。此操作不能撤销。', async () => {
    await api(`/library/banks/${bank.id}`, {method: 'DELETE'}); location.hash = '#/banks'; toast('题库已删除');
  }, '删除题库');
  document.querySelectorAll('[data-edit-item]').forEach(b => b.onclick = () => run(() => editItem(bank, itemFor(b.dataset.editItem), refresh)));
  document.querySelectorAll('[data-remove-item]').forEach(b => b.onclick = () => {
    const item = itemFor(b.dataset.removeItem);
    confirmAction('移除收录', '从当前题库移除此题，已有问卷保持不变。', async () => {
      await api(`/library/banks/${bank.id}/items/${item.rootQuestionId}`, {method: 'DELETE', body: {expectedRecommendedVersionId: item.recommendedVersionId}});
      await refresh(); toast('已移除收录');
    }, '移除');
  });
}

function bankDialog(bank = null, refresh = async () => {}) {
  const element = modal(bank ? '编辑题库' : '创建题库', `<form><label class="field">题库名称<input name="name" required value="${esc(bank?.name || '')}"></label><label class="field">说明<textarea name="description">${esc(bank?.description || '')}</textarea></label><p class="error-banner" data-error hidden></p><div class="dialog-actions"><button class="primary">保存题库</button></div></form>`);
  bindForm(element.querySelector('form'), async data => {
    const saved = await api(bank ? `/library/banks/${bank.id}` : '/library/banks', {method: bank ? 'PATCH' : 'POST', body: {name: data.get('name').trim(), description: data.get('description')}});
    await closeModal({saved: true}); if (bank) await refresh(); else location.hash = `#/banks/${saved.id}`;
  });
}

async function selectOwnQuestion(bank, refresh) {
  const roots = await allPages('/library/questions');
  if (!roots.length) { modal('先创建常用题', '<p>在常用题页面创建题目，或从问卷保存常用题副本。</p><a class="secondary" href="#/questions">前往常用题</a>'); return; }
  const element = modal('选择常用题', `<form><label class="field">题目<select name="root">${roots.map(q => `<option value="${q.id}">${esc(q.title)}</option>`).join('')}</select></label><p class="error-banner" data-error hidden></p><div class="dialog-actions"><button class="primary">选择推荐版本</button></div></form>`);
  bindForm(element.querySelector('form'), async data => {
    const versions = await allPages(`/library/questions/${data.get('root')}/versions`);
    const context = questionContext(versions.at(-1));
    await closeModal({saved: true}); await run(() => collectDialog(context, bank.id, refresh));
  });
}

async function editItem(bank, item, refresh) {
  const context = bankContext(bank, item);
  const versions = await allPages(context.versionsPath);
  const element = modal('推荐版本与分类排序', `<form><label class="field">推荐版本<select name="version">${[...versions].reverse().map(q => `<option value="${q.id}" ${q.id === item.recommendedVersionId ? 'selected' : ''}>v${q.version} · ${esc(q.title)}</option>`).join('')}</select></label><label class="field">分类<input name="category" value="${esc(item.category)}"></label><label class="field">顺序<input name="order" type="number" min="1" max="2147483647" step="1" required value="${item.order}"></label><p class="error-banner" data-error hidden></p><div class="dialog-actions"><button class="primary">保存收录设置</button></div></form>`);
  bindForm(element.querySelector('form'), async data => {
    await api(`/library/banks/${bank.id}/items/${item.rootQuestionId}`, {method: 'PUT', body: {recommendedVersionId: data.get('version'), expectedRecommendedVersionId: item.recommendedVersionId, category: data.get('category'), order: Number(data.get('order')), bankId: bank.id}});
    await closeModal({saved: true}); await refresh(); toast('推荐版本和分类排序已保存');
  });
}
