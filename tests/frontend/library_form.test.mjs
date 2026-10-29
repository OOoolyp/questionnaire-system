import test from 'node:test';
import assert from 'node:assert/strict';
import {libraryPayload} from '../../frontend/src/shared/library-form.mjs';

const data = values => {
  const form = new FormData();
  for (const [key, value] of Object.entries(values)) form.set(key, value);
  return form;
};

test('新版本保留选项身份，并排除归属与版本元数据', () => {
  const payload = libraryPayload(data({title: ' 水果 ', type: 'multiple', maxChoices: '2', version: '99', creatorId: 'other'}), [{text: ' 苹果 ', optionId: 'original'}, {text: '香蕉'}]);
  assert.deepEqual(payload, {title: '水果', type: 'multiple', validation: {maxChoices: 2}, options: [{text: '苹果', order: 1, optionId: 'original'}, {text: '香蕉', order: 2}]});
});
test('数字零下限不丢失；切换题型不提交残留的选项和规则', () => {
  assert.deepEqual(libraryPayload(data({title: '年龄', type: 'number', minValue: '0', maxValue: '', integerOnly: 'on', maxChoices: '2'}), [{text: '旧选项'}]), {title: '年龄', type: 'number', validation: {minValue: 0, integerOnly: true}});
  assert.deepEqual(libraryPayload(data({title: '建议', type: 'text', maxLength: '50'})), {title: '建议', type: 'text', validation: {maxLength: 50}});
});
test('拒绝无效数量、倒置范围及超出浏览器精度的整数', () => {
  for (const values of [
    {type: 'text', minLength: '-1'}, {type: 'text', minLength: '1.5'},
    {type: 'number', minValue: '10', maxValue: '0'}, {type: 'number', minValue: 'Infinity'},
    {type: 'number', minValue: '9007199254740993'},
  ]) assert.throws(() => libraryPayload(data({title: '测试', ...values})));
  assert.throws(() => libraryPayload(data({title: '选项', type: 'single'}), [{text: '一项'}]));
  assert.throws(() => libraryPayload(data({title: '选项', type: 'multiple', maxChoices: '3'}), [{text: '甲'}, {text: '乙'}]));
});
