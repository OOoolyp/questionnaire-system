// 纯函数：前端预校验与答题路径；服务器仍执行最终校验。
export function validateAnswer(question, answer) {
  const rules = question.validation || {};
  const selected = answer?.selectedOptionIds || [];
  const value = answer?.value;
  const empty = question.type === 'single' || question.type === 'multiple'
    ? selected.length === 0 : value === undefined || value === null || String(value).trim() === '';
  if (empty) return question.required ? '这道题需要回答。' : '';
  if (['single', 'multiple'].includes(question.type)) {
    if (new Set(selected).size !== selected.length || selected.some(id => !question.options.some(o => o.optionId === id))) return '所选选项无效，请重新选择。';
    if (question.type === 'single' && selected.length !== 1) return '请选择一个选项。';
    if (question.type === 'multiple' && (selected.length < (rules.minChoices ?? 0) || selected.length > (rules.maxChoices ?? question.options.length))) {
      return `请选择 ${rules.minChoices ?? 0}～${rules.maxChoices ?? question.options.length} 项。`;
    }
  } else if (question.type === 'text') {
    // Python的len按Unicode码点计数，使用展开而非JS字符串的UTF-16长度。
    const length = [...String(value)].length;
    if (length < (rules.minLength ?? 0) || length > (rules.maxLength ?? Infinity)) return `请填写 ${rules.minLength ?? 0}～${rules.maxLength ?? '不限'} 个字符。`;
  } else {
    const number = Number(value);
    if (!Number.isFinite(number)) return '请输入有效数字。';
    if (rules.integerOnly && !Number.isInteger(number)) return '请输入整数。';
    if (rules.integerOnly && !Number.isSafeInteger(number)) return '该整数超出浏览器可精确表示的范围，请联系创建者。';
    if (number < (rules.minValue ?? -Infinity) || number > (rules.maxValue ?? Infinity)) return `数值应在 ${rules.minValue ?? '不限'}～${rules.maxValue ?? '不限'} 之间。`;
  }
  return '';
}

export function hasAnswer(question, answer) {
  return ['single', 'multiple'].includes(question.type)
    ? Boolean(answer?.selectedOptionIds?.length)
    : answer?.value !== undefined && answer?.value !== null && String(answer.value).trim() !== '';
}

export function nextId(questions, question, answer) {
  if (hasAnswer(question, answer) && !validateAnswer(question, answer)) {
    for (const rule of question.jumpRules || []) {
      const selected = answer.selectedOptionIds || [];
      const value = Number(answer.value);
      const matches = rule.operator === 'selected' ? selected.includes(rule.value)
        : rule.operator === 'exactly' ? selected.length === rule.value.length && rule.value.every(id => selected.includes(id))
        : ({'<': () => value < rule.value, '<=': () => value <= rule.value, '=': () => value === rule.value,
            '>=': () => value >= rule.value, '>': () => value > rule.value}[rule.operator]?.() ?? false);
      if (matches) return rule.targetQuestionId;
    }
  }
  return [...questions].sort((a, b) => a.order - b.order).find(q => q.order > question.order)?.questionId ?? null;
}

export function activePath(questions, answers) {
  const ordered = [...questions].sort((a, b) => a.order - b.order);
  const byId = new Map(ordered.map(q => [q.questionId, q]));
  const path = [], seen = new Set();
  let current = ordered[0]?.questionId ?? null;
  while (current !== null) {
    if (seen.has(current) || !byId.has(current)) throw new Error('问卷跳转结构无效，请联系创建者。');
    seen.add(current);
    const question = byId.get(current);
    path.push(question);
    current = nextId(ordered, question, answers[question.questionId]);
  }
  return path;
}

export function pruneAnswers(questions, answers) {
  // 上游答案变化时，只保留新路径上的答案；避免隐藏答案被重新带回。
  const ids = new Set(activePath(questions, answers).map(q => q.questionId));
  for (const id of Object.keys(answers)) if (!ids.has(id)) delete answers[id];
  return activePath(questions, answers);
}

export function submissionAnswers(path, answers) {
  return path.filter(q => hasAnswer(q, answers[q.questionId])).map(q => ({
    questionId: q.questionId,
    ...(['single', 'multiple'].includes(q.type)
      ? {selectedOptionIds: [...answers[q.questionId].selectedOptionIds]}
      : {value: q.type === 'number' ? Number(answers[q.questionId].value) : answers[q.questionId].value}),
  }));
}
