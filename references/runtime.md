# 运行、安装与分享

1.5 增加透明艺术标题、照片横竖走马灯叠层、可调黑幕停留、严格原声审核和无损中间渲染，默认中文字幕。四个统一命令及计划版本不变，但旧计划的正增益原声需要实际听审或改为静音。相关入口见 [片头片尾](opening-ending.md)、[原声审核](original-audio.md)、[协作与宿主适配](agent-workflow.md)、[密集取帧](frame-review-tool.md)、[声音设计](sound-design.md)。Codex 与 DeepSeek Harness 共用本地执行接口；视觉、听音、委派、生图由各会话真实工具决定，不保证每种模型都具备。保留既有离线组件机制，本次 GitHub 公开版仅提供普通版源码与必要资产，不含完整离线运行组件。

目标为 Windows 本机、剪映专业版和 DeepSeek Harness。使用 Python 3.11+、FFmpeg/ffprobe、固定提交的 pyJianYingDraft 0.3.0、Pillow、NumPy、fontTools；本地转录用 faster-whisper small。

机器路径保存在 config.local.json（不要分享）；默认值在 config.example.json。除常见系统路径发现外，不在程序中写入开发者用户名、盘符、原素材位置。

优先 Python 顺序：config.local.json 的 python → 上次配置保留的 Python → 技能 .runtime → 项目祖先 .tools/media-venv → PATH 中合格的 Python。不要将旧 jianying-editor/vendor 注入这个进程，会遮蔽新版草稿库。

双击“安装到助手.cmd”打开四页大字向导：先准备剪映和 DeepSeek Harness → 选择助手并安装 Skill → 检查环境，缺组件时显示“自动配置环境” → 全部通过才显示完成页。首屏自动从常见目录、用户配置、注册表和实际运行程序路径检查两个软件；没有时下载官方安装包，再显示“安装”按钮，打开标准安装界面。用户装好后点击“已安装，重新检测”，实际找到程序才可下一步；只有安装包不算安装完成。账号登录仍由用户完成。

可选 DeepSeek Harness、Codex 或两个都装；本版本按用户要求在最前面检查上述两个软件，无论 Skill 选择装到哪个助手。两份 Skill 的环境分别复核。更新前备份被替换的文件，保留已有 config.local.json。安装窗口用 Windows 自带的 PowerShell 和 WinForms，不依赖 Python 才能打开。

自动配置会寻找并复用 Python 3.11+（64 位、含 tkinter/venv）、符合功能要求的 FFmpeg/ffprobe、依赖和完整语音模型；缺少时优先使用运行组件离线包，否则联网补齐，无需填写路径或挑选 exe。下载/安装在后台运行，窗口显示当前阶段，失败后保留已完成组件供重试。只在复核成功后写入机器配置。两个助手同时安装时可以共享已准备好的运行环境，各自配置和剪映状态仍单独复核。

1.3.1 的运行组件离线版多一个 `offline-runtime` 目录，包含签名 Python 3.13.16 安装器、FFmpeg、Windows 64 位 Python 3.13 依赖 wheel、哈希锁定清单和语音模型。安装到助手时把组件包位置保存到本机配置的 `offline_bundle_path`；配置时校验并安装到 Skill 的 `.runtime`，不把整份离线包重复复制给每个助手。用户必须完整解压，保留解压目录直到配置结束。已有依赖可复用；需要安装依赖时，离线版使用匹配的 Python 3.13。损坏的离线文件报错并停止，不跳过校验。离线版不含剪映或 Harness 安装器，软件准备页缺少应用时仍需联网。

下载来源及校验：
- 剪映：从 [剪映官网](https://www.capcut.cn/) 的 Windows 下载入口动态获取安装器，限定官方包托管域名并验证“深圳市脸萌科技有限公司”的有效数字签名。
- DeepSeek Harness：从 [DeepSeek 官方下载页](https://www.deepseek.com/zh/download/) 获取 Windows x64 安装器，限定 download.deepseek.com 并验证 Hangzhou DeepSeek Artificial Intelligence 的有效数字签名。已有软件不重装、不自动升级；官网变化时明确提示并保留官网入口。
- Python 固定为 [官方 3.13.16 Windows 安装包](https://www.python.org/downloads/release/python-31316/)，执行前验证有效的 Python Software Foundation 数字签名，采用[官方静默安装参数](https://docs.python.org/3.13/using/windows.html#installing-without-ui)，安装在技能 `.runtime/python`。不修改全局 PATH 或文件关联。
- FFmpeg 使用 [FFmpeg 官方下载页](https://ffmpeg.org/download.html#build-windows)列出的 [Gyan Essentials 构建](https://www.gyan.dev/ffmpeg/builds/)，校验发布方的 SHA-256 后解压，并实际检查 libx264、subtitles、zscale、tonemap 和 ffprobe。
- Python 库从 requirements.txt 安装到独立虚拟环境，安装工作目录必须为 Skill 根目录。固定提交的 pyJianYingDraft wheel 已随包放在 assets/vendor，安装前校验，避免再次访问 GitHub；来源、哈希和许可证同目录可查。普通版其余库从 PyPI 下载；离线版使用 `--no-index --require-hashes` 和包内 wheel。
- 语音模型从 Hugging Face 的 Systran/faster-whisper-small 固定提交下载，缓存保留供重试。仅下载 model.bin、config.json、tokenizer.json、vocabulary.txt，全部存在且非空才启用。离线模型已与官方提交核对哈希；来源、提交和全部离线文件的 SHA-256 记录在 offline-runtime/manifest.json，使用时再次校验。

“首次配置.cmd”以及 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<技能目录>/scripts/setup.ps1" -Quiet` 也能执行同一配置。结果写入 `.runtime/setup-result.json`，另保留 `.runtime/setup-last-result.json`；调用方可用 `-ResultPath <文件>` 接收 `{ok, code, ...}`。失败包含 `stage, stage_label, message, log, stdout_log, next_action`；进度写入 `.runtime/setup-progress.json`。向导显示失败步骤及“重试自动配置”“复制诊断信息”，复制当前报错及相关日志尾部。子进程分开保留 stdout/stderr，按退出码判断结果并有超时，stderr 的正常进度不会被当作失败。并发配置有文件锁；`installer-worker.ps1` 返回 `{ready, auto_setup_needed, items, problems, failure?}`。四个剪辑命令的 JSON 接口不变。

软件预检：`application-worker.ps1 -Root <技能目录> -Result <JSON> [-DownloadMissing]` 返回 `{ready, phase:"applications", apps:[{id,name,installed,path,installer,homepage,error}], problems}`。不传 DownloadMissing 只检查。setup 在配置任何 Python/FFmpeg 之前再次执行软件预检；未安装时下载包并返回 APP_INSTALL_REQUIRED，不继续配置。`doctor` 也包含只读软件检测结果。

软件下载不改动已有剪映工程或助手设置，不修改系统安全设置。素材不上传；之后素材分析、语音识别与程序配乐均可本地执行。网络或下载源不可达时显示失败并允许重试，不以完成页掩盖错误。默认字体路径已经失效时，自动配置恢复本机系统字体，其他有效配置保留。

可选配置字段：python、harness_exe、ffmpeg、ffprobe、jianying_install_dir、jianying_user_data、rectangle_mask_dir、font_path、font_dirs、whisper_model_dir、model_cache、music_library、output_root、input_language。font_dirs 支持递归扫描；用户精选字体以内置相对路径 assets/fonts 寻找，不依赖某台电脑的原 fonts 路径。语音输入语言与最终字幕语言不同，字幕翻译由 Harness 完成。

矩形蒙版需本机剪映的实际资源。工具自动从剪映缓存定位；新电脑没有缓存时，在剪映给测试片段选一次“蒙版→矩形”，保存并关闭剪映，再运行 doctor。仅有资源编号不足以保证渲染，不会以错误的叠加画面冒充三分屏。

受限 Harness 执行环境可能无法读取 Windows 图形组件、SAPI 或查询剪映进程。出现 DESKTOP_UNAVAILABLE / PROCESS_STATE_UNAVAILABLE 时，按宿主的本地执行授权流程处理，或者让用户双击本机入口。不要误判为必须重装 Python，也不要把检测失败当作剪映已退出。

DeepSeek Harness 项目级可放 `.dsh/skills/video-edit/SKILL.md`，用户级可放 `%USERPROFILE%/.dsh/skills/video-edit/SKILL.md`；启用 skill registry、filesystem provider、skill loader，并允许在该工作区读取文件和执行本地程序。使用 `/video-edit` 或自然语言调用。具体以已安装版本为准。[官方目录说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md)、[官方技能加载说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/tool-skill/README.md)。

双击“开始选素材.cmd”可以独立完成选材与分析，但故事编排仍需回到 Harness 对话；这是 Skill，不是假装自带模型的独立全自动 App。

## 工程搬迁

导出目录包括时间线直接使用的完整原片副本、独立音频、SRT、高画质预览和原生加密草稿，不再生成经过压缩的规范化剪辑源。画布、帧率和预览配置见 [画质规则](quality.md)。绝对路径是剪映运行时需要的数据；portable-manifest.json 记录它们相对工程包的位置。移动后执行 relocate 重新绑定，在剪映关闭时 register 加到首页。迁移读取当前原生草稿，保留用户在编辑器中的修改。存在同名工程时指定新名称；不覆盖已有项目。

不同电脑剪映版本、DLL 和字体必须重新检测，不能保证所有未来剪映版本都兼容。工程打包用到的用户精选字体及说明，系统字体使用接收电脑已有字体；不分发 Windows 字体文件。

普通版 ZIP 不带完整运行组件；运行组件离线版附带可复核的组件包。两版都不分发开发电脑的虚拟环境、本机配置或原视频。现有电脑的环境检查、全新运行环境安装与全新 Windows 电脑测试分开记录。

剪映可能在保存时把首页名称同步成工程文件夹名。搬迁副本的文件夹应直接使用希望显示的作品名称，再用 --name 同名生成独立工程 ID，避免首页名称跳变。本机实测状态见 [验证记录](validation-status.md)。
