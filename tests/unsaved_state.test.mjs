import test from 'node:test';
import assert from 'node:assert/strict';
import {createUnsavedRegistry} from '../frontend/unsaved.mjs';

test('场景：内容改回原值；预期不再提示未保存',()=>{
  const registry=createUnsavedRegistry();let value='原值';
  registry.add({isDirty:()=>value!=='原值'});
  assert.equal(registry.pending().length,0);
  value='修改';assert.equal(registry.pending().length,1);
  value='原值';assert.equal(registry.pending().length,0);
});
test('场景：多个编辑区域；预期只放弃指定区域且不会互相覆盖',()=>{
  const registry=createUnsavedRegistry();const discarded=[];
  const first=registry.add({isDirty:()=>true,onDiscard:()=>discarded.push('first')});
  registry.add({isDirty:()=>true,onDiscard:()=>discarded.push('second')});
  registry.discard(first);
  assert.deepEqual(discarded,['first']);assert.equal(registry.pending().length,1);
});
test('场景：保存进行中与保存失败；预期均保留保护，成功后解除',()=>{
  const registry=createUnsavedRegistry();let busy=true,dirty=false;
  const handle=registry.add({isDirty:()=>dirty,isBusy:()=>busy});
  assert.equal(registry.pending().length,1);
  busy=false;dirty=true;assert.equal(registry.pending().length,1);
  handle.dispose();assert.equal(registry.pending().length,0);
});
test('场景：登录过期清理监听；预期不触发放弃输入回调',()=>{
  const registry=createUnsavedRegistry();let discarded=false;
  registry.add({isDirty:()=>true,onDiscard:()=>{discarded=true;}});
  registry.clear();assert.equal(discarded,false);assert.equal(registry.pending().length,0);
});
