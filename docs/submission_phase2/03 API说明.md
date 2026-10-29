# 问卷系统第二阶段 API 说明

## 1 范围与通用约定

第二阶段在第一阶段登录、问卷编辑、填写与答卷统计接口上，新增常用题版本、题目复用、问卷版本、分享、题库和使用追踪接口。本文件以当前代码及 `app.openapi()` 为依据，共列出 **29 个新增接口**；第一阶段未改变的接口不重复展开。

本机展示基础地址为 `http://127.0.0.1:8021`，Swagger 为 `/docs`，运行中的完整接口模式为 `/openapi.json`。端口属于启动配置，不是接口的一部分。

- 所有本阶段接口都需要 `Authorization: Bearer <access_token>`，包括 `/shared` 分享访问；分享标识不等于登录令牌。
- 有请求体的新增接口采用 `application/json`。`save-to-library` 不需要请求体；创建问卷新版本需要空对象 `{}`。移除题库收录项的 DELETE 接口需要 JSON 请求体。
- 对外 ID 为 24 位十六进制字符串，MongoDB 内存为 ObjectId。时间为带时区的 ISO 字符串，分享标识为独立随机字符串。
- 列表分页为 `skip=0`、`limit=20`，要求 `skip>=0`、`1<=limit<=100`。常用题、版本和题库列表返回数组；使用追踪返回含总数的对象。
- 常用题和问卷版本历史按版本号升序。常用题系列列表和自己的题库列表按创建时间倒序、ID 倒序。使用记录按问卷创建时间倒序、ID 倒序。
- 创建者管理接口使用“记录 ID＋creatorId”检查归属，不能通过提交 creatorId 获取所有权。严格请求模型拒绝额外字段。

| 状态码 | 本阶段含义 |
| --- | --- |
| 200 / 201 / 204 | 查询或修改成功 / 创建成功 / 删除题库成功且无正文 |
| 400 | 路径 ID 格式错误 |
| 401 | 未登录或令牌无效 |
| 404 | 不存在、无权访问、分享已关闭或来源授权失效 |
| 405 | 对常用题版本执行未提供的 PUT、PATCH、DELETE 等操作 |
| 409 | 非草稿修改、旧状态不匹配、题序冲突、规则引用破坏、版本并发重试耗尽等 |
| 422 | 请求格式或字段不合法、跨系列切换/恢复、题型约束不兼容等 |
| 503 | 运行期间数据库访问失败 |

错误正文通常为 `{"detail":"提示"}`，模型验证错误的 detail 可以是列表。请求体 ID 由模型校验时，格式错误通常返回 422，与路径 ID 的 400 区别。

## 2 新增接口清单

### 2.1 常用题与不可变版本

| 方法 | 路径 | 功能 | 成功状态 | 请求模型 | 响应模型 |
| --- | --- | --- | --- | --- | --- |
| POST | `/library/questions` | 创建常用题第一版 | 201 | LibraryQuestionContent | LibraryQuestionRead |
| GET | `/library/questions` | 查看自己的常用题系列，每系列返回第一版 | 200 | 无 | LibraryQuestionRead 数组 |
| GET | `/library/questions/{question_id}` | 查看自己的一条具体版本 | 200 | 无 | LibraryQuestionRead |
| GET | `/library/questions/{question_id}/versions` | 查询同系列历史版本 | 200 | 无 | LibraryQuestionRead 数组 |
| POST | `/library/questions/{question_id}/versions` | 以指定版本为修改来源，创建新版本 | 201 | LibraryQuestionContent | LibraryQuestionRead |
| POST | `/library/questions/{question_id}/restore` | 复制同系列历史内容为新版本 | 201 | RestoreQuestionInput | LibraryQuestionRead |
| POST | `/library/questions/{question_id}/sharing` | 开关此版本的分享入口 | 200 | SharingInput | LibraryQuestionRead |

### 2.2 问卷中的题目复用

| 方法 | 路径 | 功能 | 成功状态 | 请求模型 | 响应模型 |
| --- | --- | --- | --- | --- | --- |
| POST | `/surveys/{survey_id}/questions/{question_id}/save-to-library` | 另存为新的常用题系列 | 201 | 无 | LibraryQuestionRead |
| POST | `/surveys/{survey_id}/questions/from-library` | 将指定常用题版本加入草稿 | 201 | ReuseQuestionInput | QuestionRead |
| POST | `/surveys/{survey_id}/questions/{question_id}/switch-version` | 切换到同系列指定版本 | 200 | SwitchVersionInput | QuestionRead |
| POST | `/surveys/{survey_id}/questions/{question_id}/detach` | 转为独立题，移除来源关联 | 200 | DetachQuestionInput | QuestionRead |
| GET | `/surveys/{survey_id}/questions/{question_id}/source` | 查看自己问卷已使用的固定来源版本 | 200 | 无 | SharedQuestionRead |

### 2.3 问卷版本

| 方法 | 路径 | 功能 | 成功状态 | 请求模型 | 响应模型 |
| --- | --- | --- | --- | --- | --- |
| POST | `/surveys/{survey_id}/versions` | 从指定版本创建新草稿 | 201 | SurveyVersionCreate，即 `{}` | SurveyRead |
| GET | `/surveys/{survey_id}/versions` | 查询同系列历史摘要 | 200 | 无 | SurveyVersionRead 数组 |

### 2.4 题库管理

| 方法 | 路径 | 功能 | 成功状态 | 请求模型 | 响应模型 |
| --- | --- | --- | --- | --- | --- |
| POST | `/library/banks` | 创建题库 | 201 | BankCreate | BankView |
| GET | `/library/banks` | 查看自己的题库列表 | 200 | 无 | QuestionBankRead 数组 |
| GET | `/library/banks/{bank_id}` | 查看题库和推荐题目预览 | 200 | 无 | BankView |
| PATCH | `/library/banks/{bank_id}` | 修改题库名称或说明 | 200 | BankUpdate | BankView |
| DELETE | `/library/banks/{bank_id}` | 删除题库，不级联删除题目或问卷 | 204 | 无 | 无正文 |
| POST | `/library/banks/{bank_id}/sharing` | 开关题库分享 | 200 | SharingInput | BankView |
| PUT | `/library/banks/{bank_id}/items/{root_id}` | 收录题目或更新推荐版本、分类与顺序 | 200 | BankItemWrite | BankView |
| DELETE | `/library/banks/{bank_id}/items/{root_id}` | 移除指定系列的收录项 | 200 | BankItemRemove | BankView |
| GET | `/library/banks/{bank_id}/questions/{root_id}/versions` | 查看已收录系列的版本 | 200 | 无 | SharedQuestionRead 数组 |

### 2.5 分享读取

| 方法 | 路径 | 功能 | 成功状态 | 请求模型 | 响应模型 |
| --- | --- | --- | --- | --- | --- |
| GET | `/shared/questions/{token}` | 读取分享时推荐的题目版本 | 200 | 无 | QuestionShareRead |
| GET | `/shared/questions/{token}/versions` | 通过该入口查看同系列其他版本 | 200 | 无 | SharedQuestionRead 数组 |
| GET | `/shared/banks/{token}` | 查看共享题库及推荐内容 | 200 | 无 | SharedBankRead |
| GET | `/shared/banks/{token}/questions/{root_id}/versions` | 查看共享题库已收录系列的版本 | 200 | 无 | SharedQuestionRead 数组 |

### 2.6 使用追踪与跨问卷统计

| 方法 | 路径 | 功能 | 成功状态 | 请求模型 | 响应模型 |
| --- | --- | --- | --- | --- | --- |
| GET | `/analytics/questions/{question_id}/usage` | 查询具体版本或整个系列的引用问卷 | 200 | 无 | UsagePage |
| GET | `/analytics/questions/{question_id}/statistics` | 聚合具体版本在自己问卷中的答案 | 200 | 无 | QuestionAggregate |

`usage` 除分页参数外支持 `scope=version`（默认）或 `scope=series`。`statistics` 支持 `bucket_size=10`，必须为大于 0、且不超过 `1e12` 的有限数字；不支持以 scope 参数混合多个题目版本的答案。

## 3 请求参数与调用示例

以下用 `<...>` 表示应替换为前一步实际返回的 ID 或分享标识；不能将占位符原样发送。

### 3.1 创建、修改来源与恢复

创建数字题：

```http
POST /library/questions
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{"title":"每周自主学习时长（小时）","type":"number","validation":{"minValue":0,"maxValue":100}}
```

`LibraryQuestionContent` 包含 title、type、validation，选择题还包含 options。options 的每项包含 text、order 和可选 optionId。四题型限制沿用第一阶段：single 无数量限制字段；multiple 使用 minChoices/maxChoices；text 使用 minLength/maxLength；number 使用 minValue/maxValue/integerOnly。

初次创建不要提供 optionId；派生版本时，保留父版本中的选项可带回其原 optionId，新选项省略 ID。不能借用其他版本中不属于当前父版本的选项 ID。常用题内容不包含问卷专属的 order、required、jumpRules。

创建新版本向 `/library/questions/<父版本ID>/versions` 提交完整题干、题型、选项和校验内容；这不是局部 PATCH。version、rootQuestionId、parentQuestionId、creatorId、shareToken 均由服务端维护，不能自行指定。

恢复请求：

```http
POST /library/questions/<本次修改来源版本ID>/restore
```

```json
{"restoredFromQuestionId":"<历史内容来源版本ID>"}
```

两条版本必须属于同一系列且归本人所有。返回一条新版本：parentQuestionId 指向路径中的修改来源，restoredFromQuestionId 指向内容来源，version 按整个系列当前最大值加一。普通编辑和恢复均不覆盖旧版本。

### 3.2 指定版本加入问卷

```http
POST /surveys/<草稿ID>/questions/from-library
```

```json
{"sourceQuestionId":"<具体题目版本ID>","required":true}
```

服务端生成新的问卷内 questionId，复制该版本内容，并记录 sourceQuestionId。省略 order 时追加到最大题序之后；指定未占用的 order 时按该题序加入。需要插入到某题前时使用：

```json
{"sourceQuestionId":"<具体题目版本ID>","beforeQuestionId":"<目标题目ID>","order":2,"required":false}
```

beforeQuestionId 对应的题目必须存在；order 可省略，提供时必须与目标题目的当前题序相同，否则返回 409。插入时顺移后续题序。

使用他人原题时，还需携带一种有效访问入口，三者最多提供一个：

| 字段 | 含义 |
| --- | --- |
| questionShareToken | 此题目系列某条已开启分享的版本入口 |
| bankShareToken | 已开启分享且收录此系列的题库入口 |
| bankId | 自己收录该系列的私人题库；后端继续核验保存的原授权 |

只知道来源版本 ID 不代表有权使用。自己的题目不要求提供额外授权。上述访问字段同样适用于切换版本和收录题库。

### 3.3 切换与转为独立题

切换版本：

```json
{"expectedSourceQuestionId":"<页面读到的当前来源ID>","sourceQuestionId":"<同系列目标版本ID>","clearJumpRules":false}
```

路径为 `POST /surveys/<草稿ID>/questions/<问卷内题目ID>/switch-version`。expectedSourceQuestionId 用于拒绝过期页面操作；只允许同系列切换。保留 questionId、order 和 required，默认保留本题规则，再验证整个问卷的规则引用。若新版破坏选项或规则，可明确提交 clearJumpRules=true 清空本题出站规则；这不能跳过其他结构校验。

转为独立题的路径后缀为 `/detach`，请求体为：

```json
{"expectedSourceQuestionId":"<当前来源ID>"}
```

仅移除 sourceQuestionId，保留内容、题目 ID 和规则。返回的复用操作模型排除空字段，不再包含 sourceQuestionId。之后可用原有题目 PUT 接口独立修改。

`save-to-library` 只创建一个属于自己的新系列，不修改原问卷，也不自动把原题关联到新系列；即使源题来自他人共享版本，另存结果也是独立副本。草稿、已发布和关闭问卷均可另存，但只有草稿允许加入、切换和转为独立题。

### 3.4 创建问卷新版本

```http
POST /surveys/<指定来源问卷版本ID>/versions
Content-Type: application/json
```

```json
{}
```

返回新的 SurveyRead：新 id、新 shareToken、递增 version，同系列 rootSurveyId，parentSurveyId 指向指定来源；status=draft，deadline=null。复制标题、说明、匿名与重复开关、题目快照及跳转规则，不复制任何答卷。可从草稿、发布或关闭版本创建；已有问卷不会被重新开放。

### 3.5 题库收录与推荐版本

创建：`POST /library/banks`，请求为 `{"name":"校园学习调研题库","description":"共用指标"}`。修改名称或说明用 PATCH，至少提供一个非 null 字段。

首次收录：

```http
PUT /library/banks/<题库ID>/items/<根题目ID>
```

```json
{"recommendedVersionId":"<该系列某版本ID>","category":"基础指标","order":1}
```

更新已有收录项需带回旧推荐版本：

```json
{"recommendedVersionId":"<新推荐版本ID>","expectedRecommendedVersionId":"<旧推荐版本ID>","category":"基础指标","order":1}
```

一个题库内每个系列只能收录一次，order 不能与其他系列重复。首次收录提供 expectedRecommendedVersionId，或已有项未提供正确旧值，均返回 409。更新请求是收录项的完整设置；未提供 category 时使用空字符串。

移除项使用 DELETE 同一路径，请求体为 `{"expectedRecommendedVersionId":"<当前推荐版本ID>"}`，成功返回更新后的 BankView（200）。删除整个题库才返回 204。

### 3.6 分享开关与入口

题目 `/library/questions/<具体版本ID>/sharing` 和题库 `/library/banks/<ID>/sharing` 均提交 `{"enabled":true}` 或 `{"enabled":false}`。

题目分享入口推荐该具体版本，但允许查看同系列的其他版本（包括之后产生的版本），不会自动把推荐改为最新。题库推荐则由每条收录项的 recommendedVersionId 决定。同一系列可以在不同入口推荐不同版本。

共享读取不允许修改原题、修改他人题库或查看他人答卷。含有他人原题的私人题库不能开启分享，已分享题库也不能收录他人原题，均返回 409。

## 4 主要响应结构

| 响应 | 关键字段 |
| --- | --- |
| LibraryQuestionRead | id、rootQuestionId、parentQuestionId、restoredFromQuestionId、version、creatorId、title、type、options、validation、shareToken、sharingEnabled、createdAt |
| QuestionRead | questionId、order、required、题目内容、jumpRules，以及可选 sourceQuestionId |
| SurveyRead 新增字段 | rootSurveyId、parentSurveyId、version；其余字段沿用原接口 |
| SurveyVersionRead | id、rootSurveyId、parentSurveyId、version、title、status、createdAt；不包含完整题目或分享标识 |
| QuestionBankRead | id、creatorId、name、description、items、shareToken、sharingEnabled、createdAt、updatedAt |
| BankItem | rootQuestionId、recommendedVersionId、category、order、addedAt |
| BankView | 在题库收录项中增加 question 推荐内容预览；原授权失效时该字段为 null |
| SharedQuestionRead | 题目内容与版本来源信息，不含 creatorId、shareToken、sharingEnabled |
| QuestionShareRead | recommendedVersionId、question |
| SharedBankRead | id、name、description、items，每项含推荐内容预览；不含题库管理标识与内部授权 |

题库内部的 accessProof 不会出现在任何题库响应中。分享读取不会返回其他版本的分享标识。`source` 接口仅允许本人查看自己问卷已经使用的那条具体来源，即使原分享关闭，也不因此开放同系列其他版本。

### 4.1 引用分页 UsagePage

包含 questionVersionId、rootQuestionId、scope、skip、limit，以及：

- totalSurveyVersions：匹配的问卷版本文档数。
- totalSurveySeries：根问卷去重后的系列数。
- totalInstances：问卷中匹配的题目引用处数。
- restrictedSurveyVersions：当前结果范围中不属于本人的问卷版本数。
- items：当前页记录；每项含 surveyId、rootSurveyId、surveyVersion、status、canViewResults、title、createdAt、instances。

instances 含 questionId、sourceQuestionId、sourceVersion、order。题目作者可追踪全局引用；其他使用者只返回自己问卷的引用。外部记录的 title 和 createdAt 为 null，canViewResults=false，没有答卷或分享链接。

### 4.2 QuestionAggregate

统计始终限定本人问卷和具体题目版本，scope 固定为 owned_surveys_only。主要字段如下：

| 字段 | 口径 |
| --- | --- |
| surveyVersionCount / surveySeriesCount / instanceCount | 本人引用问卷版本数 / 根问卷去重数 / 题目引用处数 |
| submissionCount | 这些问卷的全部成功提交数，含未回答本题的提交 |
| answeredSubmissionCount | 至少回答一处该版本的提交数，每份答卷最多一次 |
| answerCount | 匹配的有效答案总数，一份答卷多处作答可计多次 |
| average / minimum / maximum | 数字均值和极值；无数字答案或非数字题为 null |
| bucketSize / distribution / distributionTruncated | 数字区间宽度、非空区间计数、是否超过展示上限 |
| options | 每项 optionId、text、count，含零次选项 |
| textFrequencies / otherTextAnswerCount | 前 20 项相同文本的频次、其余文本答案合计 |
| surveys | 按本人问卷拆分的 surveyId、title、version、status、instanceCount、submissionCount、answerCount |

数字区间包含下界、不含上界，返回 lower、upper、label、count；边界以字符串输出以保留精度。按下界排序最多返回 100 个非空区间，超限时仍对全部答案计算总数及均值。选择题比例由前端以 count/answerCount 计算，多选合计可超过 100%。

## 5 与第一阶段接口的兼容关系

原有问卷接口仍使用 surveyId 指向一个具体问卷版本。重复限制索引继续按 surveyId＋respondentId 生效，同一个人可以分别填写同系列的不同问卷版本。原有统计接口也只统计指定问卷版本。

原题目 PUT 不可绕过来源保护直接改写引用题的题干、选项、题型或限制；应创建常用题新版本再切换，或先 detach 再独立修改。发布/关闭后的内容仍锁定，原分享标识与已提交答案保持有效关联。

接口实现定位：`app/library/{routes,bank_routes,share_routes,analytics_routes}.py`、`app/surveys/{reuse_routes,version_routes}.py`。关键业务约束见同目录《04 关键逻辑说明》，验证方法见《05 测试用例与结果》。
