# 回忆剪辑 · video-edit

让 Codex **或** DeepSeek Harness 把旅行、家庭和活动素材剪成有故事的短片。两者只需一个；你可以只拿 MP4，也可以同时保留剪映可编辑工程。

**v1.6.0：双入口、按需安装、先确认再剪辑。** [查看更新](CHANGELOG.md) · [下载最新版本](https://github.com/CoraEJones/video-edit/releases/latest)

这是由助手调用的 Skill 和本地工具。助手负责看画面、编故事和作剪辑判断；是否能听音、调用子智能体或生成艺术字，取决于当前会话实际提供的工具。

## 先选交付方式

| 你希望拿到什么 | 需要的软件 |
|---|---|
| **只要 MP4 成片** | Codex 或 DeepSeek Harness，**无需下载剪映** |
| **MP4 ＋剪映可编辑工程** | Codex 或 DeepSeek Harness，加本地剪映专业版；先扫描已有安装，缺少时再引导安装 |

选择哪种交付方式，都能使用下面任意一个入口。首次配置会复用已有组件，只补齐当前模式需要的组件。

## 路径一：熟悉 Agent，直接在对话框开始

如果你有一定的 vibe coding 或 Agent 使用经验，先把本仓库安装为当前助手的 `video-edit` Skill，然后复制这段请求。**范例中的路径要换成你的实际路径；不知道路径时用下面的简短范例，让助手追问。**

```text
请使用 video-edit Skill 剪辑 D:\旅行素材，输出到 D:\旅行成片。
我只需要 MP4，不需要剪映工程。希望约两分钟、横屏、有电影感、中文字幕、不配音，音乐由你选择。
请先检查环境和 Skill，从我的描述中提取已明确的路径和需求；没有提到、含糊或冲突的内容请补问，不要猜素材目录或直接套用范例路径。
汇总制作确认单给我确认后，再开始分析素材、剪辑和导出。
```

还没想好也可以直接发送：

```text
请使用 video-edit 帮我剪辑一部旅行短片。
先检查 Skill 和环境，问我素材在哪里、输出到哪里，以及只要 MP4 还是还要剪映工程。
其他需求请给我易懂的选项和推荐；已回答的不要重复问。汇总给我确认后再开工。
```

想保留工程，把“只需要 MP4”改成“需要 MP4 和剪映可编辑工程，请先扫描本机剪映”。助手会按你当前使用的宿主工作，不要求再安装另一个助手。

## 路径二：第一次使用，跟着大字向导点选

1. 从 [发布页](https://github.com/CoraEJones/video-edit/releases/latest) 下载 ZIP，**完整解压**。
2. 双击 **安装到助手.cmd**：选 Codex 或 DeepSeek Harness，再选“只要 MP4”或“MP4＋可编辑工程”，选择大字向导入口。
3. 扫描本地软件。已有软件直接复用；只为选择的模式提示缺少的软件。仅工程模式检查剪映。
4. 安装 Skill，检查环境；有缺项时点“自动配置缺少组件”。语音识别和配音按需要配置。
5. 重新打开所选助手，发送安装窗口提供的请求；也可点 **开始选素材**，逐页填好需求。向导保存需求单，随后回到助手继续制作。

安装窗口不需要预装 Python 才能打开。普通版首次配置通常需要联网；软件安装界面和账号登录由你操作。旧版用户用新版安装器再次安装，保留已有本机配置。

## 开工前会确认什么

助手先提取你已明确的信息，再集中补问缺项：

- 素材路径、输出位置、只要成片还是同时保留工程。
- 作品名称、人物和故事背景、主题、时长、横竖屏、节奏，以及必留或不要的内容。
- 字幕和语言、是否配音及声音偏好、配乐方式或自选音乐。
- 标题是否接受艺术字图片、原声如何保留、片头与结尾偏好。

不确定的创作选项可以选“由助手推荐”。**素材路径必须提供或选择；输出路径缺失时，助手可以建议位置，但会请你确认。** 已明确的回答会预填，不让你重复填写整张表。

确认单会把实际路径和制作方案一起展示。你回复确认或点击向导最后的确认按钮后，才开始分析、剪辑和导出。取消不会开始制作；后续改变路径、交付方式或关键偏好，需要确认新的制作单。

## 剪辑效果与交付

- 看带时码的多帧图片，候选片段进一步密集审看，挑选清楚、有用的画面，按需委派素材、故事、标题、声音和复核子任务。
- 故事来自真实素材。精彩片段快闪＋上下黑幕揭题为首选片头，照片多时可做横竖走马灯；正文有快有慢，结尾放慢并呼应前文。
- 艺术标题优先，按背景留白和局部颜色对比设计；无生图能力或效果不佳时，用字体库做大小变化、错位或醒目大字。艺术字图片的文字内容需重新生成；需要可编辑文字可明确选字体方案。
- 原声默认静音，只有实际听审清楚且有故事价值的声音才保留；变速原声静音。关键讲话轻度清理仍不清楚就舍弃。字幕中文优先，中英第二，简单易读。
- 剪辑引用原片，临时合成用无压缩帧流或无损中间片；只在最终 MP4 做有损视频编码。MP4 默认匹配项目分辨率和帧率，原素材不改动。

**MP4 模式**交付成片、字幕、故事稿和剪辑记录，不生成剪映工程，也不复制全部原视频。以后需要重新剪辑时，请保留原素材及所用外部音乐的位置。

**工程模式**还交付独立视频、文字、声音轨的剪映工程及所用完整原片副本。移动时复制整个工程目录，使用包内“修复并打开工程.cmd”；修改输出新版本，不覆盖已有工程。

MP4 为有损 SDR 成片；HDR 原片保持不变，不能把合成 MP4 称为原片无损拷贝。实际剪映打开/编辑/保存与程序检查分开记录，详见 [验证记录](references/validation-status.md)。当前执行目标为 Windows、Python 3.11+；剪映接口随版本变化，完整离线组件包不包含在此普通版发布中。

## 给助手与开发者

从 [SKILL.md](SKILL.md) 开始。路径、补问与确认规则见 [需求接入](references/intake.md)；环境分支见 [运行说明](references/runtime.md)；另有 [计划格式](references/plan-format.md)、[协作流程](references/agent-workflow.md)、[片头片尾](references/opening-ending.md)。

```text
python scripts/video_tool.py doctor --host codex --delivery-mode mp4 --entry-mode chat
python scripts/video_tool.py request-check --request JOB/request.json
python scripts/video_tool.py confirm-request --request JOB/request.json --user-confirmed
python scripts/video_tool.py doctor --host codex --request JOB/request.json
python scripts/video_tool.py analyze --request JOB/request.json --output JOB
python scripts/video_tool.py validate --plan JOB/edit-plan.json
python scripts/video_tool.py export-mp4 --plan JOB/edit-plan.json --output DELIVERY
```

上面的 `JOB` 是内部任务目录，`DELIVERY` 必须与用户确认的输出位置一致。`--user-confirmed` **只在用户真实确认后使用**，不是跳过对话的开关。工程模式改用 `export-jianying`；向导采集需求使用 `analyze --wizard --request-only --output JOB`。七个命令返回结构化 JSON。

在仓库根目录运行 `python -m unittest discover -s tests`；可选真实 FFmpeg 合成测试和 PowerShell 分支测试见 [验证记录](references/validation-status.md)。没有视觉工具时不能声称已经审看；没有试听工具时不能把原声自动判为合格。光流补帧、运动追踪、复杂抠像、连续曲线变速仍未自动实现。

## 数据与许可

自有代码和文档采用 [MIT](LICENSE)。本地工具不把完整素材上传到第三方分析服务；助手读取帧图、转录或调用生图时，处理方式取决于当前宿主与模型。

- 公开版附辰宇落雁、志莽行两款带完整 SIL OFL 1.1 声明的字体；其他字体可从你有权使用的本地目录加载。
- 五个 CC0 音效在 `assets/sound-library/catalog.json` 记录原页、作者、许可与哈希。库音不会冒充拍摄现场实录。
- `assets/vendor` 内草稿库 wheel 使用 Apache-2.0，来源、固定提交、哈希与许可随包提供，仅工程模式需要安装。
- 不分发用户原片、Windows 字体、剪映程序/DLL、本机配置、凭据或开发环境。第三方字体、音效、音乐及依赖仍遵守各自许可。
