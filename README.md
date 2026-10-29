# 问卷系统

基于MongoDB的在线问卷系统，后端使用Python、FastAPI和PyMongo，前端使用原生HTML、CSS、JavaScript，与API同源运行，无需前端构建。

已实现注册登录、四题型编辑、条件跳转、发布填写、答卷统计，以及常用题复用、题目与问卷版本、分享、题库、使用追踪和跨问卷答案分布。常用题内容按不可变版本保存，问卷选用具体版本并保留快照，新增版本不会自动改变旧问卷。

相关文档在.\docs\submission_phase2下。

## 1. 环境配置

| 组件        | 用途                                                                         |
| ----------- | ---------------------------------------------------------------------------- |
| Python 3.12 | 运行后端、初始化与测试脚本；本项目使用conda base                             |
| MongoDB     | 数据持久化，需要单独安装并启动                                               |
| Python依赖  | requirements.txt为运行依赖，requirements-dev.txt另含测试/展示生成所需的HTTPX |
| 浏览器      | 使用前端页面                                                                 |
| Node.js     | 仅运行前端逻辑测试时需要；启动网站不需要                                     |

以下命令使用Windows PowerShell，路径按当前机器给出。其他机器需替换MongoDB安装路径、项目路径和数据目录。

在项目目录准备Python环境：

```powershell
Set-Location -LiteralPath 'D:\code\数据库\作业1'
conda activate base
python -m pip install -r requirements-dev.txt
```

如果使用其他Python环境，激活自己的环境即可。只运行网站可安装requirements.txt；需要生成展示账号或运行后端测试时，应安装requirements-dev.txt。前端无需执行npm install。

### 数据库与应用配置

| 配置             | 默认值或本机示例                | 说明                                                         |
| ---------------- | ------------------------------- | ------------------------------------------------------------ |
| MongoDB数据目录  | `D:\mongodb\data\questinaire` | mongod的dbpath，实际保存数据库文件                           |
| MONGODB_URI      | `mongodb://localhost:27017`   | 应用连接的MongoDB服务地址                                    |
| MONGODB_DATABASE | `questionnaire`               | 应用默认逻辑库；展示账号使用questionnaire_demo_usage         |
| JWT_SECRET       | 未配置时进程生成临时密钥        | 如需重启后继续验证已签发令牌，设置保密且不少于32字节的固定值 |

数据库名称不是磁盘路径。同一个MongoDB数据目录可以保存多个逻辑库，不要把库名拼到dbpath后面。环境变量在运行Python的终端设置，程序不会自动加载.env文件。

## 2. 如何运行

### 第一步：启动MongoDB（终端一）

若MongoDB已经在运行，保留现有进程即可，不要重复占用27017端口。否则执行：

```powershell
& 'D:\Program Files\mongodb\bin\mongod.exe' --dbpath 'D:\mongodb\data\questinaire' --bind_ip 127.0.0.1 --port 27017
```

若mongod已加入PATH，也可使用：

```powershell
mongod --dbpath 'D:\mongodb\data\questinaire' --bind_ip 127.0.0.1 --port 27017
```

这两条命令选择一条即可。数据目录须存在；首次使用新目录时可先创建：

```powershell
New-Item -ItemType Directory -Force -Path 'D:\mongodb\data\questinaire'
```

沿用原数据目录才能继续读取已有数据。换到空目录不会自动迁移原有账号和答卷。启动后保持终端一运行。

### 第二步：配置连接（终端二）

在项目根目录、已经激活Python环境的终端执行：

```powershell
$env:MONGODB_URI='mongodb://localhost:27017'
$env:MONGODB_DATABASE='questionnaire_demo_usage'
```

这里选择展示库，方便直接使用下文的展示账号。如需空白业务工作空间，可以改为questionnaire并在页面注册账号。新开终端时需要重新设置变量。

### 第三步：首次生成展示数据（已有数据或手动验证则跳过）

首次展示前，按下一节运行两个生成脚本。

### 第四步：启动网站

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8021
```

MongoDB和网站进程都需保持运行。应用启动时自动检查数据库连接、准备索引并执行兼容迁移，无需手工建立集合。若8021已运行本项目，直接访问即可；更换端口时浏览器地址也相应更改。

| 地址                               | 用途                 |
| ---------------------------------- | -------------------- |
| http://127.0.0.1:8021/             | 跳转到正式前端       |
| http://127.0.0.1:8021/ui/          | 注册登录与问卷工作台 |
| http://127.0.0.1:8021/docs         | Swagger接口调试      |
| http://127.0.0.1:8021/openapi.json | 完整接口结构         |
| http://127.0.0.1:8021/health       | 服务与数据库连接检查 |

## 3. 生成展示账号与数据

MongoDB启动且requirements-dev.txt安装完成后，在项目根目录依次执行：

```powershell
python scripts/seed_analytics_demo.py
python scripts/seed_showcase.py
```

生成脚本自身加载应用并调用正式API，不要求提前启动Uvicorn。

| 脚本                           | 作用                                                                                                              |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| scripts/seed_analytics_demo.py | 创建基础题目、题库、问卷及demo_owner、demo_reader、demo_respondent，保存var/analytics-demo.json                   |
| scripts/seed_showcase.py       | 读取基础清单，在同一数据库生成showcase完整成果账号、24个模拟填写者及业务数据，保存var/showcase.json并核对初始数据 |

**生成位置：**默认连接mongodb://localhost:27017，在逻辑数据库**questionnaire_demo_usage**中保存。MONGODB_URI可指定其他MongoDB服务；基础脚本在代码中指定该库名，成果脚本从基础清单读取库名，仅设置另一个MONGODB_DATABASE不会改变它们的生成目标。

### 登录账号

| 用途                   | 用户名                                           | 密码                 |
| ---------------------- | ------------------------------------------------ | -------------------- |
| 完整成果展示，推荐使用 | `showcase`                                     | `Showcase-2026!`   |
| 基础数据作者           | `demo_owner`                                   | `Demo-usage-2026!` |
| 基础共享资源接收者     | `demo_reader`                                  | `Demo-usage-2026!` |
| 基础模拟填写者         | `demo_respondent`                              | `Demo-usage-2026!` |
| 完整成果模拟填写者     | `showcase_student_01`至`showcase_student_24` | `Showcase-2026!`   |

上述账号均为本地模拟演示数据。打开前端后使用showcase登录，初始首页应显示：

- 全部问卷版本：8，属于5个问卷系列。
- 正在收集：4；草稿：3；已关闭：1。
- 累计回答：66。
- 题库：3；常用题系列：7，合计11个题目版本。

### 重复运行与保留数据

生成脚本不清空数据库，依据var中的本地记录复用已完成操作，不重复提交初始的66份答卷。人工填写、编辑或创建新版本会正常改变数量；再次运行成果脚本时，其初始数量断言可能失败，脚本不会为通过断言而删除或回滚这些操作。

var清单不保存访问令牌，不是数据库备份，且被Git忽略。若改用了完全空的数据库，但项目仍保留旧var/analytics-demo.json、var/showcase.json，应先备份并移出旧清单，再初始化空库；不要把旧ID清单当成恢复数据的方法。已有展示库正常时不需要这一步，也不要为了普通重启而删除清单。

启动网站时必须选用questionnaire_demo_usage，否则连接默认questionnaire库会看不到这些展示账号。登录仅保留在当前标签页；令牌过期或临时签名密钥随服务重启更换后，重新登录即可，数据不受影响。

## 4. 运行测试

MongoDB运行时，在项目根目录执行：

```powershell
python -X utf8 -m unittest discover -s tests/backend -v
node --test tests/frontend/*.test.mjs
```

后端测试自行加载应用，使用随机隔离数据库，不要求网站进程提前启动。测试结束默认保留数据；若明确需要结束清理，可在运行前设置：

```powershell
$env:KEEP_TEST_DATA='0'
```

前端逻辑测试需要Node.js。展示脚本末尾的夹具核对与常规unittest分开，详细范围和已记录结果见[第二阶段测试说明](<docs/submission_phase2/05 测试用例与结果.md>)。

## 5. 目录

```text
app/
  main.py                 应用入口、生命周期、路由与前端挂载
  api/                    原有账号、问卷、填写与统计HTTP接口
  auth/                   用户模型、密码哈希和JWT认证
  core/                   MongoDB连接准备、兼容迁移和索引
  surveys/                问卷、嵌入题、跳转、答卷、复用与问卷版本
  library/                常用题版本、分享授权、题库、使用追踪和聚合
frontend/
  index.html              前端入口
  assets/                 样式等静态资源
  src/pages/              工作台相关页面、编辑、填写、版本、题库与统计
  src/shared/             请求、选题、表单、链接解析与未保存保护
scripts/                  基础演示及完整成果账号生成脚本
tests/backend/            后端、真实MongoDB集成测试及展示夹具核对
      frontend/           前端纯逻辑测试
docs/submission_phase2/   第二阶段系统、数据库、API、逻辑、测试及报告
requirements.txt          后端运行依赖
requirements-dev.txt      运行依赖及测试、生成脚本所需依赖
```
