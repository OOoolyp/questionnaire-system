import {createUnsavedRegistry} from './unsaved.mjs';

const registry = createUnsavedRegistry();
let activePrompt = null;
export const registerUnsaved = source => registry.add(source);
export const resetUnsavedTracking = () => registry.clear();

export function formSnapshot(form) {
  // 记录真实控件值及顺序；增删/移动选项和规则也能被识别，错误提示不影响状态。
  return JSON.stringify([...form.elements].filter(input => ['INPUT','TEXTAREA','SELECT'].includes(input.tagName))
    .filter(input => !['submit','button'].includes(input.type))
    .map(input => [input.name, input.type, input.closest('.option-row')?.dataset.id || '',
      ['checkbox','radio'].includes(input.type) ? input.checked : input.value]));
}

export function requestLeave(scope = null) {
  const pending = registry.pending(scope);
  if (!pending.length) return Promise.resolve(true);
  if (activePrompt) return activePrompt;
  activePrompt = new Promise(resolve => {
    const busy = pending.some(source => source.isBusy?.());
    const dialog = document.createElement('dialog');
    dialog.id = 'leave-confirm'; dialog.setAttribute('aria-labelledby','leave-title');
    dialog.innerHTML = `<div class="dialog-head"><h2 id="leave-title">${busy?'正在保存，请稍候':'还有未保存的内容'}</h2></div><p class="muted">${busy?'保存或提交尚未完成，请等待结果后再离开。':'离开后，本次未保存的修改或未提交的回答将被放弃。'}</p><div class="dialog-actions"><button type="button" class="secondary" id="keep-editing">${busy?'继续等待':'继续编辑'}</button>${busy?'':'<button type="button" class="danger" id="discard-changes">放弃并离开</button>'}</div>`;
    document.body.append(dialog);
    function finish(leave) {
      if (leave && registry.pending(scope).some(source => source.isBusy?.())) {finish(false); return;}
      if (leave) registry.discard(scope);
      dialog.close(); dialog.remove(); activePrompt = null; resolve(leave);
    }
    dialog.querySelector('#keep-editing').onclick = () => finish(false);
    if (!busy) dialog.querySelector('#discard-changes').onclick = () => finish(true);
    dialog.addEventListener('cancel', event => {event.preventDefault(); finish(false);});
    dialog.showModal(); dialog.querySelector('#keep-editing').focus();
  });
  return activePrompt;
}

window.addEventListener('beforeunload', event => {
  if (registry.pending().length) {event.preventDefault(); event.returnValue = '';}
});

// 页面内链接先确认，再改变地址，避免取消时丢失当前表单。
document.addEventListener('click', async event => {
  if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const link = event.target.closest('a[href]');
  if (!link || link.target === '_blank' || link.hasAttribute('download')) return;
  const destination = new URL(link.href, location.href);
  if (!['http:','https:'].includes(destination.protocol) || destination.href === location.href || !registry.pending().length) return;
  event.preventDefault(); event.stopPropagation();
  if (await requestLeave()) location.assign(destination.href);
}, true);
