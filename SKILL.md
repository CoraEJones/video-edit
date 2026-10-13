---
name: video-edit
description: 把旅行、家庭和活动素材剪成故事短片，保留选片、叙事、节奏、字幕、混音与交付流程。2.0将剪映教程技巧抽象为可检索知识卡、带单位的图层与时间参数，可代码生成关键帧、蒙版、定格、连续变速、发光/镂空文字及组合技巧资产。支持磁盘素材记忆、分批交接、20套SDR调色、MP4或剪映工程；复杂技巧导入为合成片段。
---

# Video Edit

版本2.0.1。在原有完整剪辑流程中增加“技巧学习与代码表达”阶段；主计划仍使用schema_version 1.0，新技巧使用独立technique.2.0资产接口。doctor分别报告主计划与技巧资产能力。需要复现、学习或组合剪映技巧时读 [技巧语言](references/technique-language.md)，按需检索知识卡，不一次加载全部教程。

用户只需提供或选择素材、说明想法、确认制作单、看初稿和提出修改。主助手负责推进全流程，模型审看和作剪辑判断，脚本确定性执行。不要把内部表格、JSON、子智能体数量或环境配置变成用户作业。旅行、家庭、活动为本技能范围，分步骤教程另行处理。

## 开始工作

- 读 [协作与宿主适配](references/agent-workflow.md)。按本次实际工具选择取帧、视觉、试听、委派与生图能力，不按宿主名字猜能力。能委派且有收益时主动分工；无委派工具则主助手串行完成，不必让新手选“开启多智能体”。
- 读 [运行与交付](references/runtime.md)。Codex 与 DeepSeek Harness 只选当前使用的一个。先检查 Skill 文件/版本和实际加载情况，再按交付模式运行 `doctor`；交付未明时先补问，不默认安装剪映。`mp4` 跳过剪映、草稿库、DLL 和剪映蒙版缓存；`editable` 才扫描并复用本地剪映，缺失时引导安装。聊天入口不要求 Tk。缺组件才按运行说明配置，补齐配音/转录等需求后再 `doctor --request REQUEST` 复查；下载成功不等于已安装或已加载 Skill。
- 先读 [需求接入与确认](references/intake.md)。从用户当前提示和已确认上下文提取路径与要求，已明确的不重问。直接对话是完整入口，不强制弹窗；新手可用 `analyze --wizard --request-only --request PARTIAL_REQUEST --output JOB` 预填向导。素材路径缺失必须追问或让用户选择，不能猜文件夹、用 README 范例路径开工。输出位置缺失可建议，但需用户确认。取消不开始处理；无桌面时继续对话收集，不假称窗口已打开。
- 在确认前完成只读环境与 Skill 检查、补问缺项及冲突，展示包含实际路径、交付、故事、时长、画幅、风格、字幕、配音、音乐、必留内容、标题与首尾偏好的制作单。只在用户明确确认或向导最终确认按钮之后写入 confirmation；未经用户明确确认，不能运行 `confirm-request --user-confirmed`。确认前不得取帧分析、编排时间线、渲染或导出。用户改关键需求时先更新并重新确认，不能沿用旧指纹。
- 确认后用日常语言更新“正在找值得留下的片段”“故事顺序排好了”“正在检查字幕和声音”，自动完成约定范围内初稿，不在每个内部阶段反复确认。字幕优先简体中文，中英双语为第二选择。用户选择“只保留原声”时跳过 BGM 与所有库音，仍严格审核原声；没有合格声音时保持安静并说明。

## 从素材到成片

1. **整理证据。** `analyze --request JOB/request.json --output JOB` 生成素材清单、带时码联系表及本地转录。失败文件仍留清单。素材多或上下文紧张时读 [磁盘记忆与交接](references/material-memory.md)，运行 `scripts/material_memory.py init --job JOB`，以磁盘记录为真源，每次只领取小批或检索少量候选，不把200条完整信息塞入上下文。原片不删除、不覆盖、不预先降画质；“删废片”指不放进时间线。
2. **分段审看。** 按 [素材分析](references/material-analysis.md) 查看图片序列与转录，记录景别、主体动作、光色、构图、运动、气氛、故事用途、质量区间和可用原声。联系表初筛后，候选片段、动作/表情、对焦变化、抖动、转场两端用 [密集取帧工具](references/frame-review-tool.md) 追加审看，关键短区间可逐帧。不能把每 8 秒抽样描述成整片逐帧看完；声音判断需试听，像素评分/波形不等于语义。输出 `material-analysis.json`，观察、推断、未知分开。
3. **素材变故事。** 按 [故事与节奏](references/story-rhythm.md) 选有素材支撑的主题，写 `story-outline.json` 与 `story.txt`，每段关联实际素材区间。起承转合可用启程—探索—相遇—回望，也可跨地点围绕同一情绪；不强套巴黎例子。年龄、错过飞机、独自旅行、人物内心和历史引用不能凭空当作经历。素材稀少则做更短的诚实初稿。
4. **声音方向与粗剪。** 按 [声音设计](references/sound-design.md) 从用户音乐/音乐库选少量合适 BGM，提前获得并听审节奏候选，区分高潮、过门、安静段；仅保留通过严格音质审核的重要讲话与现场声。粗剪先保证事件和情绪逻辑。通常只做一条主方案，用户要求先看故事时再停在故事稿。
5. **精剪和技术处理。** 把故事落实到 [计划接口](references/plan-format.md) 的镜头、文字与声音轨。按动作完整性、清晰主体、信息和情绪调整入出点；保留必留片段并解释质量例外。按 [剪辑技巧](references/editing-craft.md) 选择远中近、动静/虚实、慢快慢、方向/形状/颜色匹配。过渡 1–3 秒、留白 5–8 秒可作起点，不是硬阈值；超过 15 秒复核价值。高潮可增加镜头密度、反应镜头和重音切换，人物数量不等于情绪强度。保护句子/动作，不强迫每刀踩拍。
6. **片头片尾、标题与字幕。** 按 [片头与结尾](references/opening-ending.md) 首选“精彩动作/快闪→上下黑幕揭题→正文”，照片多时考虑前景横/竖移动、后景快速走马灯；根据素材缩放节奏，不强套模板。结尾放慢、回应前文人物或细节，留尾音和停顿。按 [字体与颜色](references/typography.md)，艺术标题优先：有生图工具时生成短标题透明图，检查文字和背景适配后放入 visual_layers；没有或生成不佳时用 [可用字体](references/font-catalog.md) 做大小变化、错位、错时或醒目大字。文字尽量落在稳定颜色分区，取画面颜色并拉开局部明暗对比。讲话字幕保持简单清楚；故事短句必须与正在发生的画面相符，不能用字幕强造情绪转变。字幕关闭则 `captions=[]`，配音关闭仍可交付文案。
7. **严格原声与混音。** 先读 [原声审核](references/original-audio.md)。原视频音频默认静音，仅实际听审合格、清晰关键讲话或特别有故事价值的同期声可保留。风噪、杂音、爆音或听感差就舍弃；关键话语可先轻度清理，处理后仍不清楚就静音，用核实后的字幕承接，不根据不可靠转录编对白。所有变速镜头原声静音。BGM、旁白、审核合格原声和必要库音分轨，淡化衔接，在实际输出的关键讲话/配音处压低背景。环境音按需从有来源/许可的库补充，不能声称是现场实录；不把海浪、蝉鸣、雨等每种都加上。
8. **校验与导出。** 主助手合并 sidecar 到唯一 `edit-plan.json`，完整保留已确认 `request`，不改其中目标时长来伪造符合要求；实际时长放计划顶层。按 [画质规则](references/quality.md) 使用所选素材分辨率/帧率。`review` 记录实际审看、选片与必留依据，真的审看后才写 `status=reviewed`。先 `validate --plan PLAN` 修复，再按 `request.delivery_mode` 选择 `export-mp4` 或 `export-jianying --plan PLAN --output DELIVERY`；DELIVERY 必须是确认的输出父目录，工具在下面创建新作品目录。MP4 直接从原片合成；工程模式生成独立镜头、文字和声音轨及预览。修订从原片重导新名称，不覆盖旧工程、不反复压制成片。
9. **复核修正。** 按 [验收标准](references/acceptance.md) 查开头、场景转换、高潮、所有标题/字幕首中尾、声音进出和结尾。核对原片哈希、源出点、音画同步、可读性、重复/空镜、配乐衔接和响度。可委派独立复核，主助手负责最终结果。结构检查、预览检查、剪映实际打开/编辑/保存分别记录；未能试听/打开时如实列出。只重做受影响阶段。

## 执行约束

- 七个命令 stdout 为一个 JSON，进度写 stderr。使用本机已配置 Python；PowerShell 脚本用 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File`。完整参数见 `python scripts/video_tool.py <command> --help`。
- `doctor` 不证明宿主有视觉/子智能体/生图能力。无视觉时不能按文件名假装审看；用户描述可用于标记清楚的文字草案，但不能因此把 review 标为 reviewed 或导出自动精选成片。视觉选片与质量验收等待可用视觉；用户提供已核实的明确镜头区间时可作人工选片依据，必须标明用户提供与助手未审看的范围，不能伪造视觉验证。
- `--no-transcribe` 仅在用户不需要讲话识别、无音轨或诊断时使用并说明限制。`--no-preview` 不等于完成视觉验收。离线配音只用 doctor 实际发现的音色；声音过长须缩稿或扩镜头，不截断句子。
- 遵守确认的 `title_mode` 与 `audio_policy`：`fonts_only` 只用字体排版，不生成艺术字图片；`mute_all` 全部原声为零；`key_speech_only` 只保留审核清楚的关键讲话。`voiceover=false` 时不生成配音音轨。首尾偏好也优先于推荐模板。
- `techniques` 名称本身不生成效果，必须落实轨道/参数。分段变速不是连续曲线，矩形蒙版不是人物抠像；光流、跟踪、复杂抠像等不可把建议写成已完成。支持详情见计划接口。剪辑使用原片；临时渲染用无压缩帧流或无损中间片，仅最终 MP4 做有损视频编码，不为省时间提前降画质。
- 2.0技巧可用 `scripts/technique_tool.py catalog/recipe/validate/compile/render`。先确定故事用途，再展开成明确参数；曲线使用输出时间速度积分，声音独立处理。生成无损透明MOV后审看、登记派生素材并回到上述主流程。知识卡的语义表达不能直接执行；专有预设、烟雾/墨迹/贴纸、特定声音要实际资源。对应参数尚不能作为原生剪映特效往返编辑。验证方法见 [技巧评测](references/technique-evaluation.md)。
- 不上传完整素材到第三方分析服务。子智能体只读分配材料；艺术标题默认用文字描述生成，提供用户画面给外部模型须符合当前任务授权。
- 批次结果包含所有分配编号、input_fingerprint、coverage、segments和未知项，核验后由memory ingest/compile合并；上下文重启先读request、workflow-state、memory status和故事摘要，再按需检索，不依赖模型记得上轮。新任务用review.analysis_path关联分析、每个选段填segment_id；必留瞬间用request.must_keep_ranges，详见 [证据与计划接口](references/plan-format.md)。
- 需要调色时读 [调色接口](references/color-grading.md)：先确认输入空间、校正曝光/白平衡并匹配相邻镜头，再选择20套原创BT.709 SDR外观及强度。调色现支持MP4与预览，原生剪映明确拒绝有效调色，不能冒称已经写入。LUT不能修复过曝/模糊。
- 性能与公开素材来源按 [基准流程](references/benchmark.md)，区分下载/解码/索引、模型实际审看和人工盲评，不能用工具测试替代选片质量。

```text
doctor --host codex --delivery-mode mp4 --entry-mode chat [--request REQUEST]
request-check --request REQUEST
confirm-request --request REQUEST --user-confirmed
analyze --wizard --request-only --output JOB
analyze --request JOB/request.json --output JOB
validate --plan JOB/edit-plan.json
export-mp4 --plan JOB/edit-plan.json --output DELIVERY
export-jianying --plan JOB/edit-plan.json --output DELIVERY
export-jianying --relocate PACKAGE [--name 新副本名称] [--register]
```

## 交付与修改

按已确认交付选择提供可点击的 MP4、故事稿/SRT和简短说明，技术 sidecar 留任务目录备查。MP4 模式不生成剪映工程、不复制全部原片；后续重剪需保留原素材和外部音乐。工程模式额外提供工程文件夹，引用 `assets/originals` 完整原片副本，保留原分辨率、帧率和 HDR。MP4 为有损 SDR，不能称为逐像素无损。

显示到剪映首页前需保存并正常退出剪映，再 relocate/register；不强制结束未保存进程。搬电脑复制整个工程包，运行“修复并打开工程.cmd”，重定位读取当前工程保留修改。用户说“快一点”“多留家人”“标题温柔一些”时复用分析，只改有关阶段并输出新版本；已在剪映改过时明确基于当前工程还是旧计划，不覆盖其编辑。不要导入带固定全局变量的历史脚本或在历史工程里试运行。
