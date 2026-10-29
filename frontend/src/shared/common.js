import {registerUnsaved, requestLeave, formSnapshot} from './guards.js';

const TOKEN_KEY = 'wenxu.accessToken';
export const state = {user: null, surveys: [], lastTrace: null};
export const $ = selector => document.querySelector(selector);
export const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
export const date = value => value ? new Date(value).toLocaleString('zh-CN', {hour12: false}) : '不设置';
export const types = {single:'单选题', multiple:'多选题', text:'文本填空', number:'数字填空'};
export const statuses = {draft:'草稿', published:'收集中', closed:'已关闭'};
export const token = () => sessionStorage.getItem(TOKEN_KEY);
export function setToken(value) {sessionStorage.setItem(TOKEN_KEY, value);}
export function clearAuth() {sessionStorage.removeItem(TOKEN_KEY); state.user = null; state.lastTrace = null;}
export function errorText(detail) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(item => {
    const field = (item.loc || []).filter(x => !['body','query'].includes(x)).join(' / ');
    const message = item.type === 'missing' ? '此项必填' : item.type === 'json_invalid' ? '数据格式错误' : item.msg;
    return `${field ? field + '：' : ''}${message}`;
  }).join('\n');
  return detail?.message || '操作失败，请重试。';
}
export async function api(path, {method='GET', body, form=false} = {}) {
  const headers = {};
  if (token()) headers.Authorization = `Bearer ${token()}`;
  if (body !== undefined && !form) headers['Content-Type'] = 'application/json';
  let response;
  try {response = await fetch(path, {method, headers, body: body === undefined ? undefined : form ? body : JSON.stringify(body)});}
  catch {throw new Error('无法连接服务，请检查网络和后端是否正在运行。');}
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  // 不记录密码、账号登录请求或令牌，调试面板仅显示业务接口。
  if (!path.startsWith('/auth/')) {
    state.lastTrace = {method, path, status: response.status, request: body ?? null, response: data};
    if ($('#debug-data')) $('#debug-data').textContent = JSON.stringify(state.lastTrace, null, 2);
  }
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith('/auth/')) {
      clearAuth(); window.dispatchEvent(new Event('auth-expired'));
    }
    const error = new Error(errorText(data?.detail) || `请求失败（${response.status}）`);
    error.status = response.status; error.detail = data?.detail;
    throw error;
  }
  return data;
}
export function debugPanel() {return '<details class="debug"><summary>接口调试信息</summary><p>仅展示最近一次业务请求，不显示登录密码或令牌。</p><pre id="debug-data">'+esc(JSON.stringify(state.lastTrace, null, 2) || '暂无请求')+'</pre></details>';}
let toastTimer, modalSource = null;
export function toast(message) {$('#toast').textContent=message; $('#toast').classList.add('visible'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),3500);}
export function modal(title, content) {
  const element=$('#modal');
  if(element.open) throw new Error('请先关闭当前编辑窗口。');
  element.innerHTML=`<div class="dialog-head"><h2 id="modal-title">${esc(title)}</h2><button class="close-modal" aria-label="关闭">×</button></div>${content}`;
  element.querySelector('.close-modal').onclick=()=>closeModal();
  element.oncancel=event=>{event.preventDefault();closeModal();};
  element.onclose=()=>{if(!element.open){modalSource?.dispose();modalSource=null;}};
  element.showModal(); return element;
}
export async function closeModal(options={}) {
  if(!options.saved && modalSource && !await requestLeave(modalSource))return false;
  modalSource?.dispose();modalSource=null;$('#modal').close();return true;
}
export async function logout() {
  if(!await requestLeave())return;
  clearAuth();window.dispatchEvent(new Event('auth-expired'));
}
export function formError(form, message) {const box=form.querySelector('[data-error]'); if(box){box.textContent=message;box.hidden=!message;}}
export function bindForm(form, action) {
  // 仅管理弹窗跟踪未保存编辑，登录表单不记录密码快照。
  if(form.closest('#modal')){
    const baseline=formSnapshot(form);
    modalSource=registerUnsaved({isDirty:()=>formSnapshot(form)!==baseline,isBusy:()=>form.dataset.busy==='true'});
  }
  form.addEventListener('submit', async event => {
    event.preventDefault(); if(form.dataset.busy==='true')return;
    formError(form,''); const buttons=[...form.querySelectorAll('button')];
    const disabled=buttons.map(button=>button.disabled); buttons.forEach(button=>button.disabled=true); form.dataset.busy='true';
    try {await action(new FormData(form));} catch(error) {formError(form,error.message);}
    finally {buttons.forEach((button,index)=>button.disabled=disabled[index]);delete form.dataset.busy;}
  });
}
export function confirmAction(title, description, action, label='确认') {
  const element=modal(title,`<form><p class="muted">${esc(description)}</p><p class="error-banner" data-error hidden></p><div class="dialog-actions"><button type="button" class="secondary" id="cancel-confirm">取消</button><button class="danger">${esc(label)}</button></div></form>`);
  element.querySelector('#cancel-confirm').onclick=closeModal;
  bindForm(element.querySelector('form'),async()=>{await action();closeModal({saved:true});});
}
export function renderShell(title, content) {
  $('#app').innerHTML=`<aside class="sidebar"><a href="#/" class="brand"><span>▤</span>问序</a><div class="workspace">我的工作空间</div><p class="nav-label">工作台</p><nav><a class="nav-link ${!/^#\/(questions|banks|shared-question|shared-bank|source)/.test(location.hash)?'active':''}" href="#/">▤　我的问卷</a><a class="nav-link ${/^#\/(questions|shared-question|source)/.test(location.hash)?'active':''}" href="#/questions">▦　常用题</a><a class="nav-link ${/^#\/(banks|shared-bank)/.test(location.hash)?'active':''}" href="#/banks">▥　题库</a><a class="nav-link" href="/docs" target="_blank" rel="noopener">↗　接口文档</a></nav><div class="sidebar-bottom"><span class="user-name"><span class="avatar">${esc((state.user?.username||'用').slice(0,1))}</span>${esc(state.user?.username)}</span><button class="link-button" id="logout">退出</button></div></aside><div class="shell"><header class="topbar"><span>工作空间 / ${esc(title)}</span><span>问卷管理与填写</span></header><main class="main">${content}<footer class="page-footer"><span>问序 · 问卷工作台</span><a href="/docs" target="_blank" rel="noopener">Swagger 调试 ↗</a></footer></main></div>`;
  $('#logout').onclick=logout;
}
