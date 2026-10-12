# 运行、安装与分享（1.6）

两条入口（聊天 / 大字向导）与两种交付（MP4 / MP4＋剪映工程）独立选择。只需要 Codex 或具备本地工具的 DeepSeek Harness 中的一个；不要替当前 Codex 用户额外安装 Harness。图像理解、试听、委派、生图按当前会话实际能力判断，不由软件名称或 `doctor.ready` 推定。

## 按需依赖

| 条件 | 必须检查 |
|---|---|
| 所有模式 | Skill 文件与版本、当前助手已读取 SKILL.md、Python 3.11+、FFmpeg/ffprobe、NumPy、Pillow、fontTools、可用字体 |
| `entry_mode=chat` | 当前对话的本地文件/程序工具；不要求 Tk 或打开图形窗口 |
| `entry_mode=wizard` | 额外检查 tkinter 与本机窗口可用性 |
| `delivery_mode=mp4` | 跳过剪映、草稿库、DLL 和剪映蒙版缓存；使用独立 `export-mp4` |
| `delivery_mode=editable` | 额外扫描本地剪映、固定版本草稿库与 videoeditor.dll；使用矩形蒙版时检查实际资源 |
| 明确需要识别讲话 | `transcription_required=true`：faster-whisper 与完整本地模型 |
| 需要配音 | `voiceover_required=true`：实际可用系统声音；核对所需语言/音色 |

默认配置为 `host=auto, delivery_mode=mp4, entry_mode=chat`，但交付偏好缺失仍须补问，不能据此替用户决定。`host=codex/deepseek` 由当前会话确定；环境检查中显式 host 表示已在该宿主内，独立安装向导则真正扫描所选软件。`host=auto` 找到一个即可，不强求两个。

`doctor` 返回 Skill 文件状态与版本；`loaded_by_host` 仍需助手根据实际读取确认。工具检查不验证模型的视觉、听音权限，也不代表剪映已实际打开。

## 大字安装与入口

完整解压后运行“安装到助手.cmd”，共有五页：选一个助手、交付方式和入口 → 扫描本地软件 → 安装 Skill → 检查并配置环境 → 复制请求回到助手。

已有软件直接复用。缺所选助手时引导其官方安装入口；只有工程模式才提示剪映。软件安装与登录交由用户完成；安装包存在不代表软件安装完成，需要重新扫描。界面使用 Windows PowerShell / WinForms，不要求预装 Python。

安装只替换 Skill 文件，更新前备份被替换内容，保留已有 `config.local.json` 和未知有效配置项，同时保存本次选择的 host、delivery_mode、entry_mode。正常界面只要求选一个助手；脚本保留历史 Both 选项用于明确需要同时维护两份 Skill 的用户，它不是前置依赖。

“开始选素材.cmd”仅打开需求向导并把 `request.json` 保存到独立任务目录，不自动取帧或开始剪辑。向导最终确认按钮记录确认；把路径交回助手接续，已确认且没有变化的需求不用再次问同一轮。取消不开始制作。聊天入口可以跳过向导，直接执行 [需求接入](intake.md)。

## 配置与检查命令

在 Skill 根目录使用本机已配置的 Python。下面的 `JOB`、`DELIVERY` 是参数说明，需由助手填成实际路径：

```text
python scripts/video_tool.py doctor --host codex --delivery-mode mp4 --entry-mode chat
python scripts/video_tool.py doctor --host codex --request JOB/request.json
python scripts/video_tool.py request-check --request JOB/request.json
python scripts/video_tool.py confirm-request --request JOB/request.json --user-confirmed
python scripts/video_tool.py analyze --request JOB/request.json --output JOB
python scripts/video_tool.py validate --plan JOB/edit-plan.json
python scripts/video_tool.py export-mp4 --plan JOB/edit-plan.json --output DELIVERY
```

`confirm-request` 只能在用户真实确认完整制作单后调用。工程交付换成 `export-jianying`，不能先导出剪映工程来满足只要 MP4 的用户。`DELIVERY` 等于确认的输出父目录，工具在其中创建新作品子目录；同名已存在则明确拒绝，不覆盖。

`doctor --request` 可读取部分需求并按已明确选择复核，不会确认需求。字幕开启不自动要求 ASR；需要讲话识别时显式设置 transcription_required。配音选择从 request.voiceover 同步到 voiceover_required。配音文案语言和系统音色还需实际核对，不能把“有声音”理解为“任意语言都支持”。

缺依赖时运行自动配置，再复查：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -Quiet -HostName codex -DeliveryMode mp4 -EntryMode chat -ActiveHost
```

`-ActiveHost` 仅适用于确实正在该助手里的调用。省略模式参数时沿用已保存配置。转录/配音按已保存配置或 PowerShell 的 `-TranscriptionRequired $true` / `-VoiceoverRequired $true` 按需开启；不要仅为了生成风景故事字幕下载语音模型。

Python 寻找顺序为配置指定 → 已保留环境 → Skill `.runtime` → 项目祖先已有 media-venv → PATH 中合格 Python。缺组件先尝试可用离线包，否则从既有官方来源准备到独立运行环境，不修改全局 PATH。

依赖按模式安装：`requirements-base.txt` 为基础；`requirements-editable.txt` 追加草稿库；`requirements-transcription.txt` 仅语音识别需要。`requirements.txt` 保留完整环境手动安装方式，不是 MP4 首次配置的强制依赖。草稿库 wheel 的来源、固定提交、SHA-256 和 Apache 许可在 `assets/vendor`，不得注入旧版 jianying-editor/vendor 遮蔽它。

软件预检接口：

```text
application-worker.ps1 -Root SKILL -Result RESULT -HostName codex -DeliveryMode mp4 [-ActiveHost]
```

默认只读；需要下载时显式使用 `-DownloadMissing`，仍只处理当前所选软件。来源包括剪映官网、DeepSeek 官方下载页；Codex 缺失时引导官方页面。Python 安装器验证 PSF 签名，FFmpeg 校验发布方哈希并探测滤镜；语音模型使用固定提交。网络不可达或签名不符明确报错，不能显示配置成功。

配置进度与结果保存在 `.runtime`，包括 setup-progress.json、setup-result.json、setup-last-result.json；失败报告保留阶段、日志及下一步建议。子进程 stdout/stderr 分开，正常进度不当作失败。安装/下载不改动用户视频或剪映工程。普通版发布不包含完整运行组件离线包，首次配置通常需要联网。

受限执行环境如果无法打开 Windows 窗口、读取 SAPI 或查询剪映进程，按宿主授权流程解决或让用户双击本机入口；不能误判为必须重装 Python，也不能把查询失败当作剪映已退出。

## 导出与搬迁

MP4 路径直接引用原片，输出无压缩帧流到最终编码器，不产生全片无损中间视频。输出为 SDR H.264/AAC，保留计划尺寸和帧率；即使旧配置里有 draft 预览宽度也不降低最终成片。逐镜头/最终帧数、音轨格式时长、完整解码和原片哈希通过后才提升 partial 文件名。任务记录仍依赖原素材及外部音乐位置，MP4 可以单独分享。

工程路径复制所用完整原片、生成独立轨道、无损中间预览与原生草稿。移动后用 `export-jianying --relocate PACKAGE` 重定位，保存并正常退出剪映后才 `--register` 到首页；不能强制结束未保存进程。当前原生草稿中的用户修改会保留。必须复制整个包，不是只复制 draft_content.json。

新电脑需重新检查剪映版本、DLL、字体和用到的矩形蒙版缓存。无矩形资源时可在测试工程给片段选一次矩形蒙版，保存关闭后复查；该步骤与 MP4 路径无关。已有用户工程不作为测试容器。

DeepSeek Harness 的项目级 `.dsh/skills/video-edit/SKILL.md` 或用户级 `%USERPROFILE%/.dsh/skills/video-edit/SKILL.md` 需要实际启用本地 Skill 读取和程序执行。安装器支持相应目录；真正加载和完整对话验收仍以宿主当前版本为准。

能力与画质限制见 [计划格式](plan-format.md)、[画质规则](quality.md) 和 [本机验证记录](validation-status.md)。
