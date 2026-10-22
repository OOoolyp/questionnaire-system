# 问卷系统 API 说明

接口基础地址为 http://127.0.0.1:8000。Swagger 位于 /docs；完整机器可读参数、联合模型、示例和响应结构见附件 openapi.json，该文件由当前 app.openapi() 导出。

## 1 通用约定

除健康检查、注册、登录外，业务 API 需要 `Authorization: Bearer <access_token>`。登录为 application/x-www-form-urlencoded 表单，其余有请求体的业务接口采用 application/json。时间使用带时区 ISO 字符串，ID 使用 24 位十六进制 ObjectId 字符串，分享入口使用 shareToken。

创建者接口按问卷归属检查；越权统一 404。列表参数 skip 默认 0、非负，limit 默认 20、范围 1～100；列表及答卷返回数组，填空内容分页返回 total、skip、limit、items。

| 状态码          | 含义                                       |
| --------------- | ------------------------------------------ |
| 200 / 201 / 204 | 成功 / 创建或提交成功 / 删除成功且无正文   |
| 400             | ID 格式不合法或接口不适用于该题型          |
| 401             | 未登录、令牌失效或账号密码错误             |
| 404             | 不存在、无归属权限、草稿不可填写           |
| 409             | 状态不允许、并发冲突、重复提交或引用被破坏 |
| 422             | JSON、字段、题型、限制、答案或路径不合法   |
| 503             | 运行期间数据库不可用                       |

错误通常包含 detail；422 的 detail 可为模型验证列表、业务提示字符串或带 questionId、message 的对象，前端按实际类型显示。

## 2 完整接口清单

以下由当前 OpenAPI 生成，列表不含静态文件和根路径跳转。s 代表 survey_id，q 代表 question_id；实际路径仍使用完整参数名。

| 方法   | 路径                                                       | 功能                                   | 成功状态 | 请求模型                                                              | 响应模型               |
| ------ | ---------------------------------------------------------- | -------------------------------------- | -------- | --------------------------------------------------------------------- | ---------------------- |
| GET    | /health                                                    | 检查数据库连接                         | 200      | `无`                                                                | `对象`               |
| POST   | /auth/register                                             | 注册账号                               | 201      | `UserRegister`                                                      | `UserRead`           |
| POST   | /auth/token                                                | 登录并获取访问令牌                     | 200      | `Body_login_auth_token_post`                                        | `TokenRead`          |
| GET    | /auth/me                                                   | 查看当前登录用户                       | 200      | `无`                                                                | `UserRead`           |
| POST   | /surveys                                                   | 创建问卷草稿                           | 201      | `SurveyCreate`                                                      | `SurveyRead`         |
| GET    | /surveys                                                   | 查看我的问卷列表                       | 200      | `无`                                                                | `数组<SurveyRead>`   |
| PATCH  | /surveys/{survey_id}                                       | 修改草稿基本信息（仅创建者）           | 200      | `SurveyUpdate`                                                      | `SurveyRead`         |
| GET    | /surveys/{survey_id}                                       | 根据ID查询问卷                         | 200      | `无`                                                                | `SurveyRead`         |
| POST   | /surveys/{survey_id}/questions                             | 添加题目                               | 201      | `SingleQuestion / MultipleQuestion / TextQuestion / NumberQuestion` | `QuestionRead`       |
| POST   | /surveys/{survey_id}/questions/{before_question_id}/insert | 在指定题目前插入，后续题序自动顺移     | 201      | `SingleQuestion / MultipleQuestion / TextQuestion / NumberQuestion` | `QuestionRead`       |
| PUT    | /surveys/{survey_id}/questions/{question_id}               | 完整替换一道题（保留题目ID）           | 200      | `SingleQuestion / MultipleQuestion / TextQuestion / NumberQuestion` | `QuestionRead`       |
| DELETE | /surveys/{survey_id}/questions/{question_id}               | 删除一道题                             | 204      | `无`                                                                | `无正文`             |
| PUT    | /surveys/{survey_id}/questions/{question_id}/jump-rules    | 替换跳转规则（空数组清空）             | 200      | `JumpRulesInput`                                                    | `QuestionRead`       |
| POST   | /surveys/{survey_id}/questions/{question_id}/preview       | 校验当前答案并预览下一题（不保存答卷） | 200      | `PreviewAnswer`                                                     | `PreviewRead`        |
| POST   | /surveys/{survey_id}/publish                               | 发布草稿并设置截止时间                 | 200      | `PublishInput`                                                      | `SurveyRead`         |
| POST   | /surveys/{survey_id}/close                                 | 关闭已发布问卷                         | 200      | `无`                                                                | `SurveyRead`         |
| GET    | /survey/{share_token}                                      | 通过分享标识获取可填写问卷             | 200      | `无`                                                                | `FillSurveyRead`     |
| POST   | /survey/{share_token}/next                                 | 检查当前答案并获取下一题（不保存）     | 200      | `FillStep`                                                          | `PreviewRead`        |
| POST   | /survey/{share_token}/responses                            | 提交完整答卷并保存到MongoDB            | 201      | `SubmissionInput`                                                   | `SubmissionReceipt`  |
| GET    | /surveys/{survey_id}/responses                             | 创建者查看答卷                         | 200      | `无`                                                                | `数组<ResponseRead>` |
| GET    | /surveys/{survey_id}/statistics                            | 创建者查看整份问卷统计                 | 200      | `无`                                                                | `SurveyStatistics`   |
| GET    | /surveys/{survey_id}/questions/{question_id}/statistics    | 创建者查看单题统计                     | 200      | `无`                                                                | `QuestionStatistics` |
| GET    | /surveys/{survey_id}/questions/{question_id}/answers       | 分页查看填空内容（不含填写者身份）     | 200      | `无`                                                                | `AnswerPage`         |
