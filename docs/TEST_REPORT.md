# 测试记录（2026-11-14）

环境：Mac ARM64，Node/npm；Apple Python 3.9。没有 Linux 容器运行时、Linux x86_64 编译环境或连接的 Ally X。未推送 GitHub，未运行 Actions。

## 已执行

- `npm install --ignore-scripts`：成功，生成 package-lock.json。安装依赖来自配置的 npm 镜像；锁文件发布 URL 已规范为 registry.npmjs.org。
- `npm run typecheck`：通过。初次发现第三方声明 react-router 缺失以及 react-icons 全局 JSX 声明问题，采用 skipLibCheck 跳过依赖声明检查；项目 src 严格类型检查保留。
- `npm run build`：通过，输出 dist/index.js。官方 Rollup CLI 在本机完成输出后仍保留文件监听句柄；改为程序化构建，等待写入和 bundle.close 后显式退出，最终命令返回 0。
- `PYTHONPYCACHEPREFIX=/tmp/hearthstone-hud-pycache python3 -m unittest discover -s tests -v`：7 项通过。包含追加/半行/重复轮询、截断、inode 替换、更长的原地重写、Unicode 原子 IPC、Power 重复事件/动画日志过滤/新对局重置、后台参数校验、禁止缺失二进制启动、停止幂等。
- Python 编译检查通过。首次 parser 导入因 Python 3.9 不支持即时 union 注解失败，添加 postponed annotations 后通过。
- `python3 scripts/package.py`：按预期失败，原因是缺少 bin/hearthstone-hud-renderer。没有输出假安装 ZIP。
- 中文 OTF（约 16 MB）、原始 OFL 和本地测试 PNG 已存在。

测试使用手工合成的最小无身份信息事件，尚无真实设备脱敏日志回放。Decky 测试模块替身只验证生命周期和设置，不代表真实 Decky 加载或原生渲染。

## 未执行，必须补齐

1. Linux Actions 构建、链接、ELF 架构、ldd、readelf、GLIBC 检查（工作流已提供，当前无结果）。C++ 源码尚未经过编译。
2. Decky 从完整 ZIP 安装和插件发现。
3. Ally X 游戏模式下中英文、图片、隐藏/显示、退出/重新启动。
4. 实际 Gamescope 合成可见性，以及鼠标、手柄、触控穿透；XShape 请求不能替代实际触控验证。
5. Steam 性能监控/QAM 共存、异常杀死、Decky 重启、游戏反复启动退出、桌面/游戏模式切换和 SteamOS 重启矩阵。
6. 完整记牌、牌组数据、卡图、奥秘、竞技场评分查询与候选牌选择。

## 实机记录模板

记录设备、SteamOS/Gamescope/Decky 版本、DISPLAY、游戏模式、性能监控级别、diagnostic.json、renderer.log。逐项填写：启动、中文、图片、隐藏、显示、停止、再启动、触控、手柄、QAM、异常退出。未见 HUD 时保留诊断，不自动启用 Loadout 机制。桌面模式结果不得记为游戏模式通过。

## GitHub 提交前复核（2026-11-14）

- 新增 tests/test_packaging.py：覆盖缺失、错误格式、截断 ELF 三种失败，并验证陈旧安装 ZIP 会移除、无最终 ZIP/临时 ZIP 残留。全部 Python 测试共 8 项通过（含三个 subTest）。
- 再次运行 npm run typecheck、npm run build，均返回 0；Python 全部源码编译检查及两个 Bash 脚本 bash -n 通过。
- 补齐 .gitignore：依赖、缓存、ELF/目标文件、日志、diagnostic/state/settings、环境与密钥文件、私有测试目录和临时压缩包均排除。git check-ignore 验证了各类代表路径；原有合成测试与文档保留。
- Actions 静态复核：Ubuntu 22.04 x86_64 runner；显式 linux/amd64 Ubuntu 20.04 容器编译；前端类型与构建、Python 测试、C++ 编译、ELF64 x86_64 可执行文件断言、ldd 缺失依赖检查、readelf 与最高 GLIBC <= 2.31、原生许可证收集、Decky ZIP 打包依次执行。没有 continue-on-error 或 always 上传，失败会阻止打包/上传。容器显式安装 file。
- 打包器在校验前清理同版本旧安装包，完成临时 ZIP 后才原子重命名为最终安装 ZIP。
- 本轮未更改业务源码、原有测试或原生渲染逻辑；变更只涉及构建、发布检查、忽略规则、新增发布测试与文档。
- 远程 origin 配置为用户提供的仓库，仅完成本地提交准备；未推送、未创建 GitHub 仓库、未触发 Actions。
- Linux 编译、Actions 实际执行及 Ally X 游戏模式验收仍待进行；静态复核不代表 CI 已成功。
