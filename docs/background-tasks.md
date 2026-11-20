# 后台任务设计（bash run_in_background / bash_output）

> 状态：**设计定稿，实施暂缓**（待沙盒环境方向讨论后一并排期）。
> 本文是后台任务的唯一设计文档。对齐主流：Claude Code 的
> `run_in_background` / `TaskOutput` / `TaskStop` 四件套，按我们的
> REACT 架构与异步 web 会话语义改造。

## 1. 定位与语义

后台任务 = **有限时长的容器内进程**（构建/测试/批处理/安装），
非常驻服务（dev server 等长驻需求属于沙盒环境/容器常驻范畴，不归本设计管）。

三条架构事实决定了全部设计：

1. REACT 循环中**工具执行阶段可阻塞，LLM 流式阶段不可阻塞**——
   "等任务"只能发生在工具调用内；
2. 每次 bash 是一次 `docker exec`（一次性进程）——后台子进程经
   nohup 脱离 exec 会话，**存活期 = 容器存活期**，与 turn/run 无关；
3. 会话是异步 web 聊天——**turn 边界是 REACT 的天然感知点**，
   没有常驻会话进程可推送。

## 2. 工具面

### bash（扩展参数）

`run_in_background: bool = false`：

```bash
mkdir -p tmp/.af_bg && nohup bash -c '<cmd>' > tmp/.af_bg/{id}.log 2>&1 &
echo $! > tmp/.af_bg/{id}.pid
```

- `{id}`：短随机 id（如 `bg-7f3a2c`）
- exec **立即返回** "started background task {id}"——不阻塞当前调用；
  沙箱超时管不到 nohup 子进程（包装命令毫秒级退出）
- 模型可继续其他工具调用并回复用户

### bash_output（新工具）

`bash_output(command_id: str, block: bool = false, timeout: int = 120,
head_limit: int = 200) -> str`：

- **增量读取**：维护字节偏移，返回"自上次读取以来的新输出"（非重复 tail）；
- **探活**：`kill -0 {pid}` → `running / finished(exit N) / timeout`；
- **block 等待模式**：`block=true` 时在工具调用内分段等待（每段受
  沙箱单次 exec timeout 约束，模型循环调用实现"等完再继续"，
  每段超时返回进度——模型可决定放弃或续等）；
- **软超时**：每次调用检查任务年龄，超过 `BG_TASK_MAX_LIFETIME`
  （默认 1800s，对齐 Claude Code 的 30min SIGTERM）→ kill 并标记 `timeout`；
- 停止任务：**不设独立工具**——pid 在返回信息里，模型直接
  `bash("kill {pid}")`（比 Claude Code 少一个 TaskStop，能力不缺）。

## 3. 注册表：落 workspace（关键差异化设计）

```
tmp/.af_bg/
    {id}.log          输出
    {id}.pid          容器内 pid
    registry.json     [{id, cmd 摘要, pid, started_at, status, unread}]
```

- 落 **workspace（宿主挂载目录）→ 跨 turn / 跨 run / 跨 sandbox 实例持久**；
- 结构上规避 Claude Code 的孤儿句柄问题（[#29193]：其句柄在内存，
  上下文压缩后失效）；
- 兼作任务发现机制（Claude Code 无 ListTasks 的补位）：模型/宿主
  读 registry 即得全部任务；
- 清理：finished 且已读超 24h 的条目移除；log 文件随工作区 TTL 清理。

## 4. 感知机制（结束怎么被知道）

### 三条时间线

| 任务结束于 | 感知通道 | 版本 |
|---|---|---|
| turn 进行中 | 模型轮询 `bash_output`（增量+探活）；tool 调用边界注入 system reminder | 轮询=v1；边界注入=v2 候选 |
| **turn 之间**（最常见） | **turn 边界注入**：新 run 启动时（`resolve_harness_context`）读 registry，未读任务注入 Environment 段后追加系统提示（已结束带 exit code；仍在跑带时长），模型回复用户前自然看到 | v1 核心 |
| 用户长期不来 | 状态留 registry，下次交互补送（天然覆盖）；结果随工作区 TTL 清理 | 语义内建 |

### 明确不做

- **推送给用户**（agent 主动发消息）：合成 run 成本高 + 骚扰风险，
  产品决策不归本设计；轻量替代：前端会话页读 registry 展示任务
  状态角标（可选，后续）；
- **run 内步进注入**（v2）：每次 tool node 入口检查通知队列、在
  下个 tool result 前注入 reminder——对齐 Claude Code 的
  system-reminder 机制，工程量中等，视轮询体验再决定。

## 5. 生命周期与容器清扫的耦合

- **清扫豁免**：registry 中存在活跃任务（`kill -0` 通过且未超软超时）
  的容器，**闲置清扫跳过**——否则 turn 之间容器被回收会静默杀掉
  后台任务（后台任务唯一真正的生命周期耦合点）；
- **双超时防"永不回收"陷阱**：常驻类任务（dev server）会让豁免永久
  生效 → 软超时（轮询时 kill）+ 硬超时（beat 清扫时任务超龄 → 容器
  失去豁免 → 按正常闲置策略回收，registry 标记）；
- 会话删除 → 容器销毁 → 任务终止（语义内建，文档明示）。

## 6. 已知边界

- "finished" = 包装 shell 退出，不代表 nohup 子进程群结束（Claude Code
  同语义，[#92399]）；
- pid 复用可致 `kill -0` 误判存活——registry 记 started_at 辅助判断，
  v1 接受；
- 极端：容器被外部手工删除 → registry 残留死任务，探活返回 finished
  （`kill -0` 失败），自然收敛。

## 7. 实施清单（启动实施时的改动点）

| 层 | 改动 |
|---|---|
| harness `sandbox/tools.py` | `_BashArgs.run_in_background` + 启动包装；新工具 `bash_output` |
| harness 工具清单 | `bash_output` 进 `BUILTIN_TOOLS`（bash 勾选连带）；backend `_INJECTED_BUILTIN_TOOL_NAMES` 同步 |
| harness 注入 | `resolve_harness_context` 读 registry → 未读任务注入 Environment 段后（或独立 `[后台任务]` 段） |
| 容器清扫 | beat/maintenance：活跃任务豁免 + 超龄硬超时（依赖沙盒环境方向讨论的 stop/resume 结论） |
| 配置 | `BG_TASK_MAX_LIFETIME`（默认 1800） |
| 测试 | 启动立即返回 / 增量读取 / 探活 / block 分段等待 / 软超时 kill / 跨 run 补送注入 / 清扫豁免 |

## 8. 业界参照

- **Claude Code**：`run_in_background` + `TaskOutput`（增量+block）+
  `TaskStop` + 完成通知；已知坑：30min SIGTERM、上下文压缩后句柄孤儿化
  （本设计以 workspace 注册表规避）、无任务发现机制（本设计以 registry 补位）
- **Gemini CLI**：无后台原语（靠模型写 `&`）——反面参照
- **Deep Agents async subagents**（LangChain，2026-11，beta）：编排器 +
  后台子代理模式，五工具（start/check/update/cancel/list_async_task）
  与本设计四件套同构；通知三态——未完成任务列入编排器 system prompt
  （≈ 本设计 turn 边界注入）、**每次模型调用前检查未完成任务中途收结果**
  （≈ 本设计 v2 步进注入，已被该模式验证）、空闲时以新 run 唤醒编排器
  （其编排器为常驻服务托管；本平台 run 为请求驱动，合成 run 的成本与
  骚扰判断维持不变）。`update_async_task`（向运行中任务推指令，
  interrupt/enqueue 策略）适用于子代理层——未来方向：
  `delegate_to_subagent(async=true)` 异步委派，不影响本设计。
