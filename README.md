# 回忆剪辑 · video-edit

让 Codex 或 DeepSeek Harness 把旅行、家庭和活动素材剪成有故事的短片，交付可以继续修改的剪映工程。适合不熟悉 AI 和剪辑软件的用户：选素材、说想法、看初稿，再用日常语言修改。

**这是由助手调用的 Skill 和本地工具，不是自带视觉模型的独立剪辑 App。** 画面理解、听审、子智能体与生图取决于当前助手实际提供的能力；只有文字能力时不会假称已经看过视频。

## 能做什么

- 图形向导选择素材、期望长度和风格；默认中文字幕，中英双语为第二选择。
- 看带时码的多帧图片，按需局部逐帧核对，分析景别、动作、光色、质量和叙事用途。
- 根据真实素材写故事，编排有钩子的片头、张弛有度的正文与呼应前文的结尾。
- 按需委派素材、故事、文字、声音和复核子任务；没有委派工具时串行工作。
- 艺术标题优先，具备生图工具时可生成透明标题图；否则使用可用字体的大小变化、错位或醒目大字。标题图、照片和视频可放独立覆盖轨并水平/垂直移动。
- 原声默认静音，清楚且有故事价值的讲话/同期声须经审核后保留；变速镜头原声静音，嘈杂关键讲话清理后仍不清楚就舍弃。
- 独立字幕、配乐、环境音和音效轨；背景音遇实际保留的关键讲话时压低。附 5 类小型 CC0 音效库。
- 剪映工程使用完整原片副本；剪辑源不压缩，预览中间帧使用无损编码，仅最终 MP4 进行一次有损视频编码。

## Windows 安装

1. 下载仓库 ZIP 并完整解压，或克隆仓库。
2. 双击 **安装到助手.cmd**，按大字向导逐页操作。现有安装流程会先检测剪映专业版和 DeepSeek Harness；缺少时从官方来源下载安装包，再安装技能与配置环境。
3. 选择安装到 Codex、DeepSeek Harness 或两者。缺运行组件时点击“自动配置环境”；首次通常需要联网。
4. 重新打开助手，说：**“用 video-edit 帮我做一部旅行纪念片。”**

以后可以说：“多留家人的镜头”“片头像翻相册”“原声再少一点”“只要中文字幕”“结尾慢下来”。文件夹通过本机选择窗口选取，不需要复制路径或编辑 JSON。

当前执行目标为 Windows、剪映专业版和 Python 3.11+；支持的本机版本与未完成项目见 [验证记录](references/validation-status.md)。剪映草稿接口可能随软件版本变化。账户登录和软件安装界面的确认由用户完成。

## 素材与输出

本仓库不包含用户原视频、照片；本地脚本不将完整素材上传至云端分析服务。助手读取帧图、转录或调用生图时，数据处理方式仍取决于当前宿主和模型。任务目录保存素材清单、审看证据、故事与计划；输出包含完整所用原片副本、独立可编辑轨道、SRT、故事稿和 MP4 预览。移动工程应复制整个目录，再使用包内“修复并打开工程.cmd”。

MP4 预览为高质量有损 SDR，工程仍保留原片 HDR/位深信息。画幅变化、裁切和效果会改变最终画面，不能称合成 MP4 为原片无损拷贝。实际打开、编辑、保存验证与脚本检查分开记录。

## 字体与许可

本项目自有代码和文档采用 [MIT](LICENSE)。第三方资产不因此改为 MIT：

- 公开版只附辰宇落雁、志莽行两款带完整 SIL OFL 1.1 的字体，许可随各字体目录提供；其他精选字体可从用户有权使用的本地字体目录加载。实际可用字体由 `doctor` 报告，缺字会回退。
- `assets/sound-library/catalog.json` 记录 5 个 CC0 声音的原页、作者、许可、哈希和使用限制，声音来自 BigSoundBank，未默认当作本次拍摄实录。
- `assets/vendor` 内的 pyJianYingDraft wheel 使用 Apache-2.0，固定提交、哈希和完整许可随包提供。
- 不分发 Windows 字体、剪映程序/DLL、用户原片、本机配置、凭据或完整开发运行环境。其他依赖按各自许可安装。

若加入自己的字体或音乐，请保留来源与许可；本机可用不代表能够随公开仓库分发。

## 给助手与开发者

从 [SKILL.md](SKILL.md) 进入；[计划格式](references/plan-format.md)、[协作流程](references/agent-workflow.md)、[片头片尾](references/opening-ending.md) 和 [运行说明](references/runtime.md) 提供细节。四个统一命令返回结构化 JSON：

```text
python scripts/video_tool.py doctor
python scripts/video_tool.py analyze --wizard --request-only --output JOB
python scripts/video_tool.py analyze --request JOB/request.json --output JOB
python scripts/video_tool.py validate --plan JOB/edit-plan.json
python scripts/video_tool.py export-jianying --plan JOB/edit-plan.json --output DELIVERY
```

在仓库根目录运行 `python -m unittest discover -s tests`，可执行原声与视觉层的纯数据验证测试，不需要 FFmpeg 或剪映。实际媒体渲染和剪映界面另行验证，记录见 [验证状态](references/validation-status.md)。

密集取帧与声音检索分别见 `scripts/review_frames.py --help`、`scripts/sound_library.py --help`。光流补帧、自动追踪、复杂人物抠像和连续曲线变速仍不属于已自动实现能力。
