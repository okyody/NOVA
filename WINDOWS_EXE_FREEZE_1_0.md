# NOVA 1.0 Windows EXE 封板清单

本文档用于冻结 `NOVA 1.0` 的 Windows EXE 交付边界、桌面形态、显性化要求、验收标准与剩余收口项。

目标：

- 把 `NOVA.exe` 从“能启动的桌面包装”收成“可交付的 Windows 一体化成品”
- 确保 EXE 的行为与 runtime / Studio / config / control-plane 保持一致
- 防止 1.0 阶段继续发散成新的桌面框架试验项目

---

## 1. 1.0 Windows EXE 定义

`NOVA 1.0 Windows EXE` 的定义是：

> 一个能够在 Windows 上直接运行、自动打开内嵌工作台、可完成最小配置与控制面初始化、并可用于客户演示与验收的一体化交付物。

它不是：

- 完整原生 WinUI 企业桌面系统
- 面向普通消费者的娱乐软件
- 独立于服务端逻辑之外的第二套产品

它是：

- runtime 的桌面封装
- control-plane 的本地工作台入口
- 交付与验收载体

---

## 2. 交付物冻结

1.0 Windows EXE 正式交付物冻结为：

- `dist/NOVA/NOVA.exe`

源文件冻结为：

- `windows_launcher.py`
- `NOVA.spec`
- `build_windows_exe.bat`

测试冻结为：

- `tests/test_windows_launcher.py`

1.0 阶段不再新增第二套 Windows 打包路线。

---

## 3. 运行方式冻结

### 3.1 启动方式

用户通过双击 `NOVA.exe` 启动产品。

### 3.2 启动行为

EXE 启动后必须完成：

1. 准备运行目录
2. 准备默认配置文件
3. 启动本地 runtime 服务
4. 等待 `/studio/` 可访问
5. 打开内嵌工作台窗口

### 3.3 默认端口

1.0 默认端口冻结为：

- `8765`

### 3.4 默认行为

1.0 默认行为冻结为：

- 自动进入工作台
- 不要求用户手动打开浏览器
- 不要求用户手动执行命令行启动

---

## 4. EXE 与 Runtime 的关系冻结

1.0 EXE 必须复用同一套 runtime，而不是另起一套隐藏逻辑。

必须保证：

- `/health` 与源码版一致
- `/studio/` 与源码版一致
- `/api/config/current` 与源码版一致
- control-plane API 与源码版一致

不允许：

- EXE 里维护第二套配置解析逻辑
- EXE 里维护第二套业务流程
- EXE 与服务端行为长期分叉

---

## 5. 显性化要求冻结

1.0 EXE 不是只把网页塞进壳里，而是必须把隐性能力显性化。

首页工作台必须显性展示：

- `Quick Start`
- `Quick Actions`
- `Current User Context`
- `Environment Readiness`

配置面板必须显性展示：

- 当前配置文件路径
- 核心运行配置
- 保存结果
- 是否需要重启
- 角色卡重载结果

控制面必须显性展示：

- 当前用户
- tenant scope
- roles
- permissions
- control log

1.0 阶段不再把关键能力继续藏在隐蔽页签或依赖用户自己猜操作路径。

---

## 6. 1.0 EXE 功能范围

### 6.1 必须具备

- 启动后自动打开内嵌工作台
- Dashboard
- Events
- Config
- Control
- 登录入口
- 当前用户上下文展示
- 配置读取/保存
- 角色卡重载
- 控制面最小初始化能力

### 6.2 不要求

1.0 不要求：

- 原生多窗口系统
- 复杂桌面菜单体系
- 安装器/卸载器体系
- 自动升级器
- 本地数据库安装向导

这些属于后续产品化增强，不属于 1.0 封板条件。

---

## 7. 配置工作流冻结

EXE 里的配置工作流必须固定为：

1. 打开 `Config`
2. 读取当前配置
3. 编辑核心字段
4. 保存配置
5. 根据结果判断：
   - 即时生效
   - 需要重启
6. 必要时执行角色卡热重载

配置保存必须满足：

- 有明确成功反馈
- 有明确失败反馈
- 明确提示是否需要重启

---

## 8. 控制面工作流冻结

EXE 必须支持最小控制面初始化工作流：

1. 创建 tenant
2. 创建 role
3. 创建 permission
4. 绑定 role-permission
5. 创建 user
6. 绑定 user-role
7. 开启 auth
8. 重启 EXE
9. 登录
10. 创建 config revision
11. publish / rollback

1.0 要求的是“能完成链路”，不是做复杂后台 UX。

---

## 9. 运行可见性冻结

EXE 工作台必须显性可见：

- health 状态
- runtime role
- event bus lag / pending / retry / DLQ
- persisted history
- current user context
- control log

如果这些信息不可见，EXE 不算 1.0 封板通过。

---

## 10. 验收标准

只有下面全部成立，Windows EXE 封板才算通过：

1. `dist/NOVA/NOVA.exe` 可启动
2. 启动后自动进入内嵌工作台
3. `/health` 返回正常
4. `/studio/` 返回正常
5. `/api/config/current` 返回正常
6. Config 页可读取并保存配置
7. 首页能显性展示关键操作与关键状态
8. Control 页可完成最小控制面初始化链
9. EXE 行为与源码 runtime 不分叉

---

## 11. 禁止漂移项

Windows EXE 1.0 封板前禁止继续扩张：

- 新桌面框架替换
- 新多窗口方案
- 新安装器体系
- 新桌面插件系统
- 新原生渲染层重写

所有剩余工作都必须围绕：

- 稳定
- 显性化
- 交付
- 验收

---

## 12. 1.0 剩余收口重点

Windows EXE 在 1.0 剩余最值得继续做的事情只保留：

1. 保持启动稳定
2. 保持首页显性化工作台清晰
3. 保持 Config / Control / Dashboard 三条工作流一致
4. 保持 EXE 与源码 runtime 行为一致
5. 保持客户手册与 EXE 当前行为一致

不再新增新的桌面产品方向。

---

## 13. Go / No-Go 判定

### Go

允许进入下一个封板项（`部署与恢复封板`），当且仅当：

- EXE 已经是稳定交付物
- 显性化工作台已形成
- 最小控制面初始化可通过 EXE 完成
- 配置工作流可解释、可保存、可反馈

### No-Go

以下任一情况成立，都不允许认为 Windows EXE 已封板：

- EXE 启动不稳定
- 还依赖手动打开浏览器
- 首页仍然像调试页而不是工作台
- Config 保存结果不明确
- EXE 和源码版行为明显不一致

---

## 14. 下一步

Windows EXE 封板完成后，严格进入下一个封板项：

- `部署与恢复封板`

后续重点将转向交付环境的部署、迁移、备份、恢复与正式客户验收链。 
