import test from 'node:test';
import assert from 'node:assert/strict';
import {validateAnswer,activePath,pruneAnswers,submissionAnswers,nextId} from '../../frontend/src/shared/logic.mjs';

const single={questionId:'q1',type:'single',order:1,required:true,validation:{},options:[{optionId:'a'},{optionId:'b'}],jumpRules:[{operator:'selected',value:'b',targetQuestionId:'q3'}]};
const multi={questionId:'q2',type:'multiple',order:2,required:true,validation:{minChoices:1,maxChoices:2},options:[{optionId:'a'},{optionId:'b'},{optionId:'c'}],jumpRules:[]};
const number={questionId:'q3',type:'number',order:3,required:true,validation:{minValue:0,maxValue:120,integerOnly:true},jumpRules:[]};
const questions=[single,multi,number];

test('场景：上游改答案后隐藏并清空被跳过题；预期只提交新路径',()=>{
  const answers={q1:{selectedOptionIds:['a']},q2:{selectedOptionIds:['a','b']},q3:{value:'0'}};
  assert.deepEqual(activePath(questions,answers).map(q=>q.questionId),['q1','q2','q3']);
  answers.q1={selectedOptionIds:['b']};
  const path=pruneAnswers(questions,answers);
  assert.equal(answers.q2,undefined);
  assert.deepEqual(submissionAnswers(path,answers),[{questionId:'q1',selectedOptionIds:['b']},{questionId:'q3',value:0}]);
});
test('场景：多选完全匹配；预期顺序无关，子集和超集不匹配',()=>{
  const source={...multi,jumpRules:[{operator:'exactly',value:['a','b'],targetQuestionId:null}],validation:{}};
  assert.equal(nextId(questions,source,{selectedOptionIds:['b','a']}),null);
  assert.equal(nextId(questions,source,{selectedOptionIds:['a']}),'q3');
  assert.equal(nextId(questions,source,{selectedOptionIds:['a','b','c']}),'q3');
});
test('场景：数字校验；预期0/120通过、非整数/越界/空值拒绝',()=>{
  for(const value of ['0','120'])assert.equal(validateAnswer(number,{value}),'');
  for(const value of ['','-1','121','0.5','NaN'])assert.notEqual(validateAnswer(number,{value}),'');
});
test('场景：字符数与后端一致；预期Unicode码点计数且可选题省略',()=>{
  const text={type:'text',required:false,validation:{minLength:2,maxLength:2}};
  assert.equal(validateAnswer(text,{value:'😀中'}),'');
  assert.notEqual(validateAnswer(text,{value:'😀'}),'');
  assert.equal(validateAnswer(text,{}),'');
});
test('场景：必答多选与非法选项；预期数量/归属/重复均被校验',()=>{
  for(const selectedOptionIds of [[],['x'],['a','a'],['a','b','c']])assert.notEqual(validateAnswer(multi,{selectedOptionIds}),'');
  assert.equal(validateAnswer(multi,{selectedOptionIds:['a','b']}),'');
});
