import {api,$,esc,date,types,renderShell,modal,debugPanel} from '../shared/common.js?v=4';

export async function renderResults(id){
  const [survey,stats]=await Promise.all([api(`/surveys/${id}`),api(`/surveys/${id}/statistics`)]);
  let tab='summary',offset=0,loadVersion=0;
  renderShell('答卷与统计',`<section class="heading"><div><div class="eyebrow">RESPONSES & INSIGHTS</div><h1>${esc(survey.title)}</h1><p>按成功提交次数统计，跳过或未回答的题目不计入平均值。</p></div><div class="actions"><button class="secondary" id="refresh-results">刷新数据</button><a class="secondary" href="#/edit/${id}">← 管理问卷</a></div></section><section class="metrics"><div><span>累计提交</span><strong>${stats.submissionCount}</strong></div><div><span>题目数量</span><strong>${stats.questions.length}</strong></div><div><span>重复填写</span><strong style="font-size:18px">${survey.allowRepeat?'允许':'不允许'}</strong></div><div><span>匿名填写</span><strong style="font-size:18px">${survey.allowAnonymous?'允许':'不允许'}</strong></div></section><div class="toolbar"><div class="tabs"><button class="tab active" id="summary-tab">统计汇总</button><button class="tab" id="responses-tab">原始答卷</button></div><small>仅问卷创建者可见</small></div><div id="result-body"></div>${debugPanel()}`);
  $('#refresh-results').onclick=()=>renderResults(id).catch(error=>{const b=$('#result-body');if(b)b.innerHTML=`<p class="error-banner">${esc(error.message)}</p>`;});
  const load=async()=>{
    const version=++loadVersion;
    const container=$('#result-body');container.innerHTML='<div class="loading">正在加载…</div>';
    try{
      if(tab==='summary'){
        container.innerHTML=stats.questions.length?stats.questions.map(q=>`<section class="panel"><div class="stat-head"><h3>${q.order}. ${esc(q.title)}</h3><small>${types[q.type]} · ${q.answerCount} 次回答</small></div>${q.options.length?q.options.map(o=>`<div class="chart-row"><span>${esc(o.text)}</span><div class="bar-track"><div class="bar" style="width:${q.answerCount?Math.min(100,o.count/q.answerCount*100):0}%"></div></div><strong>${o.count}</strong></div>`).join(''):`${q.type==='number'?`<div class="stat-number">${q.average===null?'—':Number(q.average.toPrecision(8))}<small>平均值</small></div>`:'<p class="status-note" style="margin-top:16px">填写内容按提交时间分页查看。</p>'}<button class="secondary" data-content="${q.questionId}">查看${q.type==='number'?'数字':'文本'}内容</button>`}</section>`).join(''):'<div class="panel empty">还没有题目。</div>';
        container.querySelectorAll('[data-content]').forEach(button=>button.onclick=()=>contents(survey,button.dataset.content));
      }else{
        const responses=await api(`/surveys/${id}/responses?skip=${offset}&limit=20`);
        if(version!==loadVersion||!container.isConnected)return;
        container.innerHTML=responses.length?responses.map((response,index)=>`<article class="response-item"><h3>答卷 ${offset+index+1} <small>· ${date(response.submittedAt)}</small></h3><p class="status-note">${response.isAnonymous?'匿名填写':`填写用户：${esc(response.respondentId)}`}</p><dl>${response.answers.map(answer=>{
          const q=survey.questions.find(q=>q.questionId===answer.questionId);
          const value=answer.selectedOptionIds?answer.selectedOptionIds.map(optionId=>q?.options?.find(o=>o.optionId===optionId)?.text||'未知选项').join('、'):answer.value;
          return `<dt>${esc(q?.title||'未知题目')}</dt><dd>${esc(value)}</dd>`;
        }).join('')||'<dt>本次没有填写内容。</dt>'}</dl></article>`).join(''):'<div class="panel empty">当前页没有答卷。</div>';
        container.insertAdjacentHTML('beforeend',`<div class="pagination"><button class="secondary" id="responses-prev" ${offset===0?'disabled':''}>上一页</button><span>第 ${Math.floor(offset/20)+1} 页</span><button class="secondary" id="responses-next" ${responses.length<20?'disabled':''}>下一页</button></div>`);
        $('#responses-prev').onclick=()=>{offset=Math.max(0,offset-20);load();};$('#responses-next').onclick=()=>{offset+=20;load();};
      }
    }catch(error){if(version===loadVersion&&container.isConnected)container.innerHTML=`<p class="error-banner">${esc(error.message)}</p>`;}
  };
  function select(value){tab=value;$('#summary-tab').classList.toggle('active',value==='summary');$('#responses-tab').classList.toggle('active',value==='responses');load();}
  $('#summary-tab').onclick=()=>select('summary');$('#responses-tab').onclick=()=>select('responses');await load();
}

async function contents(survey,questionId){
  const q=survey.questions.find(q=>q.questionId===questionId);
  const element=modal(q.title,'<div id="content-page" class="loading">正在加载…</div>');
  let skip=0;
  async function load(){
    try{
      const page=await api(`/surveys/${survey.id}/questions/${questionId}/answers?skip=${skip}&limit=20`);
      if(!element.open||!element.querySelector('#content-page'))return;
      const body=element.querySelector('#content-page');body.className='';
      body.innerHTML=`<p class="status-note">共 ${page.total} 条有效回答 · 不显示填写者身份</p>${page.items.length?`<table class="content-table"><thead><tr><th>填写内容</th><th>提交时间</th></tr></thead><tbody>${page.items.map(item=>`<tr><td>${esc(item.value)}</td><td>${date(item.submittedAt)}</td></tr>`).join('')}</tbody></table>`:'<div class="empty">暂无填写内容。</div>'}<div class="pagination"><button class="secondary" id="contents-prev" ${skip===0?'disabled':''}>上一页</button><span>${Math.floor(skip/20)+1} / ${Math.max(1,Math.ceil(page.total/20))}</span><button class="secondary" id="contents-next" ${skip+20>=page.total?'disabled':''}>下一页</button></div>`;
      body.querySelector('#contents-prev').onclick=()=>{skip=Math.max(0,skip-20);load();};body.querySelector('#contents-next').onclick=()=>{skip+=20;load();};
    }catch(error){const b=element.querySelector('#content-page');if(b)b.innerHTML=`<p class="error-banner">${esc(error.message)}</p>`;}
  }
  await load();
}
