// 常用题表单只生成内容字段，不允许前端指定版本号、归属或分享标识。
export function libraryPayload(data, options = []) {
  const type = data.get('type');
  const title = String(data.get('title') || '').trim();
  if (!title) throw new Error('请填写题干。');
  const keys = {single: [], multiple: ['minChoices', 'maxChoices'], text: ['minLength', 'maxLength'], number: ['minValue', 'maxValue']}[type];
  if (!keys) throw new Error('请选择有效题型。');
  const validation = {};
  for (const key of keys) {
    const raw = data.get(key);
    if (raw === null || raw === '') continue;
    const value = Number(raw);
    if (!Number.isFinite(value)) throw new Error('校验范围必须为有效数字。');
    if (type !== 'number' && (!Number.isInteger(value) || value < 0 || value > 2147483647)) throw new Error('数量或长度必须为有效的非负整数。');
    if (Number.isInteger(value) && !Number.isSafeInteger(value)) throw new Error('数值超出浏览器可精确表示的整数范围。');
    validation[key] = value;
  }
  if (keys.length === 2 && validation[keys[0]] !== undefined && validation[keys[1]] !== undefined && validation[keys[0]] > validation[keys[1]]) throw new Error('下限不能大于上限。');
  if (type === 'number') validation.integerOnly = data.has('integerOnly');
  const payload = {title, type, validation};
  if (type === 'single' || type === 'multiple') {
    if (options.length < 2) throw new Error('选择题至少需要两个选项。');
    payload.options = options.map((option, index) => {
      const text = option.text.trim();
      if (!text) throw new Error('选项文字不能为空。');
      return {text, order: index + 1, ...(option.optionId ? {optionId: option.optionId} : {})};
    });
    if (keys.some(key => validation[key] > options.length)) throw new Error('选择数量限制不能超过选项数量。');
  }
  return payload;
}
