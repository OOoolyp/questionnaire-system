import {api, $, esc, types, statuses, renderShell} from '../shared/common.js?v=4';

// 每次绘制都使用独立序号，切换范围和分页时丢弃迟到的响应。
export async function renderQuestionAnalysis(id, isCurrent = () => true) {
  const endpoint = `/analytics/questions/${encodeURIComponent(id)}`;
  const stats = await api(`${endpoint}/statistics`);
  if (!isCurrent()) return;
  let scope = 'version', skip = 0, usageRequest = 0, statsRequest = 0;
  renderShell('使用追踪与统计', `<section class="heading"><div><div class="eyebrow">QUESTION INSIGHTS</div><h1>${esc(stats.title)}</h1><p>v${stats.version} · ${types[stats.type]} · 使用追踪与跨问卷统计</p></div><a class="secondary" href="#/questions">← 我的常用题</a></section>
    <p class="note">统计固定到此题目版本，只汇总我的问卷。分享题目不会开放其他人的答卷。次数按成功提交的答案计算，同一人重复提交、同一答卷多处引用会分别计数。</p>
    <div id="question-statistics"></div>
    <section class="panel"><div class="stat-head"><h2>引用问卷</h2><label class="field">查看范围<select id="usage-scope"><option value="version">当前版本 v${stats.version}</option><option value="series">整个题目系列</option></select></label></div><p class="muted">题目作者可追踪外部引用，但只能查看自己问卷的详情和答卷。其他使用者仅能查看自己的引用记录。</p><div id="question-usage"></div></section>`);
  function drawStatistics(data) {
    $('#question-statistics').innerHTML = `<section class="metrics"><div><span>我的问卷版本</span><strong>${data.surveyVersionCount}</strong></div><div><span>累计提交</span><strong>${data.submissionCount}</strong></div><div><span>含本题答案的提交</span><strong>${data.answeredSubmissionCount}</strong></div><div><span>本题有效答案</span><strong>${data.answerCount}</strong></div></section>
      <section class="panel"><div class="stat-head"><h2>答案分布</h2><span>${data.surveySeriesCount} 个问卷系列 · ${data.instanceCount} 处引用</span></div>
      ${data.type === 'number' ? `<div class="metrics"><div><span>平均值</span><strong>${number(data.average)}</strong></div><div><span>最小值</span><strong>${number(data.minimum)}</strong></div><div><span>最大值</span><strong>${number(data.maximum)}</strong></div></div><form id="bucket-form" class="actions"><label class="field">区间宽度<input name="size" type="number" step="any" min="0" max="1000000000000" required value="${esc(data.bucketSize)}"></label><button class="secondary">更新分布</button></form><p class="muted">区间包含下界，不包含上界；仅展示有答案的区间。</p>${data.distribution.map(row => bar(row.label, row.count, data.answerCount)).join('')}${data.distributionTruncated ? '<p class="note">区间超过 100 个，当前仅展示从小到大的前 100 个。请增大区间宽度以查看完整分布。</p>' : ''}` :
      data.options.length ? `<p class="muted">比例分母为本题有效答案数${data.type === 'multiple' ? '，多选题比例合计可能超过 100%' : ''}。</p>${data.options.map(row => bar(row.text, row.count, data.answerCount)).join('')}` :
      `<p class="muted">按完全相同的文本汇总，展示频次最高的 20 项。</p>${data.textFrequencies.map(row => bar(row.value, row.count, data.answerCount)).join('')}${data.otherTextAnswerCount ? `<p class="note">其他文本合计 ${data.otherTextAnswerCount} 次回答。</p>` : ''}`}
      ${!data.answerCount ? '<p class="empty">暂无本题答案。草稿和未回答的引用仍可在下方查看。</p>' : ''}<p class="error-banner" id="statistics-error" hidden></p></section>
      <section class="panel"><h2>按问卷查看</h2>${data.surveys.length ? `<div class="table-scroll"><table class="content-table"><thead><tr><th>问卷</th><th>状态</th><th>引用处数</th><th>提交数</th><th>本题答案数</th></tr></thead><tbody>${data.surveys.map(s => `<tr><td><a href="#/results/${s.surveyId}">${esc(s.title)} · v${s.version}</a></td><td>${statuses[s.status]}</td><td>${s.instanceCount}</td><td>${s.submissionCount}</td><td>${s.answerCount}</td></tr>`).join('')}</tbody></table></div>` : '<p class="empty">我的问卷尚未使用此版本。</p>'}</section>`;
    if ($('#bucket-form')) $('#bucket-form').onsubmit = async event => {
      event.preventDefault();
      const size = Number(new FormData(event.target).get('size'));
      const serial = ++statsRequest, errorBox = $('#statistics-error');
      errorBox.hidden = true;
      try {
        if (!Number.isFinite(size) || size <= 0 || size > 1e12) throw new Error('区间宽度须大于 0，且不超过 1 万亿。');
        const data = await api(`${endpoint}/statistics?bucket_size=${encodeURIComponent(size)}`);
        if (isCurrent() && serial === statsRequest) drawStatistics(data);
      } catch (error) { if (isCurrent() && serial === statsRequest) { errorBox.textContent = error.message; errorBox.hidden = false; } }
    };
  }
  async function loadUsage() {
    const serial = ++usageRequest, container = $('#question-usage');
    container.innerHTML = '<p class="loading">正在查询引用…</p>';
    try {
      const page = await api(`${endpoint}/usage?scope=${scope}&skip=${skip}&limit=10`);
      if (!isCurrent() || serial !== usageRequest) return;
      container.innerHTML = `<p class="status-note">${page.totalSurveyVersions} 个问卷版本 · ${page.totalSurveySeries} 个问卷系列 · ${page.totalInstances} 处引用${page.restrictedSurveyVersions ? ` · ${page.restrictedSurveyVersions} 个外部问卷版本仅展示引用信息` : ''}</p>
        ${page.items.length ? page.items.map(s => `<article class="response-item"><h3>${s.canViewResults ? `<a href="#/edit/${s.surveyId}">${esc(s.title)}</a>` : '其他用户的问卷（详情受限）'} · v${s.surveyVersion}</h3><p>${statuses[s.status]} · ${s.instances.map(q => `第 ${q.order} 题 / 来源 v${q.sourceVersion}`).join('，')}</p>${s.canViewResults ? `<a href="#/results/${s.surveyId}">查看答卷与统计 →</a>` : `<small>引用问卷 ID：${esc(s.surveyId)}</small>`}</article>`).join('') : '<p class="empty">当前范围暂无引用。</p>'}
        <div class="pagination"><button class="secondary" id="usage-prev" ${skip === 0 ? 'disabled' : ''}>上一页</button><span>${Math.floor(skip / 10) + 1} / ${Math.max(1, Math.ceil(page.totalSurveyVersions / 10))}</span><button class="secondary" id="usage-next" ${skip + 10 >= page.totalSurveyVersions ? 'disabled' : ''}>下一页</button></div>`;
      $('#usage-prev').onclick = () => { skip = Math.max(0, skip - 10); loadUsage(); };
      $('#usage-next').onclick = () => { skip += 10; loadUsage(); };
    } catch (error) { if (isCurrent() && serial === usageRequest) container.innerHTML = `<p class="error-banner">${esc(error.message)}</p><button class="secondary" id="usage-retry">重试</button>`; if (isCurrent() && serial === usageRequest) $('#usage-retry').onclick = loadUsage; }
  }
  $('#usage-scope').onchange = event => { scope = event.target.value; skip = 0; loadUsage(); };
  drawStatistics(stats);
  await loadUsage();
}

function number(value) { return value === null ? '—' : esc(Number(value.toPrecision(8))); }
function bar(label, count, total) {
  const rate = total ? Math.min(100, count / total * 100) : 0;
  return `<div class="chart-row analytics-chart"><span>${esc(label)}</span><div class="bar-track"><div class="bar" style="width:${rate}%"></div></div><strong>${count} (${rate.toFixed(1)}%)</strong></div>`;
}
