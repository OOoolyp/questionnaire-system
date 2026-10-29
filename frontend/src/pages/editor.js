import {api,$,esc,date,types,statuses,renderShell,modal,closeModal,bindForm,toast,confirmAction,debugPanel} from '../shared/common.js?v=4';
import {createSurveyVersion} from './survey-versions.js?v=2';
import {openReusePicker} from '../shared/reuse-picker.js?v=2';

function limitsText(question){
  const v=question.validation||{};
  if(question.type==='multiple')return `选择 ${v.minChoices??0}～${v.maxChoices??question.options.length} 项`;
  if(question.type==='text')return `长度 ${v.minLength??0}～${v.maxLength??'不限'} 字符`;
  if(question.type==='number')return `${v.integerOnly?'整数':'数字'}，范围 ${v.minValue??'不限'}～${v.maxValue??'不限'}`;
  return '只能选择一项';
}
export async function renderEditor(id){
  const survey=await api(`/surveys/${id}`),draft=survey.status==='draft';
  renderShell('问卷管理',`<section class="heading"><div><div class="eyebrow">SURVEY WORKSPACE</div><h1>${esc(survey.title)}</h1><p>${esc(survey.description||'暂无问卷说明')}</p></div><div class="actions"><a class="secondary" href="#/">← 问卷列表</a><a class="secondary" href="#/${draft?'preview/'+id:'fill/'+survey.shareToken}">${draft?'填写预览':'打开填写页'}</a><a class="secondary" href="#/results/${id}">查看数据</a><a class="secondary" href="#/survey-versions/${id}">版本历史</a><button class="secondary" id="create-survey-version">创建新版本</button></div></section><p id="editor-error" class="error-banner" hidden></p><div class="editor-layout"><section><div class="toolbar"><strong>题目 · ${survey.questions.length}</strong>${draft?'<div class="actions"><button class="secondary" id="pick-question">从常用题或题库选题</button><button class="primary" id="add-question">＋ 添加题目</button></div>':'<span class="muted">已发布题目不可修改</span>'}</div>${survey.questions.length?survey.questions.map(q=>`<div class="question-block">${draft?`<div class="insert-zone"><span></span><button class="insert-question" data-before="${q.questionId}" aria-label="在第${q.order}题前添加题目" title="在此处添加题目">＋</button><span></span></div>`:''}<article class="question-item"><div class="question-meta"><span>题序 ${q.order}</span><span>${types[q.type]}</span><span>${q.required?'必答':'可选'}</span>${q.sourceQuestionId?'<span>引用常用题</span>':''}</div><h3>${esc(q.title)}</h3><p class="muted" style="font-size:11px">${esc(limitsText(q))}</p>${q.options?.length?'<ol class="question-options">'+q.options.map(o=>`<li>${esc(o.text)}</li>`).join('')+'</ol>':''}<p class="status-note">${q.jumpRules.length?`${q.jumpRules.length} 条跳转规则，按顺序匹配`:'无条件跳转，按题序继续'}</p>${draft?`<div class="question-actions"><button class="secondary" data-edit="${q.questionId}">${q.sourceQuestionId?'题序与必答设置':'修改题目'}</button>${q.sourceQuestionId?`<button class="secondary" data-switch="${q.questionId}">切换版本</button><button class="secondary" data-detach="${q.questionId}">转为独立题</button>`:''}<button class="secondary" data-rules="${q.questionId}">跳转规则</button><button class="danger" data-delete="${q.questionId}">删除题目</button></div>`:''}<div class="question-actions">${q.sourceQuestionId?`<a class="secondary" href="#/source/${id}/${q.questionId}">查看来源版本</a>`:''}<button class="secondary" data-save-library="${q.questionId}">保存到常用题</button></div></article></div>`).join(''):'<div class="panel empty">还没有题目，添加第一道题开始设计。</div>'}</section><aside><div class="panel aside-panel"><h3>问卷设置</h3><span class="badge ${survey.status}">● ${statuses[survey.status]}</span><dl class="detail-list"><dt>问卷版本</dt><dd>v${esc(survey.version ?? 1)}</dd><dt>匿名填写</dt><dd>${survey.allowAnonymous?'允许，仍需登录':'不允许'}</dd><dt>重复填写</dt><dd>${survey.allowRepeat?'允许多次提交':'每人只能提交一次'}</dd><dt>截止时间</dt><dd>${date(survey.deadline)}</dd><dt>创建时间</dt><dd>${date(survey.createdAt)}</dd></dl>${draft?'<button class="secondary" id="edit-info" style="width:100%;margin-bottom:12px">修改基本信息</button><button class="primary" id="publish">发布问卷 →</button><p>发布后题目和跳转规则锁定，请先检查填写预览。</p>':`<button class="secondary" id="share">查看分享链接</button>${survey.status==='published'?'<button class="danger" id="close-survey" style="margin-top:12px">关闭收集</button>':''}`}<details class="debug"><summary>查看问卷标识</summary><p class="code">${esc(id)}</p></details></div></aside></div>${debugPanel()}`);
  const refresh=()=>renderEditor(id);
  $('#create-survey-version').onclick=()=>createSurveyVersion(survey);
  const report=error=>{const box=$('#editor-error');if(box){box.textContent=error.message;box.hidden=false;}};
  document.querySelectorAll('[data-save-library]').forEach(button=>button.onclick=()=>confirmAction('保存到常用题','将当前题目的内容另存为一道新的常用题。原问卷题目保持现状，题序、必答设置和跳转规则不保存到常用题。',async()=>{
    await api(`/surveys/${id}/questions/${button.dataset.saveLibrary}/save-to-library`,{method:'POST'});toast('已保存，可在常用题中查看');
  },'保存常用题'));

  if(draft){
    $('#pick-question').onclick=()=>openReusePicker(survey,refresh).catch(report);
    document.querySelectorAll('[data-switch]').forEach(button=>button.onclick=()=>openReusePicker(survey,refresh,survey.questions.find(q=>q.questionId===button.dataset.switch)).catch(report));
    document.querySelectorAll('[data-detach]').forEach(button=>button.onclick=()=>{const q=survey.questions.find(q=>q.questionId===button.dataset.detach);confirmAction('转为独立题','保留当前内容、选项和跳转规则，移除常用题版本关联。之后可以在本问卷中修改内容。',async()=>{await api(`/surveys/${id}/questions/${q.questionId}/detach`,{method:'POST',body:{expectedSourceQuestionId:q.sourceQuestionId}});await refresh();toast('已转为独立题');},'转为独立题');});
    $('#edit-info').onclick=()=>basicInfoDialog(survey,refresh);
    $('#add-question').onclick=()=>questionDialog(survey,null,refresh);
    document.querySelectorAll('[data-before]').forEach(button=>button.onclick=()=>questionDialog(survey,null,refresh,survey.questions.find(q=>q.questionId===button.dataset.before)));
    document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>questionDialog(survey,survey.questions.find(q=>q.questionId===b.dataset.edit),refresh));
    document.querySelectorAll('[data-rules]').forEach(b=>b.onclick=()=>rulesDialog(survey,survey.questions.find(q=>q.questionId===b.dataset.rules),refresh));
    document.querySelectorAll('[data-delete]').forEach(b=>b.onclick=()=>confirmAction('删除题目','删除后无法恢复。如果此题被跳转规则引用，服务器会拒绝删除，请先修改相关规则。',async()=>{await api(`/surveys/${id}/questions/${b.dataset.delete}`,{method:'DELETE'});await refresh();toast('题目已删除');},'删除题目'));
    $('#publish').onclick=()=>{
      const element=modal('发布问卷',`<form><p class="muted">发布后不能修改题目和规则，可随时关闭收集。</p><label class="field">截止时间（选填）<input name="deadline" type="datetime-local"><small>按你当前设备的本地时区设置，留空表示不限时间。</small></label><p class="error-banner" data-error hidden></p><div class="dialog-actions"><button class="primary">确认发布</button></div></form>`);
      bindForm(element.querySelector('form'),async data=>{const value=data.get('deadline');await api(`/surveys/${id}/publish`,{method:'POST',body:{deadline:value?new Date(value).toISOString():null}});closeModal({saved:true});await refresh();toast('问卷已发布');});
    };
  }else{
    $('#share').onclick=()=>{
      const url=new URL(`#/fill/${survey.shareToken}`,location.href).href;
      const element=modal('分享问卷',`<p class="muted">填写者需先登录。${survey.status==='closed'?'问卷已关闭，链接不再接收填写。':''}</p><label class="field">填写链接<input readonly value="${esc(url)}" id="share-url"></label><div class="actions"><button class="primary" id="copy-link">复制链接</button><a class="secondary" href="#/fill/${survey.shareToken}" id="open-share">打开填写页</a></div>`);
      element.querySelector('#open-share').onclick=closeModal;
      element.querySelector('#copy-link').onclick=async()=>{try{await navigator.clipboard.writeText(url);toast('分享链接已复制');}catch{element.querySelector('#share-url').select();toast('已选中链接，请按 Ctrl+C 复制');}};
    };
    if($('#close-survey'))$('#close-survey').onclick=()=>confirmAction('关闭问卷','关闭后将拒绝新的填写；当前版本不支持重新发布。已有答卷和统计仍会保留。',async()=>{await api(`/surveys/${id}/close`,{method:'POST'});await refresh();toast('已关闭问卷');},'确认关闭');
  }
}

function basicInfoDialog(survey,refresh){
  const element=modal('修改草稿基本信息',`<form><label class="field">问卷标题<input name="title" required value="${esc(survey.title)}"></label><label class="field">问卷说明<textarea name="description" rows="4">${esc(survey.description)}</textarea></label><label class="check-label"><input name="allowAnonymous" type="checkbox" ${survey.allowAnonymous?'checked':''}>允许匿名填写（仍需登录）</label><label class="check-label"><input name="allowRepeat" type="checkbox" ${survey.allowRepeat?'checked':''}>允许同一用户多次提交</label><p class="note">只修改基本信息，题目、选项和跳转规则保持不变。发布后不可修改。</p><p class="error-banner" data-error hidden></p><div class="dialog-actions"><button class="primary">保存基本信息</button></div></form>`);
  bindForm(element.querySelector('form'),async data=>{
    await api(`/surveys/${survey.id}`,{method:'PATCH',body:{title:data.get('title').trim(),description:data.get('description'),allowAnonymous:data.has('allowAnonymous'),allowRepeat:data.has('allowRepeat')}});
    closeModal({saved:true});await refresh();toast('草稿基本信息已保存');
  });
}

function questionDialog(survey,question,refresh,before=null){
  if(question?.sourceQuestionId){referenceSettingsDialog(survey,question,refresh);return;}
  const current=question||{title:'',type:'single',order:before?.order??Math.max(0,...survey.questions.map(q=>q.order))+1,required:false,options:[],validation:{}};
  const element=modal(question?'修改题目':before?'在此处插入题目':'添加题目',`<form id="question-form"><div class="row"><label class="field">题型<select name="type">${Object.entries(types).map(([value,label])=>`<option value="${value}" ${value===current.type?'selected':''}>${label}</option>`).join('')}</select></label><label class="field">题序<input name="order" type="number" min="1" max="2147483647" step="1" value="${current.order}" ${before?'readonly':''} required></label></div><label class="field">题干<input name="title" value="${esc(current.title)}" required placeholder="请输入问题"></label><label class="check-label"><input name="optional" type="checkbox" ${!current.required?'checked':''}>是否可选（勾选后允许不回答）</label><div id="question-fields"></div><p class="note">${before?'新题将插入当前题目前，后续题序自动顺移。':'题序不能重复。'}更改题型或移除被规则引用的选项时，请先调整跳转规则。</p><p class="error-banner" data-error hidden></p><div class="dialog-actions"><button class="primary">保存题目</button></div></form>`);
  const form=element.querySelector('form');
  function specifics(type,source){
    const validation=source?.validation||{};
    const choice=['single','multiple'].includes(type);
    const fields=type==='multiple'?[['minChoices','最少选择数'],['maxChoices','最多选择数']]:type==='text'?[['minLength','最小字符数'],['maxLength','最大字符数']]:type==='number'?[['minValue','最小值'],['maxValue','最大值']]:[];
    element.querySelector('#question-fields').innerHTML=(choice?'<label class="field">选项（至少两项）</label><div id="option-rows"></div><button type="button" class="secondary" id="add-option">＋ 添加选项</button>':'')+`<div class="row" style="margin-top:18px">${fields.map(([key,label])=>`<label class="field">${label}<input name="${key}" type="number" ${type!=='number'?'min="0" max="2147483647" step="1"':'step="any"'} value="${validation[key]??''}" placeholder="不限"></label>`).join('')}</div>`+(type==='number'?`<label class="check-label"><input name="integerOnly" type="checkbox" ${validation.integerOnly?'checked':''}>仅允许整数</label>`:'');
    if(choice){
      const addOption=option=>{
        const row=document.createElement('div');row.className='option-row';if(option?.optionId)row.dataset.id=option.optionId;
        row.innerHTML=`<input aria-label="选项文字" required placeholder="选项文字" value="${esc(option?.text||'')}"><button type="button" class="remove-option" aria-label="删除选项">×</button>`;
        row.querySelector('button').onclick=()=>row.remove();element.querySelector('#option-rows').append(row);
      };
      (source?.options?.length?source.options:[{},{}]).forEach(addOption);
      element.querySelector('#add-option').onclick=()=>addOption({});
    }
  }
  specifics(current.type,current);
  form.elements.type.onchange=()=>specifics(form.elements.type.value,null);
  bindForm(form,async data=>{
    const type=data.get('type'),validation={};
    for(const key of ['minChoices','maxChoices','minLength','maxLength','minValue','maxValue'])if(data.has(key)&&data.get(key)!=='')validation[key]=Number(data.get(key));
    if(type==='number')validation.integerOnly=data.has('integerOnly');
    const payload={type,title:data.get('title').trim(),order:Number(data.get('order')),required:!data.has('optional'),validation};
    if(['single','multiple'].includes(type)){
      payload.options=[...form.querySelectorAll('.option-row')].map((row,index)=>({text:row.querySelector('input').value.trim(),order:index+1,...(row.dataset.id?{optionId:row.dataset.id}:{})}));
      if(payload.options.length<2)throw new Error('选择题至少需要两个选项。');
    }
    const path=before?`/surveys/${survey.id}/questions/${before.questionId}/insert`:`/surveys/${survey.id}/questions${question?'/'+question.questionId:''}`;
    const saved=await api(path,{method:question?'PUT':'POST',body:payload});closeModal({saved:true});await refresh();
    const added=document.querySelector(`[data-edit="${saved.questionId}"]`)?.closest('.question-block');
    if(added){added.scrollIntoView({behavior:'smooth',block:'center'});added.classList.add('just-added');}
    toast(before?'题目已插入，后续题序已顺移':'题目已保存');
  });
}

function rulesDialog(survey,question,refresh){
  const rules=structuredClone(question.jumpRules);
  const element=modal('跳转规则',`<form><p class="muted">${esc(question.title)}</p><p class="note">按从上到下的顺序匹配第一条规则。无匹配则进入下一题；多选须与指定集合完全相同。</p><div id="rule-list"></div><button type="button" class="secondary" id="add-rule">＋ 添加规则</button><p class="error-banner" data-error hidden></p><div class="dialog-actions"><button class="primary">保存规则</button></div></form>`);
  const form=element.querySelector('form');
  function capture(){
    [...form.querySelectorAll('.rule')].forEach((row,index)=>{
      const op=row.querySelector('[name=operator]').value;
      rules[index]={operator:op,value:op==='selected'?row.querySelector('[name=option]').value:op==='exactly'?[...row.querySelectorAll('[name=options]:checked')].map(i=>i.value):Number(row.querySelector('[name=value]').value),targetQuestionId:row.querySelector('[name=target]').value||null};
    });
  }
  function draw(){
    element.querySelector('#rule-list').innerHTML=rules.map((rule,index)=>`<section class="rule"><div class="rule-head"><span>规则 ${index+1}</span><div class="actions"><button type="button" class="link-button" data-up="${index}" ${index===0?'disabled':''}>上移</button><button type="button" class="link-button" data-remove="${index}">删除</button></div></div>${question.type==='single'?`<input name="operator" type="hidden" value="selected"><label class="field">选择了<select name="option">${question.options.map(o=>`<option value="${o.optionId}" ${rule.value===o.optionId?'selected':''}>${esc(o.text)}</option>`).join('')}</select></label>`:question.type==='multiple'?`<input name="operator" type="hidden" value="exactly"><label class="field">仅选择以下选项</label><div class="rules-options">${question.options.map(o=>`<label><input type="checkbox" name="options" value="${o.optionId}" ${rule.value?.includes(o.optionId)?'checked':''}>${esc(o.text)}</label>`).join('')}</div>`:`<div class="row"><label class="field">比较符<select name="operator">${['<','<=','=','>=','>'].map(op=>`<option value="${esc(op)}" ${op===rule.operator?'selected':''}>${esc(op)}</option>`).join('')}</select></label><label class="field">比较数值<input type="number" step="any" name="value" required value="${esc(rule.value??0)}"></label></div>`}<label class="field">满足条件后<select name="target"><option value="">结束问卷</option>${survey.questions.filter(q=>q.order>question.order).map(q=>`<option value="${q.questionId}" ${rule.targetQuestionId===q.questionId?'selected':''}>${q.order}. ${esc(q.title)}</option>`).join('')}</select></label></section>`).join('');
    form.querySelectorAll('[data-remove]').forEach(button=>button.onclick=()=>{capture();rules.splice(Number(button.dataset.remove),1);draw();});
    form.querySelectorAll('[data-up]').forEach(button=>button.onclick=()=>{capture();const i=Number(button.dataset.up);[rules[i-1],rules[i]]=[rules[i],rules[i-1]];draw();});
  }
  draw();
  if(question.type==='text'){element.querySelector('#add-rule').hidden=true;element.querySelector('#rule-list').innerHTML='<p class="muted">文本题不设置条件跳转，按题序继续。</p>';}
  element.querySelector('#add-rule').onclick=()=>{capture();rules.push({operator:question.type==='single'?'selected':question.type==='multiple'?'exactly':'<',value:question.type==='single'?question.options[0].optionId:question.type==='multiple'?[]:0,targetQuestionId:null});draw();};
  bindForm(form,async()=>{capture();if(rules.some(rule=>rule.operator==='exactly'&&!rule.value.length))throw new Error('多选条件至少选择一个选项。');await api(`/surveys/${survey.id}/questions/${question.questionId}/jump-rules`,{method:'PUT',body:{rules}});closeModal({saved:true});await refresh();toast('跳转规则已保存');});
}

function referenceSettingsDialog(survey,question,refresh){
  const element=modal('题序与必答设置',`<form><p class="note">此题使用常用题的固定版本。修改内容请切换版本或先转为独立题。</p><label class="field">题序<input name="order" type="number" min="1" max="2147483647" step="1" value="${question.order}" required></label><label class="check-label"><input type="checkbox" name="required" ${question.required?'checked':''}>设为必答</label><p class="error-banner" data-error hidden></p><div class="dialog-actions"><button class="primary">保存设置</button></div></form>`);
  bindForm(element.querySelector('form'),async data=>{
    const payload={title:question.title,type:question.type,validation:question.validation,order:Number(data.get('order')),required:data.has('required')};
    if(question.options)payload.options=question.options;
    await api(`/surveys/${survey.id}/questions/${question.questionId}`,{method:'PUT',body:payload});
    await closeModal({saved:true});await refresh();toast('设置已保存');
  });
}
