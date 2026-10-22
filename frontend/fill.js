import {api,state,$,esc,date,types,logout,debugPanel} from './common.js?v=2';
import {validateAnswer,hasAnswer,pruneAnswers,submissionAnswers} from './logic.mjs?v=2';
import {registerUnsaved} from './guards.js';

// 仅保留当前页面会话中的未提交输入，刷新后不承诺恢复。
const drafts=new Map();
export async function renderFill(identifier,isPreview){
  const survey=await api(isPreview?`/surveys/${identifier}`:`/survey/${identifier}`);
  const questions=[...survey.questions].sort((a,b)=>a.order-b.order);
  const key=`${state.user.id}/${isPreview?'preview':'fill'}/${identifier}`;
  if(!drafts.has(key))drafts.set(key,{});
  const answers=drafts.get(key);
  let checked=false,busy=false,finished=false;
  function hint(q){
    const v=q.validation;
    if(q.type==='single')return '请选择一项。';
    if(q.type==='multiple')return `请选择 ${v.minChoices??0}～${v.maxChoices??q.options.length} 项。`;
    if(q.type==='text')return `如需填写，请输入 ${v.minLength??0}～${v.maxLength??'不限'} 个字符。`;
    return `${v.integerOnly?'请填写整数':'请填写数字'}，允许范围 ${v.minValue??'不限'}～${v.maxValue??'不限'}。`;
  }
  function control(q){
    const answer=answers[q.questionId];
    if(['single','multiple'].includes(q.type))return `<div class="fill-options">${q.options.map(o=>`<label class="fill-option"><input type="${q.type==='single'?'radio':'checkbox'}" name="answer-${q.questionId}" value="${o.optionId}" ${answer?.selectedOptionIds?.includes(o.optionId)?'checked':''} aria-describedby="error-${q.questionId}"><span>${esc(o.text)}</span></label>`).join('')}</div>`;
    if(q.type==='text')return `<textarea rows="5" name="answer-${q.questionId}" aria-label="${esc(q.title)}" aria-describedby="error-${q.questionId}" placeholder="请输入你的回答">${esc(answer?.value??'')}</textarea><div class="char-count" data-count="${q.questionId}"></div>`;
    return `<input type="number" step="${q.validation.integerOnly?'1':'any'}" name="answer-${q.questionId}" value="${esc(answer?.value??'')}" aria-label="${esc(q.title)}" aria-describedby="error-${q.questionId}" placeholder="请输入数值">`;
  }
  $('#app').innerHTML=`<header class="fill-header"><a class="brand" href="#/"><span>▤</span>问序</a><div class="actions"><span class="user-name">${esc(state.user.username)}</span><button class="link-button" id="fill-logout">退出</button><a href="${isPreview?'#/edit/'+identifier:'#/'}">${isPreview?'← 返回编辑':'返回工作台'}</a></div></header><div class="fill-progress"><div id="fill-progress-bar"></div></div><main class="survey-sheet"><section class="survey-intro" id="fill-intro"><div class="eyebrow">${isPreview?'DRAFT PREVIEW':'QUESTIONNAIRE'}</div><h1>${esc(survey.title)}</h1><p class="survey-description">${esc(survey.description||'请根据实际情况填写，感谢你的参与。')}</p><div class="survey-meta"><span>${questions.length} 道题目</span><span>* 为必答</span><span>截止：${date(survey.deadline)}</span></div>${isPreview?'<p class="note">草稿预览：会验证填写结果，不提交或保存答卷。</p>':''}</section><form id="fill-form" novalidate><div class="form-heading"><span>向下滚动，依次填写</span><span id="completion"></span></div><p class="note" id="path-note" hidden role="status"></p>${questions.map(q=>`<fieldset class="fill-question" id="q-${q.questionId}" data-qid="${q.questionId}"><legend><span class="question-number">${String(q.order).padStart(2,'0')}</span>${esc(q.title)}${q.required?'<span class="required">*</span>':'<span class="optional">选填</span>'}</legend><p class="question-hint">${esc(hint(q))}</p>${control(q)}<p class="question-error" id="error-${q.questionId}" hidden></p></fieldset>`).join('')}${survey.allowAnonymous&&!isPreview?'<label class="check-label" style="margin-top:25px"><input type="checkbox" id="anonymous">匿名提交（对创建者隐藏身份）</label>':''}<div class="submit-area"><div><p class="error-banner" id="submit-error" role="alert" hidden></p><small>确认无误后统一提交。${isPreview?'本次预览不会保存。':'未提交内容不会自动保存；刷新或离开可能丢失。'}</small></div><button class="primary" id="submit-fill" ${questions.length?'':'disabled'}>${isPreview?'完成预览':'提交问卷'} →</button></div></form><section class="fill-success" id="fill-success" hidden tabindex="-1"></section>${debugPanel()}</main><footer class="fill-footer">问序 · ${isPreview?'问卷预览':'在线问卷'}</footer>`;
  $('#fill-logout').onclick=logout;
  const form=$('#fill-form');
  const unsaved=registerUnsaved({
    isDirty:()=>!finished&&(questions.some(q=>hasAnswer(q,answers[q.questionId]))||Boolean($('#anonymous')?.checked)),
    isBusy:()=>busy,
    onDiscard:()=>{drafts.delete(key);},
  });
  function mark(q,message){
    const section=$(`#q-${q.questionId}`),error=$(`#error-${q.questionId}`);
    if(!section)return;error.textContent=message;error.hidden=!message;section.classList.toggle('invalid',Boolean(message));
    section.querySelectorAll('input,textarea').forEach(input=>input.setAttribute('aria-invalid',String(Boolean(message))));
  }
  function sync(){
    const path=pruneAnswers(questions,answers),ids=new Set(path.map(q=>q.questionId));
    for(const q of questions){
      const section=$(`#q-${q.questionId}`);section.hidden=!ids.has(q.questionId);section.disabled=!ids.has(q.questionId);
      if(section.hidden){section.querySelectorAll('input,textarea').forEach(input=>{if(['checkbox','radio'].includes(input.type))input.checked=false;else input.value='';});mark(q,'');}
      else if(checked)mark(q,validateAnswer(q,answers[q.questionId]));
      if(q.type==='text')document.querySelector(`[data-count="${q.questionId}"]`).textContent=`${[...String(answers[q.questionId]?.value??'')].length}${q.validation.maxLength!==undefined?' / '+q.validation.maxLength:''} 字符`;
    }
    const answered=path.filter(q=>hasAnswer(q,answers[q.questionId])).length;
    $('#completion').textContent=`已填写 ${answered} / ${path.length} 题`;
    $('#fill-progress-bar').style.width=(path.length?answered/path.length*100:0)+'%';
    const hidden=questions.filter(q=>!ids.has(q.questionId));
    $('#path-note').hidden=hidden.length===0;$('#path-note').textContent=hidden.length?`根据当前答案，已跳过第 ${hidden.map(q=>q.order).join('、')} 题。`:'';
    return path;
  }
  form.addEventListener('input',event=>{
    const section=event.target.closest('[data-qid]');if(!section)return;
    const q=questions.find(q=>q.questionId===section.dataset.qid);
    answers[q.questionId]=['single','multiple'].includes(q.type)?{selectedOptionIds:[...section.querySelectorAll('input:checked')].map(input=>input.value)}:{value:event.target.value};
    sync();
    if(checked){const count=pruneAnswers(questions,answers).filter(q=>validateAnswer(q,answers[q.questionId])).length;$('#submit-error').hidden=count===0;if(count)$('#submit-error').textContent=`还有 ${count} 道题需要检查。`;}
  });
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy)return;checked=true;
    const path=sync(),invalid=path.filter(q=>validateAnswer(q,answers[q.questionId]));
    const banner=$('#submit-error');
    if(invalid.length){banner.textContent=`还有 ${invalid.length} 道题需要检查。`;banner.hidden=false;focusQuestion(invalid[0].questionId);return;}
    banner.hidden=true;busy=true;const button=$('#submit-fill');button.disabled=true;button.textContent='正在检查…';
    try{
      let receipt;
      if(isPreview){
        for(const q of path)await api(`/surveys/${identifier}/questions/${q.questionId}/preview`,{method:'POST',body:submissionAnswers([q],answers)[0]?Object.fromEntries(Object.entries(submissionAnswers([q],answers)[0]).filter(([key])=>key!=='questionId')):{}});
      }else{
        receipt=await api(`/survey/${identifier}/responses`,{method:'POST',body:{isAnonymous:$('#anonymous')?.checked??false,answers:submissionAnswers(path,answers)}});
      }
      drafts.delete(key);finished=true;unsaved.dispose();
      if(!$('#fill-form'))return;
      form.hidden=true;$('#fill-intro').hidden=true;$('#fill-progress-bar').style.width='100%';
      const success=$('#fill-success');success.hidden=false;
      success.innerHTML=`<span class="success-mark">✓</span><h1>${isPreview?'预览完成':'提交成功，谢谢你的回答。'}</h1><p class="muted">${isPreview?'服务器已检查当前答案，本次预览没有保存答卷。':'你的答卷已保存。'}</p>${receipt?`<p class="code">回执编号：${esc(receipt.id)}</p><p class="muted">${date(receipt.submittedAt)}</p>`:''}<div class="actions"><a class="primary" href="${isPreview?'#/edit/'+identifier:'#/'}">${isPreview?'返回编辑':'返回工作台'} →</a></div>`;
      success.focus({preventScroll:true});window.scrollTo({top:0,behavior:'smooth'});
    }catch(error){
      if(!$('#submit-error'))return;
      banner.textContent=error.message;banner.hidden=false;
      if(error.detail?.questionId){const q=questions.find(q=>q.questionId===error.detail.questionId);if(q){mark(q,error.message);focusQuestion(q.questionId);}}
      else banner.scrollIntoView({behavior:'smooth',block:'center'});
    }finally{busy=false;button.disabled=false;button.textContent=isPreview?'完成预览 →':'提交问卷 →';}
  });
  function focusQuestion(id){const section=$(`#q-${id}`);section?.querySelector('input,textarea')?.focus({preventScroll:true});section?.scrollIntoView({behavior:'smooth',block:'start'});}
  sync();
}
