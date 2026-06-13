# Lead Finder 项目交接摘要（2026-06-13）

> 用途：给下次新会话直接加载，快速恢复项目上下文。
> 范围：基于当前仓库 `F:\project\lead-finder`、本地分支/工作树状态，以及已验证的 README / 设计文档 / 关键代码入口整理。

## 1. 当前项目一句话

这是一个面向玻纤外贸获客的本地私有化工具：先用 Comtrade 选市场，再用 Serper 做公开网页搜寻，经过官网抓取、分类、评分、邮箱补全与验证后，把高质量线索导出或同步进本地 CRM（`F:\project\sale`）。

---

## 2. 当前状态总览

### 主分支状态

- 当前分支：`main`
- 当前主分支最新提交：`6b06504` `Fix workbench header responsiveness`
- 主分支已稳定落地：**基础流程 + Stage A（准确率）**
- Stage B / Stage C：**已在独立 worktree/分支实现或推进，但未合并回 main**

### 本地工作树

| 位置 | 分支 | 说明 |
|---|---|---|
| `F:\project\lead-finder` | `main` | 当前主工作区，偏稳定 |
| `F:\project\lead-finder\.worktrees\stage-b-lead-recall` | `stage-b-lead-recall` | Stage B：召回率/多国家/本地化搜索词/召回报告 |
| `F:\project\lead-finder\.worktrees\stage-c-crm-feedback` | `stage-c-crm-feedback` | Stage C：CRM 反馈回流、工作台联动、UX 打磨 |

### 已知本地服务

- Lead Finder 工作台：`http://127.0.0.1:8765`
- 本地 CRM：`http://127.0.0.1:5173`

### 默认配置入口

- 配置文件：`.env`
- 代码入口：[`F:\project\lead-finder\leadfinder\config.py`](F:\project\lead-finder\leadfinder\config.py)
- 默认数据库：`data/leadfinder.sqlite`
- 默认 CRM 地址：`http://127.0.0.1:5173`

---

## 3. 关键决策

### 3.1 产品与流程决策

- **先准确率，后召回率。** 这是整个四阶段路线的核心前提，避免把低质量线索送进 Hunter、Apollo 或 CRM。
- **工作流保持本地私有化。** 用 Python + SQLite + 本地 HTTP 工作台，不上云，不引入重型 SaaS 作为主依赖。
- **Comtrade 负责选市场，Serper 负责公开网页搜公司。** 外贸邦、易之家、Apollo、Snov、Bright Data 只作为可选数据源，不是零成本核心依赖。
- **Hunter / Apollo 只给通过准确率门槛的线索消耗额度。** 不给 supplier、directory、crawl failed、unknown 乱花 credits。
- **CRM 同步必须是 Qualified 且邮箱已验证。** 不把未验证邮箱直接推到 CRM。

### 3.2 安全与合规决策

- **不关闭 SSL 校验。**
- **不抓取登录态 SaaS、付费会员页、条款不允许自动化的页面。**
- **不在浏览器响应、日志、文档、Git 中暴露 API key / secret。**
- **不自动发开发信。** 系统只做到线索发现、审核、同步、反馈。

### 3.3 工程决策

- **沿用单一主流程，而不是另起一条新管线。** Stage B / Stage C 都是在现有 `campaign -> enrich -> review -> sync CRM` 之上扩展。
- **SQLite 保留稳定 CRM 导出字段契约。** 允许内部字段增加，但导出给 CRM 的 CSV schema 不随意改。
- **工作台优先提供“可审核性”。** 不是只给一个分数，而是要给分类原因、评分原因、抓取状态、复核队列。

---

## 4. 四阶段架构思路

来源文档：[`F:\project\lead-finder\docs\superpowers\specs\2026-06-08-lead-finder-four-stage-improvement-design.md`](F:\project\lead-finder\docs\superpowers\specs\2026-06-08-lead-finder-four-stage-improvement-design.md)

### Stage A：Lead Accuracy

目标：让每个 Qualified / Rejected 决策可解释，并阻止低质量线索消耗 Hunter / Apollo / CRM 资源。

### Stage B：Lead Recall

目标：在不破坏 Stage A 门槛的前提下，提高不同国家、不同玻纤品类下的买家召回率。

### Stage C：CRM Feedback Loop

目标：把 CRM 跟进结果拉回 lead-finder，反哺评分、国家优先级、搜索词策略和复核规则。

### Stage D：Product Stability

目标：配额控制、断路器、运行日志、错误状态、重复日常运行的稳定性。

---

## 5. 已完成部分

### 5.1 主分支已完成

#### 基础能力

- Comtrade 市场选择
- Serper 公开网页搜寻
- 官网抓取与补全
- CSV 导入外部来源（外贸邦 / 易之家 / Apollo / Snov）
- CRM CSV 导出
- 本地工作台
- SQLite 持久化
- unittest 基础覆盖

#### Stage A 准确率体系

- 分类标签体系：buyer / supplier / distributor / manufacturer / directory / unknown
- 结构化证据字段
- 评分解释字段
- 复核队列筛选
- 只对通过门槛的线索做 Hunter / Apollo
- 工作台支持高置信、待复核、疑似 supplier 误判、抓取失败等视图

#### CLI / CRM 同步

当前主工作区存在未提交但明确的 WIP：

- `cli.py` 已新增 `sync-crm`
- `README.md` 已补充 `sync-crm` 命令说明
- `tests/test_crm.py` 已补充 CLI 层测试

这部分是**当前 main 工作区的未提交改动**，不是已落到主分支历史里的正式提交。

### 5.2 Stage B 已推进

分支：`stage-b-lead-recall`

分支 tip：

- `c4046a4` `Add Stage B recall reporting workbench`

已知改动范围：

- `README.md`
- `leadfinder/webapp.py`
- `tests/test_webapp.py`

方向上已覆盖：

- 召回率工作台展示
- 本地化搜索/国家维度报告
- 为 Stage B 的召回可视化做了工作台入口

详细实施计划文档：

- [`F:\project\lead-finder\docs\superpowers\plans\2026-06-12-stage-b-lead-recall.md`](F:\project\lead-finder\docs\superpowers\plans\2026-06-12-stage-b-lead-recall.md)

### 5.3 Stage C 已推进

分支：`stage-c-crm-feedback`

分支 tip：

- `dd172e9` `Polish Stage C workbench feedback UX`

已知改动范围：

- `leadfinder/webapp.py`
- `tests/test_webapp.py`

已知已经做过或验证过的方向：

- CRM 反馈回流界面
- 工作台按钮和操作分组优化
- 顶部操作区响应式调整
- 将原始 JSON 回执改成人话摘要的方向
- CRM 联调已做过真实 pull-back 测试

### 5.4 已做过的真实联调结论

根据本轮之前的项目进展记录，已经验证过：

- 本地 CRM 跑在 `http://127.0.0.1:5173`
- Lead Finder 工作台跑在 `http://127.0.0.1:8765`
- 之前做过真实 CRM feedback pull 联调
- 曾成功看到 CRM 反馈标签，如：
  - `valid_customer`
  - `do_not_contact`

---

## 6. 当前未提交 WIP

当前 `main` 工作区不是干净状态：

```text
M README.md
M cli.py
M tests/test_crm.py
?? docs/superpowers/plans/2026-06-12-stage-b-lead-recall.md
```

### WIP 内容摘要

- [`F:\project\lead-finder\cli.py`](F:\project\lead-finder\cli.py)
  - 新增 `sync-crm` 子命令
  - 调用 `leadfinder.crm.sync_verified_qualified`
- [`F:\project\lead-finder\README.md`](F:\project\lead-finder\README.md)
  - 增加 `sync-crm --limit 50` 示例与说明
- [`F:\project\lead-finder\tests\test_crm.py`](F:\project\lead-finder\tests\test_crm.py)
  - 增加 `sync-crm` CLI 输出测试

这意味着：**主分支代码与当前工作区文件状态不完全一致**。下次接手前，先决定是提交这组 WIP，还是切去 Stage C worktree 继续。

---

## 7. 重要文件与修改记录

### 7.1 核心入口文件

- [`F:\project\lead-finder\cli.py`](F:\project\lead-finder\cli.py)
  - CLI 命令总入口
  - 当前已包含：`markets` / `discover` / `campaign` / `provider-report` / `quality-report` / `import-csv` / `enrich` / `export` / `serve` / `stats`
  - 当前工作区 WIP：`sync-crm`

- [`F:\project\lead-finder\leadfinder\webapp.py`](F:\project\lead-finder\leadfinder\webapp.py)
  - 本地工作台 UI 与 API
  - 现有 main 已含 Stage A 复核筛选、分页、批量动作基础
  - Stage B / Stage C 的前端增强主要也集中在这里

- [`F:\project\lead-finder\leadfinder\db.py`](F:\project\lead-finder\leadfinder\db.py)
  - SQLite schema 和数据访问
  - 已包含准确率相关字段：
    - `crawl_status`
    - `classification_status`
    - `classification_evidence`
    - `score_evidence`
    - `review_status`
    - `market_fit_status`
    - `email_verification_status`
    - `crm_sync_status`
  - 还包含：
    - `campaign_runs`
    - `provider_events`

- [`F:\project\lead-finder\leadfinder\crm.py`](F:\project\lead-finder\leadfinder\crm.py)
  - CRM 状态检查
  - Qualified 且 verified 邮箱同步
  - 本地 CRM 仅允许 `localhost / 127.0.0.1 / ::1`

- [`F:\project\lead-finder\leadfinder\config.py`](F:\project\lead-finder\leadfinder\config.py)
  - 统一读取 `.env`
  - 默认：
    - `LEADFINDER_DB_PATH=data/leadfinder.sqlite`
    - `LEADFINDER_CRM_URL=http://127.0.0.1:5173`

### 7.2 设计与计划文档

- [`F:\project\lead-finder\docs\superpowers\specs\2026-06-04-campaign-one-click-lead-discovery-design.md`](F:\project\lead-finder\docs\superpowers\specs\2026-06-04-campaign-one-click-lead-discovery-design.md)
  - 早期一键获客设计

- [`F:\project\lead-finder\docs\superpowers\specs\2026-06-08-lead-finder-four-stage-improvement-design.md`](F:\project\lead-finder\docs\superpowers\specs\2026-06-08-lead-finder-four-stage-improvement-design.md)
  - 四阶段总设计，建议下次会话必读

- [`F:\project\lead-finder\docs\superpowers\plans\2026-06-08-stage-a-lead-accuracy.md`](F:\project\lead-finder\docs\superpowers\plans\2026-06-08-stage-a-lead-accuracy.md)
  - Stage A 实施计划

- [`F:\project\lead-finder\docs\superpowers\plans\2026-06-12-stage-b-lead-recall.md`](F:\project\lead-finder\docs\superpowers\plans\2026-06-12-stage-b-lead-recall.md)
  - Stage B 实施计划
  - 当前显示为未跟踪文件，需要确认是否正式纳入版本库

### 7.3 关键测试文件

- [`F:\project\lead-finder\tests\test_webapp.py`](F:\project\lead-finder\tests\test_webapp.py)
  - 工作台 HTML / API / review filter 核心测试
- [`F:\project\lead-finder\tests\test_crm.py`](F:\project\lead-finder\tests\test_crm.py)
  - CRM 同步和敏感信息清洗测试

### 7.4 主分支最近关键提交

按时间从新到旧：

| 提交 | 摘要 |
|---|---|
| `6b06504` | 修复工作台头部响应式布局 |
| `d912bfc` | 接受部分 crawl 结果作为可用证据 |
| `c2aa5df` | 完成 lead accuracy 集成 |
| `f0b1eb4` | README 澄清 CRM 与 Apollo 作用范围 |
| `281fa19` | 文档化准确率门槛 |
| `3079751` | 强化 review filter 与证据展示 |
| `4c00b5c` | 修复 review filter 分页 |
| `5678ba8` | 加入准确率复核过滤 |
| `83a4260` | Hunter enrichment 受证据门槛控制 |
| `7efcc91` | evidence 字段迁移测试 |
| `712e756` | 持久化 lead evidence 字段 |
| `cb2db82` | 规范 classification evidence |

---

## 8. 整体架构思路

### 8.1 主流程

1. `markets`
   - 用 Comtrade 选择目标市场
2. `discover` / `campaign`
   - 用 Serper 公开搜索公司官网线索
3. `enrich`
   - 抓官网，提取品牌、行业、应用、产品适配信息
4. `score + classify`
   - 结合官网文本做 buyer/supplier 分类与打分
5. `review`
   - 在工作台按 review queue 人工复核
6. `contact enrichment`
   - 对 Qualified 且通过门槛的线索才跑 Apollo / Hunter
7. `verify`
   - 验证邮箱有效性
8. `export / sync CRM`
   - 导出 CSV 或直接同步至本地 CRM
9. `pull CRM feedback`
   - Stage C 方向，把 CRM 跟进结果拉回 lead-finder

### 8.2 模块分工

- `markets.py`
  - Comtrade / fallback 市场选择
- `serper.py`
  - 搜索查询与结果解析
- `enrich.py` / `contact_enrichment.py`
  - 官网抓取、邮箱补全、验证
- `scoring.py` / `classifier.py` / `evidence.py`
  - 分类、证据、打分解释
- `db.py`
  - SQLite schema、campaign run、provider event
- `webapp.py`
  - 本地工作台和 JSON API
- `crm.py`
  - CRM 状态、同步、后续反馈回拉

### 8.3 设计原则

- 公开网页优先
- 证据优先于猜测
- 低成本优先于全自动
- 人工复核保留在闭环中
- CRM 是后链路，不是筛选前置

---

## 9. 待办事项

### 9.1 近期最值得做

1. **决定主线继续在哪个 worktree 推进**
   - 如果继续做 CRM 反馈与工作台交互，优先切到 `stage-c-crm-feedback`
   - 如果继续做多国家召回、本地化搜索词和召回报告，切到 `stage-b-lead-recall`

2. **处理 main 上未提交的 `sync-crm` WIP**
   - 要么补完测试并提交
   - 要么明确 cherry-pick / 合并到 Stage C 线

3. **把 Stage C 真正收敛成可合并状态**
   - 统一所有工作台动作回执为中文人话版
   - 完成批量复核 / 批量验证 / 只导出 Qualified / CRM 回流摘要
   - 继续把按钮布局、工具条层级做细

4. **把 Stage B 的召回能力与 Stage A 门槛彻底接上**
   - 国家本地化搜索词
   - HS code -> 产品族 -> 搜索词模板
   - 区域 -> 国家分批次限额
   - 每国家 / 每关键词召回效率报告

### 9.2 还没彻底完成的 Stage C / D 方向

- CRM 反馈标签的稳定持久化与统计摘要
- “哪些国家/搜索词/分类规则带来 valid_customer” 的规则反馈
- provider 使用次数和本次消耗在工作台清晰展示
- Serper / Apollo / Hunter 的软预算与断路器
- 后台常驻启动与恢复机制
- 对抓取失败的更细状态展示与重试策略

### 9.3 安全待办

- 对话里已经出现过 API key，**建议尽快轮换**
- 工作台所有错误信息继续做 `sanitize_error`
- 后续文档与 commit message 避免出现真实密钥

---

## 10. 下次会话建议启动顺序

### 如果要继续做代码

1. 先看当前状态：

```powershell
git status --short
git branch -vv
git worktree list
```

2. 如果继续 Stage C：

```powershell
cd F:\project\lead-finder\.worktrees\stage-c-crm-feedback
git status --short
```

3. 如果继续 Stage B：

```powershell
cd F:\project\lead-finder\.worktrees\stage-b-lead-recall
git status --short
```

4. 启动工作台：

```powershell
python cli.py serve
```

5. 打开：

- Lead Finder：`http://127.0.0.1:8765`
- CRM：`http://127.0.0.1:5173`

### 如果要继续理解方案

优先阅读：

1. [`F:\project\lead-finder\docs\superpowers\specs\2026-06-08-lead-finder-four-stage-improvement-design.md`](F:\project\lead-finder\docs\superpowers\specs\2026-06-08-lead-finder-four-stage-improvement-design.md)
2. [`F:\project\lead-finder\docs\superpowers\plans\2026-06-08-stage-a-lead-accuracy.md`](F:\project\lead-finder\docs\superpowers\plans\2026-06-08-stage-a-lead-accuracy.md)
3. [`F:\project\lead-finder\docs\superpowers\plans\2026-06-12-stage-b-lead-recall.md`](F:\project\lead-finder\docs\superpowers\plans\2026-06-12-stage-b-lead-recall.md)
4. [`F:\project\lead-finder\README.md`](F:\project\lead-finder\README.md)

---

## 11. 建议给下次新会话的首条提示词

可以直接把下面这段发给新会话：

```text
请先阅读 F:\project\lead-finder\docs\session-handoff-2026-06-13.md，然后检查当前 git 分支、worktree 和未提交改动。这个项目的主线是：Stage A 准确率在 main，Stage B 和 Stage C 在独立 worktree。请基于交接文档先给我一个“当前最合理下一步”的短计划，再开始实施。
```

---

## 12. 一句判断

现在项目不是“从零到一”的阶段了，已经进入“把准确率主线固化、把召回与 CRM 反馈收敛合并”的阶段。最重要的不是再加新功能，而是把 **Stage B / Stage C 的 worktree 成果整理成可合并、可复用、可验证** 的主线演进。
