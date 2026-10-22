# 问卷系统第一阶段

技术栈：conda base、Python、FastAPI、PyMongo、MongoDB；正式前端使用无需构建的HTML/CSS/JavaScript，与API同源。

当前完成：注册登录、草稿编辑、跳转配置、发布关闭、登录填写、提交答卷、创建者查看答卷及问卷/单题统计。

## 启动

powershell启动数据库：

```powershell
mongod --dbpath='D:\mongodb\data\questinaire'
```

在项目目录打开终端，确保 MongoDB 正在运行：

```powershell
conda activate base
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

正式前端：http://127.0.0.1:8000/ （根路径跳转到 `/ui/`）。Swagger仍在 http://127.0.0.1:8000/docs 。

默认数据库连接为 `mongodb://localhost:27017`，数据库名称为 `questionnaire`。
使用 `users`、`surveys`、`responses` 三个集合，详情请见文档。

可在启动前设置以下环境变量；程序不会自动加载 `.env` 文件：

```powershell
$env:MONGODB_URI = "mongodb://localhost:27017"
$env:MONGODB_DATABASE = "questionnaire"
```

## 接口清单

| 方法及路径                                                  | 功能                     | 身份要求 |
| ----------------------------------------------------------- | ------------------------ | -------- |
| GET /health                                                 | 检查数据库连接           | 无       |
| POST /auth/register                                         | 注册                     | 无       |
| POST /auth/token                                            | 表单登录，获取令牌       | 无       |
| GET /auth/me                                                | 当前用户信息             | 登录     |
| POST /surveys                                               | 创建草稿                 | 登录     |
| GET /surveys                                                | 我的问卷列表             | 登录     |
| GET /surveys/{survey_id}                                    | 查询自己问卷的管理信息   | 创建者   |
| PATCH /surveys/{survey_id}                                  | 修改草稿基本信息         | 创建者   |
| POST /surveys/{survey_id}/questions                         | 添加题目                 | 创建者   |
| PUT /surveys/{survey_id}/questions/{question_id}            | 完整替换一道题           | 创建者   |
| DELETE /surveys/{survey_id}/questions/{question_id}         | 删除一道题               | 创建者   |
| PUT /surveys/{survey_id}/questions/{question_id}/jump-rules | 替换或清空跳转规则       | 创建者   |
| POST /surveys/{survey_id}/questions/{question_id}/preview   | 检查当前答案，预览下一题 | 创建者   |

典型错误：401未登录或令牌错误；404问卷不存在或不属于当前用户；409用户名重复；422字段校验失败；400问卷ID格式错误；503运行期间数据库不可用。

## 跳转配置与预览

这一阶段只做创建者的草稿调试，不保存答卷，也不检查从第一题开始的完整答题路径。

1. 创建至少三道题，例如第1题单选、第2题文本、第3题数字，查询问卷取得真实questionId和optionId。
2. 使用 `PUT /surveys/{survey_id}/questions/{question_id}/jump-rules` 给第1题配置规则。Swagger中单选和多选示例的ID是占位符，必须替换成自己问卷中的真实ID。
3. 用第1题的preview接口提交匹配选项，检查下一题是否为配置目标；再用其他选项确认按顺序进入第2题。
4. 将targetQuestionId设置为null，匹配后应返回ended=true。
5. 用 `{"rules": []}` 清空规则，恢复按顺序继续。

规则请求是完整替换，rules数组的顺序代表优先级，第一条命中即执行：

| 题型 | operator        | value                              |
| ---- | --------------- | ---------------------------------- |
| 单选 | selected        | 一个本题选项ID                     |
| 多选 | exactly         | 本题选项ID数组，不能为空且不能重复 |
| 数字 | <、<=、=、>=、> | 一个数字                           |
| 文本 | 不支持跳转条件  | 只能清空规则                       |

多选exactly表示集合完全一致：配置A和B，选A、B（任意顺序）才命中；只选A或选A、B、C都不命中。
targetQuestionId必须指向本问卷order更大的题目，或为null（结束）。未命中时进入order最小的后续题；没有后续题时结束。

preview请求只提供答案，不提供规则或下一题：

```json
{"selectedOptionIds": ["填入真实选项ID"]}
```

单选数组必须只有一项，多选可以有多项；文本/数字题改为 `{"value": "建议内容"}` 或 `{"value": 17}`。
非必答题可使用 `{}` 表示不回答，不触发条件，按顺序继续。
后端先检查必答、选项归属和重复项、选择数量、文本长度、数字范围和整数要求，再计算跳转；非法答案返回422。

响应字段：

| 字段             | 含义                                             |
| ---------------- | ------------------------------------------------ |
| questionId       | 当前题目                                         |
| nextQuestionId   | 下一题ID；null表示结束                           |
| ended            | 是否结束                                         |
| reason           | matched_rule表示命中规则；sequential表示顺序继续 |
| matchedRuleIndex | 命中规则从0开始的下标；没有命中为null            |

保护规则：删除被引用的目标题目、移除被条件引用的选项、变更题型或顺序导致原规则失效，都会返回409，数据库保留原内容。先修改/清空相关规则，再调整题目。删除作为条件来源的题目会一起删除其自身规则，但若仍被其他题引用，依然拒绝。

配置和预览均要求创建者登录且问卷为草稿；跨账号返回404，未登录返回401。当前不强制规则必须命中某个可能答案，也不自动优化重叠规则，创建者可通过预览检查；多选规则集合必须符合该题选择数量限制。

## Swagger 完整验证流程

1. 执行 `GET /health`，确认数据库状态为 `connected`。
2. 执行 `POST /auth/register`，注册两个测试账号，例如 `alice`、`bob`。用户名去除首尾空格后不能为空，最多50字符；区分大小写；密码长度8～128字符。

```json
{
  "username": "alice",
  "password": "test-password-123"
}
```

3. 执行 `POST /auth/token`，在表单中填写账号密码，返回 `access_token`、`token_type`、`expires_in`。用户名或密码错误返回401。
4. 点击页面上方 **Authorize**。此处采用 OAuth2 密码登录表单，直接填写 username、password，再点击 **Authorize**，Swagger 会自动登录并携带令牌，无需手动复制令牌。client_id、client_secret 留空。
5. 执行 `GET /auth/me`，确认当前账号为 alice。响应不包含密码或密码哈希。
6. 执行 `POST /surveys`：

```json
{
  "title": "生活习惯调查",
  "description": "登录后的第一份问卷",
  "allowAnonymous": false,
  "allowRepeat": false
}
```

7. 应返回201，保存返回的 `id`，检查 `creatorId` 与 alice 的用户ID一致。创建者由后端从令牌中确定，客户端不能指定。
8. 执行 `GET /surveys`，应看到自己创建的问卷。支持 `skip` 和 `limit` 分页，默认每页20条、最多100条。
9. 执行 `GET /surveys/{survey_id}`，填写刚才的ID，应返回200及问卷内容。
10. 在 **Authorize → Logout** 后登录 bob。再次查询 alice 的问卷，应返回404；bob 的列表不应出现 alice 的问卷。统一404避免泄露其他人的问卷是否存在。
11. Logout 后访问问卷接口，应返回401；令牌无效或过期同样返回401。

单独调用 `/auth/token` 不会自动修改 Swagger 的登录状态；请以 **Authorize** 设置的账号为准。

## 前端完整验证流程：发布、填写和提交闭环

### 创建者发布

完成题目与跳转配置后，执行 `POST /surveys/{survey_id}/publish`。请求为：

```json
{"deadline": null}
```

null表示不限时间。需要截止时间时，填写带时区的未来时间，例如 `2030-12-31T23:59:00+08:00`；没有时区或已过去的时间返回422。
发布前检查至少一道题、题目结构和限制、顺序及ID唯一、跳转引用有效。发布后拒绝所有题目/规则编辑；此阶段不支持恢复草稿或重新发布。

复制发布响应的shareToken，作为填写访问标识。shareToken不是登录令牌。

### 另一个账号填写

切换到填写者账号，在Swagger的Authorize中登录：

| 接口                                 | 用途                                        |
| ------------------------------------ | ------------------------------------------- |
| GET /survey/{share_token}            | 获取已发布问卷及题目，从order最小的题目开始 |
| POST /survey/{share_token}/next      | 提交当前题目的答案并获取下一题；不保存      |
| POST /survey/{share_token}/responses | 一次提交整份答卷，成功返回201               |

next请求示例（questionId和选项ID必须替换成真实值）：

```json
{
  "questionId": "000000000000000000000001",
  "selectedOptionIds": ["000000000000000000000002"]
}
```

文本或数字题使用questionId加value。next仅方便逐题调试；它不会生成答题会话，提交时必须再次携带整份答案。

完整提交示例：

```json
{
  "isAnonymous": false,
  "answers": [
    {
      "questionId": "000000000000000000000001",
      "selectedOptionIds": ["000000000000000000000002"]
    },
    {
      "questionId": "000000000000000000000003",
      "value": 20
    }
  ]
}
```

后端从第一题重新走完整路径：

- 检查实际经过的必答题、选项、长度、范围与整数限制。
- 被跳过的必答题不用回答；提交任何跳过题或结束后的题目答案会被拒绝。
- 题目不能重复，不能引用其他问卷的题目或选项。答案数组排列不影响检查。
- 非必答题可省略；空答案不保存。成功后完整答卷保存为responses中的一个文档。
- submittedAt和respondentId由后端设置，客户端不能伪造。

### 查看、匿名和重复填写

创建者执行 `GET /surveys/{survey_id}/responses` 查看答卷，支持skip/limit分页。其他账号不能查看；问卷关闭后创建者仍可查看。

匿名答卷内部仍保存respondentId用于重复提交检查，但管理接口和提交回执不会泄露匿名填写者身份。非匿名答卷在创建者接口显示respondentId。需要匿名时必须在创建问卷时设置allowAnonymous=true，并在提交时设置isAnonymous=true。

禁止重复填写时，responses对surveyId和respondentId建立条件唯一索引（repeatRestricted=true），即使同时发起多个请求也只成功一次。允许重复的问卷每次提交新增独立记录。测试包含4请求并发提交，验证只有1条记录成功写入。

### 关闭与截止

创建者执行 `POST /surveys/{survey_id}/close` 关闭已发布问卷，不需要请求体。草稿不可填写（404），关闭或截止后获取、下一题和提交均被拒绝（409）。
提交会在开始校验和写入前各检查一次状态与时间；第二次检查通过是本次提交的接收时点。已接收且正在写入的请求可能与随后发生的关闭操作并行完成，关闭不撤销已经接收的提交。本机独立MongoDB无需配置副本集事务。
