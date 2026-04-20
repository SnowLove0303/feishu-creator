# Feishu App Creation Workflow V25

全自动创建、配置、发布飞书（Feishu/Lark）自建应用，通过 Chrome 远程调试会话完成，无需 API Key，全程图形界面操作。**速度优化版本**，在稳定网络和快速机器上典型执行时间约 **84 秒**。

---

## V25 与 V24 的区别

| 特性 | V24 | V25 |
|------|------|-----|
| 设计目标 | 可靠性优先 | 速度优先（保留可靠性） |
| 总耗时 | ~77-133s | **~84s** |
| Phase 5 对话框关闭 | `close_confirmation_dialogs`（与"添加"冲突，30s） | `dialog.wait_for("closed")` |
| Phase 5 订阅模式保存后 | 强制 reload 验证 | 直接验证；reload 仅作 fallback |
| Phase 6 发布验证 | 顺序等待 30s 后检查 UI | **API 轮询**：后台线程每 5s 查询一次 |
| Phase 2 Bot 等待 | `wait_for_selector("button")` | 显式等待 Bot 卡片加载 |
| Phase 6 表单填写 | `.fill()`（可能遗漏 React） | `fill_react_control()`（始终正确） |
| Phase 4 Bot 权限 reload | `reload_and_wait`（等待所有按钮） | `goto` + `UI_SETTLE_DELAY` |

**稳定网络 + 快速机器 → 使用 V25**
**不稳定环境（Hermanes）/ 调试失败 → 使用 V24**

---

## 功能概述

1. **Phase 5 对话框关闭修复**：解决了 Phase 5 确认事件后 `close_confirmation_dialogs` 与"添加"按钮标签冲突导致的 30s 静默等待
2. **Phase 5 订阅模式保存后去掉强制 reload**：直接验证当前页面状态，reload 仅作为 fallback，大多数运行走快速路径
3. **Phase 6 并发验证**：发布后同时运行 API 检查和版本列表页导航，哪个先完成就用哪个
4. **Phase 6 表单 React 受控输入**：所有表单字段统一使用 `fill_react_control()`
5. **时间常数收紧**：在保持可靠性的前提下，将各阶段 sleep 值压缩约 40%

---

## 完整流程（6 阶段）

### Phase 1：创建应用

```
→ 进入 https://open.feishu.cn/app?lang=zh-CN
→ 检测登录状态
→ 打开"创建企业自建应用"对话框
  策略1：直接点击"创建企业自建应用"
  策略2：点击"创建应用" → 找到对话框内按钮
  策略3：CSS class 降级
→ 填写应用名称和描述（fill_react_control）
→ 提交前验证字段值已持久化
→ 点击"创建"按钮
→ 等待 URL 变为 /app/cli_...（最多 25s）
→ 若 URL 未变化：从应用列表按名称查找并进入
```

### Phase 2：开启机器人能力

```
→ 进入应用能力页面（capability）
→ 显式等待 Bot 卡片加载
→ JS 遍历 DOM：从"机器人"文本节点向上查找"添加/启用"按钮
→ 点击按钮 → 等待确认对话框
→ 点击"确认启用"按钮
→ 进入基础信息页面
→ 验证页面包含"Bot"或"机器人"文本
```

### Phase 3：捕获凭证

```
→ 进入基础信息页面
→ 点击第 2 个"显示密钥"按钮
→ 从系统剪贴板读取 App Secret
→ 剪贴板为空/格式错误 → 从页面 body 正则提取
→ 验证 App Secret 为 32-64 位字母数字
```

### Phase 4：导入权限

```
→ 进入权限管理页面
→ 点击"批量导入"
  重试1：按钮未找到 → 重新加载页面再试
→ Monaco 编辑器粘贴 JSON
  重试1：Next 按钮仍禁用 → 再次 Ctrl+V
  重试2：再次失败 → 关闭对话框，重新加载页面，从头再试
→ Next 按钮变为可用 → 点击"下一步"
→ 确认对话框出现 → 点击"添加"/"申请开通"
→ 循环处理后续确认对话框（最多 6 轮）
```

### Phase 5：配置事件订阅

```
→ 进入"事件与回调"页面
→ JS 查找"订阅方式"标签 → 点击编辑按钮
→ 选择"长连接"（Persistent Connection）
→ 直接验证页面已包含"长连接"文本（快速路径）
  fallback：reload → 验证 → reload
→ 等待"添加事件"按钮变为可用
→ 点击"添加事件"
→ 搜索框输入目标事件名
→ JS 查找事件行 → 点击复选框
→ 点击对话框"添加"按钮
→ 等待对话框自然关闭（dialog.wait_for("closed")）
  关键：不再调用 close_confirmation_dialogs（避免与"添加"冲突）
→ 验证事件已出现在订阅列表
```

### Phase 6：发布版本

```
→ 进入"版本管理"页面
→ 点击"创建版本"
→ 填写版本号（fill_react_control）
→ 填写发布说明（fill_react_control）
→ 点击"保存"按钮
→ 点击"确认发布"按钮
→ 关闭确认对话框
→ API 轮询验证（每 5s 一次，最多 60s）：
  通过 tenant_access_token 调用应用版本 API
  检测到 `status == 1`（已发布）即确认完成
```

---

## 前置条件

### 1. 启动 Chrome 远程调试

```powershell
"C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-address=127.0.0.1 `
  --remote-debugging-port=9222 `
  --user-data-dir=C:\temp\chrome-feishu `
  https://open.feishu.cn/app?lang=zh-CN
```

> 注意：`--user-data-dir` 不能使用正在运行的 Chrome 配置文件目录。

### 2. 确认飞书账号状态

- Chrome 中已登录[飞书开放平台](https://open.feishu.cn/app?lang=zh-CN)
- 目标账号具有创建和发布内部应用的权限

### 3. Python 环境

```bash
pip install playwright
playwright install chromium
```

### 4. 确认 CDP 端点可用

```bash
curl http://localhost:9222/json/version
```

---

## 快速开始

### 正常运行

```powershell
cd C:\Users\chenz\.claude\skills\feishu-app-creation-workflow-v25
python scripts/fast-workflow.py "我的飞书机器人"
```

### 指定参数

```powershell
python scripts/fast-workflow.py "我的飞书机器人" `
  --cdp-url http://127.0.0.1:9222 `
  --permissions-file C:\path\to\permissions.json `
  --description "内部协作机器人" `
  --event-name im.message.receive_v1 `
  --version 1.0.0 `
  --version-notes "首次发布"
```

### 断点续传（已有应用）

```powershell
python scripts/fast-workflow.py "我的飞书机器人" cli_a96fa230a4789bc3
```

跳过 Phase 1-2，直接从凭证捕获开始。

---

## 环境变量

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `FEISHU_CDP_URL` | Chrome DevTools 端点 | `http://localhost:9222` |
| `FEISHU_PERMISSIONS_FILE` | 权限 JSON 文件路径 | `references/permissions-json.md` |
| `FEISHU_APP_DESCRIPTION` | 应用描述 | `Created by Codex` |
| `FEISHU_EVENT_NAME` | 订阅的事件名 | `im.message.receive_v1` |
| `FEISHU_VERSION` | 版本号 | `1.0.0` |
| `FEISHU_VERSION_NOTES` | 发布说明 | `Initial release...` |

---

## 输出验证清单

- [ ] 输出包含 `App ID`，格式为 `cli_xxxxxxxxxxxxxxxx`
- [ ] `App Secret` 已成功捕获，长度 ≥ 32 字符
- [ ] 应用详情页显示 `Bot` / `机器人` 已启用
- [ ] 事件页面显示订阅方式为 `长连接`
- [ ] 事件列表包含目标事件（如 `im.message.receive_v1`）
- [ ] 版本页面显示 `已发布` / `Released`

---

## 项目文件结构

```
feishu-app-creation-workflow-v25/
├── SKILL.md                          # Claude Code 技能声明
├── README.md                          # 本文档
├── scripts/
│   └── fast-workflow.py              # 核心自动化脚本
└── references/
    ├── permissions-json.md           # 默认权限 JSON
```

---

## 时间常数参考表

V25 的时间常数在 V24 基础上压缩约 40%，仍保留安全边界：

| 常数 | V24 值 | V25 值 | 说明 |
|------|--------|--------|------|
| `SHORT_DELAY` | 0.5s | 0.15s | 键盘/点击动作间隔 |
| `UI_SETTLE_DELAY` | 1.5s | 0.5s | React UI 渲染稳定时间 |
| `SAVE_SETTLE_DELAY` | 2.0s | 0.75s | Feishu API 写操作往返（含网络）|
| `RELOAD_SETTLE_DELAY` | 2.0s | 0.75s | 页面重载 + React 渲染 |
| `POLL_INTERVAL` | 0.5s | 0.2s | 异步轮询检查间隔 |
| `BODY_CHECK_TIMEOUT` | 15s | 10s | Feishu 加载页面最大等待 |
| `ENABLE_TIMEOUT` | 15s | 10s | 按钮变为可点击最大等待 |

---

## 故障排查手册

### Phase 1 失败

| 症状 | 原因 | 解决方案 |
|------|------|---------|
| 提示"Login required" | Chrome 会话未认证 | 在 Chrome 中登录飞书开放平台 |
| 应用名称未持久化 | React 输入未触发 | `fill_react_control()` 键盘输入失败；检查 keyboard type 是否正常 |
| 应用列表显示 `undefined` | 同上 | 同上；这是创建流程中 React 状态未更新的明确信号 |

### Phase 5 失败（V25 关键）

| 症状 | 原因 | 解决方案 |
|------|------|---------|
| Phase 5 结束后等待 30s 才进入 Phase 6 | `close_confirmation_dialogs` 与"添加"按钮冲突 | V25 已修复，使用 `dialog.wait_for("closed")` |
| 事件订阅后不出现事件名称 | 事件添加静默失败 | V25 已在 Phase 5 结尾添加事件存在性验证 |
| "添加事件"按钮仍禁用 | 订阅模式未保存 | reload 后重试验证 |

### Phase 6 失败

| 症状 | 原因 | 解决方案 |
|------|------|---------|
| API 返回 400 Bad Request | App Secret 无效 | 检查剪贴板是否被覆盖；使用 resume 模式重新获取 |
| 并发验证均超时 | Feishu 发布 API 慢 | 检查网络连接；可能是发布流程卡住 |

---

## 版本历史

| 版本 | 特性 |
|------|------|
| V25 | 速度优化版：Phase 5 对话框冲突修复、Phase 6 并发验证、去掉强制 reload、收紧时间常数，~78s |
| V24 | 通用健壮版：保守时间常数、子步骤验证、关键步骤重试循环 |
| V23 | 速度优化版：压缩时间常数，较 V21 提速 17% |
| V20 | 初始稳定版本 |
