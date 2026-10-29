import {renderQuestionAnalysis} from './pages/question-analysis.js?v=1';
import {api, state, $, esc, date, statuses, token, setToken, clearAuth, renderShell, modal, closeModal, bindForm, toast, debugPanel} from './shared/common.js?v=4';
import {renderEditor} from './pages/editor.js?v=7';
import {renderFill} from './pages/fill.js?v=4';
import {renderResults} from './pages/results.js?v=4';
import {renderSurveyVersions} from './pages/survey-versions.js?v=2';
import {renderLibrary, renderLibraryQuestion} from './pages/library.js?v=3';
import {requestLeave, resetUnsavedTracking} from './shared/guards.js';

import {renderBanks,renderBank} from './pages/banks.js?v=1';
import {renderSharedQuestion,renderSource} from './pages/shared-library.js?v=3';

let routeVersion=0,filter='all',query='',currentHref=location.href,navigationVersion=0;
function authView(register=false) {
  const filling=location.hash.startsWith('#/fill/');
  $('#app').innerHTML=`<div class="auth-shell"><section class="auth-brand"><a href="#/" class="brand"><span>▤</span>问序</a><h1>从一个好问题开始。</h1><p>设计问卷，收集回答，了解真实的想法。</p></section><section class="auth-panel"><form class="auth-form"><div class="eyebrow">YOUR WORKSPACE</div><h2>${register?'创建账号':'欢迎回来'}</h2><p class="muted">${filling?'请先登录，随后继续填写这份问卷。':register?'注册后即可创建和填写问卷。':'登录你的问卷工作空间。'}</p><label class="field">用户名<input name="username" autocomplete="username" maxlength="50" required placeholder="请输入用户名"></label><label class="field">密码<input name="password" type="password" autocomplete="${register?'new-password':'current-password'}" ${register?'minlength="8" maxlength="128"':''} required placeholder="${register?'8～128个字符':'请输入密码'}"></label><p class="error-banner" data-error hidden></p><button class="primary">${register?'注册并登录':'登录'}</button><p class="auth-switch">${register?'已有账号？':'还没有账号？'} <button type="button" class="link-button" id="switch-auth">${register?'去登录':'注册账号'}</button></p><small>登录状态仅保留在当前浏览器标签页中。</small><a class="auth-top-link" href="/docs" target="_blank" rel="noopener">打开 Swagger 接口文档 ↗</a></form></section></div>`;
  $('#switch-auth').onclick=()=>authView(!register);
  bindForm($('.auth-form'),async data=>{
    const username=data.get('username').trim(),password=data.get('password');
    if(register)await api('/auth/register',{method:'POST',body:{username,password}});
    const result=await api('/auth/token',{method:'POST',body:new URLSearchParams({username,password}),form:true});
    setToken(result.access_token);state.user=await api('/auth/me');toast(register?'注册成功，已登录':'登录成功');await route();
  });
}

async function allSurveys(){
  const result=[];
  for(let skip=0;;skip+=100){const batch=await api(`/surveys?skip=${skip}&limit=100`);result.push(...batch);if(batch.length<100)break;}
  return result;
}
async function dashboard(version){
  const surveys=await allSurveys();if(version!==routeVersion)return;state.surveys=surveys;
  renderShell('我的问卷',`<section class="heading"><div><div class="eyebrow">YOUR WORKSPACE</div><h1>我的问卷</h1><p>创建问卷、分享链接，查看每一次回答。</p></div><button class="primary" id="create-survey">＋ 创建问卷</button></section><section class="welcome"><h2>把想了解的事，变成一个好问题。</h2><p>从草稿开始设计，发布后通过链接邀请填写。</p></section><section class="metrics"><div><span>全部问卷</span><strong>${surveys.length}</strong></div><div><span>正在收集</span><strong>${surveys.filter(s=>s.status==='published').length}</strong></div><div><span>累计回答</span><strong id="total-responses">…</strong></div><div><span>待完善草稿</span><strong>${surveys.filter(s=>s.status==='draft').length}</strong></div></section><div class="toolbar"><div class="tabs">${[['all','全部问卷'],['published','收集中'],['draft','草稿'],['closed','已关闭']].map(([value,label])=>`<button class="tab ${value===filter?'active':''}" data-filter="${value}">${label}</button>`).join('')}</div><input class="search" id="search" type="search" aria-label="搜索问卷" placeholder="搜索问卷名称…" value="${esc(query)}"></div><div id="list-note" class="status-note"></div><div class="cards" id="survey-cards"></div>${debugPanel()}`);
  const counts=new Map();
  function draw(){
    const visible=surveys.filter(s=>(filter==='all'||s.status===filter)&&s.title.toLowerCase().includes(query.toLowerCase()));
    $('#survey-cards').innerHTML=visible.length?visible.map(s=>`<article class="card"><div class="card-main"><div class="card-top"><span class="card-icon">▤</span><span class="badge ${s.status}">● ${statuses[s.status]}</span></div><h3>${esc(s.title)}</h3><p class="card-description">${esc(s.description||'暂无说明')}</p><div class="card-numbers"><div><strong>${counts.has(s.id)?counts.get(s.id):'—'}</strong><small>收到回答</small></div><div><strong>${s.questions.length}</strong><small>道题目</small></div></div></div><div class="card-footer"><small>v${esc(s.version ?? 1)} · 创建于 ${date(s.createdAt)}</small><a href="#/edit/${s.id}">${s.status==='draft'?'编辑问卷':'管理问卷'} ↗</a><a href="#/results/${s.id}">查看数据</a><a href="#/survey-versions/${s.id}">版本历史</a></div></article>`).join(''):'<div class="panel empty">'+(surveys.length?'没有找到匹配的问卷。':'还没有问卷，点击“创建问卷”开始。')+'</div>';
  }
  draw();$('#search').oninput=event=>{query=event.target.value;draw();};
  document.querySelectorAll('[data-filter]').forEach(button=>button.onclick=()=>{filter=button.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b===button));draw();});
  $('#create-survey').onclick=()=>{
    const element=modal('创建问卷',`<form><label class="field">问卷标题<input name="title" required placeholder="例如：校园生活满意度调查"></label><label class="field">问卷说明<textarea name="description" rows="3" placeholder="向填写者介绍这份问卷"></textarea></label><label class="check-label"><input name="allowAnonymous" type="checkbox">允许匿名填写（仍需登录）</label><label class="check-label"><input name="allowRepeat" type="checkbox">允许同一用户多次提交</label><p class="note">创建后可在草稿的“修改基本信息”中继续调整。发布后这些设置锁定。</p><p class="error-banner" data-error hidden></p><div class="dialog-actions"><button class="primary">创建草稿 →</button></div></form>`);
    bindForm(element.querySelector('form'),async data=>{const result=await api('/surveys',{method:'POST',body:{title:data.get('title').trim(),description:data.get('description'),allowAnonymous:data.has('allowAnonymous'),allowRepeat:data.has('allowRepeat')}});closeModal({saved:true});location.hash=`#/edit/${result.id}`;});
  };
  // 分批获取真实计数；任何失败都显示未知，而不是伪造为0。
  let failed=0;
  for(let offset=0;offset<surveys.length;offset+=5){
    await Promise.all(surveys.slice(offset,offset+5).map(async survey=>{try{const result=await api(`/surveys/${survey.id}/statistics`);counts.set(survey.id,result.submissionCount);}catch{failed++;}}));
    if(version!==routeVersion)return;
    draw();
  }
  if(version!==routeVersion)return;
  $('#total-responses').textContent=failed?'—':[...counts.values()].reduce((sum,n)=>sum+n,0);
  $('#list-note').textContent=failed?'部分回答数暂未加载，请刷新重试。':`共 ${surveys.length} 份问卷 · 数据来自已保存的提交`;
}

export async function route(){
  const version=++routeVersion;
  const modalElement=$('#modal');if(modalElement.open)modalElement.close();
  resetUnsavedTracking();
  if(!token()){authView();return;}
  $('#app').innerHTML='<div class="loading">正在加载…</div>';
  try{
    if(!state.user)state.user=await api('/auth/me');
    if(version!==routeVersion)return;
    const parts=location.hash.replace(/^#\/?/,'').split('/');
    if(parts[0]==='question-analysis'&&parts[1])await renderQuestionAnalysis(parts[1],()=>version===routeVersion);
    else if(parts[0]==='shared-question'&&parts[1])await renderSharedQuestion(parts[1],()=>version===routeVersion);
    else if(parts[0]==='shared-bank'&&parts[1])await renderBank(parts[1],()=>version===routeVersion,true);
    else if(parts[0]==='banks'&&parts[1])await renderBank(parts[1],()=>version===routeVersion);
    else if(parts[0]==='banks')await renderBanks(()=>version===routeVersion);
    else if(parts[0]==='source'&&parts[1]&&parts[2])await renderSource(parts[1],parts[2],()=>version===routeVersion);
    else if(parts[0]==='questions'&&parts[1])await renderLibraryQuestion(parts[1],()=>version===routeVersion,parts[2]==='latest');
    else if(parts[0]==='questions')await renderLibrary(()=>version===routeVersion);
    else if(parts[0]==='fill'&&parts[1])await renderFill(parts[1],false);
    else if(parts[0]==='preview'&&parts[1])await renderFill(parts[1],true);
    else if(parts[0]==='survey-versions'&&parts[1])await renderSurveyVersions(parts[1],()=>version===routeVersion);
    else if(parts[0]==='edit'&&parts[1])await renderEditor(parts[1]);
    else if(parts[0]==='results'&&parts[1])await renderResults(parts[1]);
    else await dashboard(version);
  }catch(error){
    if(version!==routeVersion)return;
    if(error.status===401){clearAuth();authView();return;}
    renderShell('加载失败',`<h1>暂时无法打开页面</h1><p class="error-banner">${esc(error.message)}</p><div class="actions"><button class="primary" id="retry">重新加载</button><a class="secondary" href="#/">返回工作台</a></div>${debugPanel()}`);
    $('#retry').onclick=route;
  }
}
window.addEventListener('hashchange',async()=>{
  const version=++navigationVersion,target=location.href;
  if(!await requestLeave()){
    if(version===navigationVersion)history.replaceState(null,'',currentHref);
    return;
  }
  if(version!==navigationVersion)return;
  currentHref=target;window.scrollTo(0,0);route();
});
window.addEventListener('auth-expired',()=>{++routeVersion;resetUnsavedTracking();if($('#modal').open)$('#modal').close();authView();});
route();
