# 权限驱动 UI 对接契约（PERMISSIONS）

> 本文档是前后端权限体系的唯一对接规范。**新增任何模块/页面前先读本文**，
> 按第五节的清单走即可，无需再阅读权限系统实现。

## 1. 核心原则

**判权限（permission），不判角色（role）。**

- **角色只是权限的命名打包**：管理员给用户分配角色 = 一次性授予一组权限。
  角色的存在是为了授权方便，不是执行依据。
- 一切**页面显示与操作**（导航可见性、路由可达性、按钮可点性、API 访问）
  四层只认**权限键**，且使用同一个键。
- 角色只允许出现在三处：角色管理页、用户列表的"角色"展示列、个人资料页。
- **红线**：除角色管理页外，前后端任何代码出现 `role === 'admin'`、
  `require_any_role(...)` 之类的角色名判断即为违规（admin-only 管理面除外，
  见第四节）。

## 2. 权限键规范

命名：`资源名:动作`，全小写，动作取值：

| 动作 | 语义 | 典型用途 |
|---|---|---|
| `read` | 查看/列表/详情 | 路由守卫、导航项、GET 端点 |
| `write` | 创建/修改/删除/发布 | 写按钮、POST/PUT/DELETE 端点 |
| `invoke` | 调用/执行（消耗资源） | 对话/执行按钮、invoke 端点 |
| `manage` | 敏感管理（密钥/系统设置） | admin 级管理面 |

现有全部权限键见 `backend/app/services/role_service.py` 的
`ALL_PERMISSION_KEYS`（31 个）。

## 3. 四层门控架构

```
① 权限真源（后端）
   ALL_PERMISSION_KEYS 定义权限键
   角色 = 权限集合（MongoDB roles 集合，管理员可编辑）
   登录/refresh/GET /auth/me 下发 user.permissions
        ↓
② 前端数据层
   auth store 持有 user.permissions
   usePermissionSync 每 60s/窗口聚焦拉 /auth/me（权限变更近实时生效）
        ↓
③ 导航/路由层（页面能不能进）
   frontend:  <PermissionRoute perm="xxx:read">（routes/index.tsx）
   studio:    NAV_ITEMS { permission: 'xxx:read' } 过滤 + tab 回退
        ↓
④ 操作层（按钮能不能点）
   usePermission('xxx:write') 门控所有写操作按钮（隐藏，不是禁用）
   后端同键 require_permission 兜底（前端隐藏只是体验，后端才是防线）
```

## 4. 后端端点写法

```python
from app.core.security import require_permission

# 读
_: UserResponse = Depends(require_permission("xxx:read"))
# 写
_: UserResponse = Depends(require_permission("xxx:write"))
```

- 禁止 `require_any_role`（只认 4 个系统角色名，自定义角色会被 403）。
  现存合法例外：`admin.py`/`roles.py`/`api_keys.py`/`webhooks.py` 的
  `require_role(admin)` 超管管理面。
  （`channels.py` 已迁移 RBAC：路由级 `channel:read` + 写端点
  `channel:write`。）
- 权限解析链：Redis 缓存 → MongoDB roles 集合 → 硬编码默认
  （`DEFAULT_SYSTEM_ROLE_PERMISSIONS` 反转生成，见 `security.py`）。
- 资源归属（own/all）在端点内校验，与权限键正交：`execution:read:own`
  之外还需要 `doc.user_id == current_user.id` 检查。

### 4.1 系统角色 `ext_user`（外部终端用户，权限为空）

终端用户授权关联专用角色（`DEFAULT_SYSTEM_ROLE_PERMISSIONS`
中 `"ext_user": []`）：

- 这类账号只经 ext API（API Key + introspection）访问，不走 RBAC；
  空权限列表同时确保它们即使拿到 JWT 也进不了任何管理页面。
- 来源：admin 在用户管理页创建，或 client 首绑时经用户知情确认后以
  「应用同账户密码」自动创建（`create_ext_user_with_password`，前端
  勾选确认、绝不无感建号；同名已有账号且密码不一致报
  `PLATFORM_USERNAME_TAKEN` 引导走认领 claim）。

## 5. 新模块对接清单（照做即可）

以新模块 `report` 为例：

**后端（3 步）**
1. 定义权限键并注册到 `backend/app/services/role_service.py`：
   - `ALL_PERMISSION_KEYS` 加 `"report:read"`, `"report:write"`
   - `DEFAULT_SYSTEM_ROLE_PERMISSIONS` 决定默认授予：admin 全量；
     developer 视模块定位加 `report:write`；operator/viewer 至多 `report:read`
   - 若补授予存量系统角色，需在 `bootstrap.py` 加一次性 backfill
     （marker-guarded，参考 `backfill_viewer_agent_invoke_v3`）
2. 端点挂依赖：读 `require_permission("report:read")`，写
   `require_permission("report:write")`
3. 无需改 schemas / 登录响应——权限随角色解析自动下发

**前端（3 步，frontend 与 frontend-studio 同构）**
1. 路由/导航：
   - frontend：`{ path: '/reports', element: wrapPermission('report:read', <ReportsPage />) }`
   - studio：`NAV_ITEMS` 加 `{ id: 'reports', ..., permission: 'report:read' }`
2. 写按钮：`const canWrite = usePermission('report:write')`，
   `{canWrite && <Button>新建报表</Button>}`
3. 无其他——角色编辑器会自动展示新权限键（由 `/roles/permissions`
   端点驱动，前端零改动）

**自检**：用一个仅授予 `report:read` 的自定义角色用户验证——能看到页面、
看不到写按钮、直接调写 API 返回 403。三者齐备即对接完成。

## 6. 权限变更的生效时效

- 后端 API：立即生效（每次请求从 DB 重读角色并重新解析权限）
- 前端页面：≤60s 或窗口聚焦时生效（`usePermissionSync` 拉取 `/auth/me`）
- 角色编辑后角色管理页的 Redis 缓存会被主动失效，无 TTL 延迟

## 7. 相关文件索引

| 层 | frontend（管理端） | frontend-studio |
|---|---|---|
| hook | `src/hooks/use-permission.ts` | `src/hooks/use-permission.ts` |
| 路由守卫 | `src/routes/permission-route.tsx` | `App.tsx` NAV_ITEMS 过滤 |
| 近实时同步 | `src/hooks/use-permission-sync.ts` | `src/hooks/use-permission-sync.ts` |
| 按钮样板 | `src/pages/users-page.tsx` | `src/components/UserManagement.tsx` |

后端：`app/core/security.py`（鉴权依赖）、`app/services/role_service.py`
（权限键真源 + 默认矩阵）、`app/core/bootstrap.py`（系统角色初始化/backfill）、
`app/api/v1/auth.py`（`GET /auth/me`）。
