import test from 'node:test';
import assert from 'node:assert/strict';
import {parseShareLink} from '../../frontend/src/shared/library-links.mjs';

test('解析题目与题库分享链接，保留推荐入口标识', () => {
  assert.deepEqual(parseShareLink('https://example.com/ui/#/shared-question/abc_def-123'), {kind:'question', token:'abc_def-123'});
  assert.deepEqual(parseShareLink(' #/shared-bank/abc_def-123 '), {kind:'bank', token:'abc_def-123'});
  assert.deepEqual(parseShareLink('/shared/banks/abc_def-123'), {kind:'bank', token:'abc_def-123'});
});
test('拒绝不支持的协议、普通页面、截断标识和多余路径', () => {
  for (const value of ['javascript:alert(1)', 'file:///private', 'https://example.com/', '#/shared-bank/x', '#/shared-question/abc_def-123/other', '']) {
    assert.throws(() => parseShareLink(value));
  }
});
test('分享解析只返回类型与标识，不使用粘贴网址作为API目标', () => {
  const result = parseShareLink('https://external.invalid/ui/#/shared-bank/known_token_123');
  assert.deepEqual(Object.keys(result).sort(), ['kind','token']);
  assert.equal(result.token, 'known_token_123');
});
