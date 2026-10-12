# 剪辑计划 1.0

顶层：schema_version、name、width、height、fps、duration、inventory_path、request、shots、panels、titles、captions、chapters、narration、audio_layers、visual_layers、techniques、review。1.5 保持计划版本 1.0，增加可选 visual_layers 和 mask_reveal.hold；正增益原声需新增实际听审记录，旧计划不能绕过此要求。

所有时间为秒。duration 是时间线时长；素材出点 = source_in + duration × speed。帧对齐用 round(seconds * fps) / fps；相邻镜头 start 使用前一镜头的终点，避免累计空隙。脚本内部转换为整数微秒。

```json
{
  "schema_version": "1.0",
  "name": "把夏天留下",
  "width": 1920,
  "height": 1080,
  "fps": 30,
  "duration": 8,
  "inventory_path": "inventory.json",
  "request": {"voiceover": false, "subtitles": true, "music": "自动配乐", "target_seconds": 10},
  "shots": [
    {"index": 1, "id": "使用清单中的真实编号", "source_in": 2, "duration": 8, "speed": 1, "start": 0, "purpose": "opening", "audio_gain": 0}
  ],
  "panels": [],
  "titles": [{"text": "把夏天留下", "start": 0.5, "end": 3, "x": 0, "y": 0.05, "size": 13}],
  "captions": [],
  "chapters": [],
  "narration": [],
  "techniques": ["montage"],
  "review": {"status": "reviewed", "evidence": ["填写实际已查看的画面和时间点"], "selection_reason": "填写实际剪辑理由", "omissions": []}
}
```

以上仅说明格式，不能把示意证据原样用于真实验收。示例 1920×1080 / 30 fps 不是通用默认值；依据所选素材的 recommended_quality 设置实际分辨率和帧率，见 [画质规则](quality.md)。

## 素材、画幅、主轨

- inventory_path 相对计划目录解析，也可绝对路径；清单是 analyze 输出的数组。每个素材包含 id、absolute_path、kind(video/image)、duration、width、height、fps、fingerprint、frames、contact_sheets、transcript。
- 可内嵌 inventory 数组。已有 v5 清单可适配到这些字段；旧项目特有 chapter 冻结图卡和 custom_source_crops 不会自动迁移，需要显式转换为照片素材或新计划，不能静默忽略。
- 主轨 shots 按 start 排序，始终从 0 连续到 duration，不重叠。帧率 24/25/30/50/60。
- 照片可安排任意正时长，默认 source_in=0、speed=1。视频不得越过真实源时长。
- shots 可加 zoom=[1,1.06]、fade_out=0.5；不做自动人脸跟踪，缩放须检查人物是否被裁掉。
- shots 的 audio_gain 默认 0；正增益必须有 [原声审核](original-audio.md) 的 audio_review，只有正常速度、清楚且有故事价值的声音可放行。important_speech 不会自行保留声音或压低配乐。audio_lead/audio_tail 单位为时间线秒，用于已审核声音的 J/L 衔接；审核范围必须覆盖实际可用源区间内的前后延续。变速原声一律静音。

## 分屏和蒙版

三分屏的主轨镜头 purpose 使用 panels_triptych，保持黑底占位，避免剪映自动吸附空隙。panels 中放三条相同 index/start/duration 的记录，panel 分别为 -1/0/1；其余 source_in/speed/id 同普通镜头。每条对应独立蒙版轨。

mask_reveal={"start":0,"duration":0.7} 表示上下两块黑色矩形移开；采用位置关键帧。mask_reveal 区间必须在时间线内。普通画面在时间线保持比例适配画布，空白处为黑底；原片不预先缩小。分屏只显示中心区域，蒙版尺寸按原片适配后的大小计算，需实际查看主体。

## 可选视觉叠层与照片走马灯（1.5）

顶层 `visual_layers` 数组在主轨/分屏上叠加图片或视频；透明 PNG 可作艺术标题。每层使用清单中真实 `id`，生成资源后先把图片加入 inventory，再引用。原件逐字节打包；不会把标题烘焙进原片。主轨可同时快速切换背景，叠层可以连续跨过多个主轨切点。数组后面的层显示在前面层之上；黑幕揭幕盖在所有视觉叠层之上，原生文字和字幕继续位于最上方。

```json
{
  "visual_layers": [
    {
      "id": "实际照片编号", "start": 0, "duration": 2, "scale": 0.45,
      "keyframes": [
        {"time": 0, "x": -1.4, "y": 0},
        {"time": 0.6, "x": 0, "y": 0},
        {"time": 1.4, "x": 0, "y": 0},
        {"time": 1.96, "x": 1.4, "y": 0}
      ],
      "purpose": "横向照片进入、停留、离开"
    },
    {"id": "透明标题图片编号", "start": 0.8, "duration": 1.2,
     "x": 0, "y": 0.6, "scale": 0.6, "purpose": "艺术标题"}
  ],
  "mask_reveal": {"start": 4.6, "duration": 0.72, "hold": 0.2}
}
```

示例以 25 fps 为准；实际 id 必须替换，总时间线须包含图层和揭幕时段。

- 允许字段：`id/start/duration/source_in/speed/x/y/scale/keyframes/purpose`，未知字段直接报错。`source_in=0`、`speed=1`、`x=y=0`、`scale=1` 为默认。图片只能 source_in=0、speed=1；视频速度 0.25–4，源出点为 source_in+duration×speed，不得越界。叠层始终静音；需要保留关键讲话时在主轨独立安排并经过原声审核。
- x/y 是素材中心相对画布中心的位置，以半幅宽/高为单位：x 正向右，y 正向上；范围 -4–4，允许进入/离开画外。scale 为原素材等比适配画布后的静态缩放，范围 0.01–4；与图片实际透明边距一并计算。尺寸转换存在最多约 1 像素的取整差异。
- `keyframes` 可省略，省略时使用静态 x/y；存在时，每点必须恰有 time/x/y。time 是层内秒，严格递增并对齐帧率；第一点必须是 0，最后一点必须是 **duration−1/fps**，确保最后可见帧实际到达终点。一帧图层可只有 time=0 一个点。存在关键帧时以关键帧中的 x/y 为准。
- 原生工程和预览均使用同一组时间点做线性插值；相同位置的两个相邻关键帧表示停留。竖向走马灯固定 x、改变 y。当前不支持图层缩放动画、旋转、曲线插值、自动抠像或运动跟踪，不能填写未执行的参数。
- 图层 start/duration 均须对齐项目帧率，范围须完全位于时间线内。`techniques` 可标记 visual_layers、photo_carousel、art_title_overlay，仍需真实图层参数；标记自身不产生效果。
- `mask_reveal.hold` 为可选的全黑停留秒数，须满足 0≤hold<duration；随后在 duration−hold 秒内向上下打开。省略保持旧版 duration×0.25。上述示例完整复用 4.6 秒起、停 0.2 秒、开 0.52 秒的节奏。当前不支持持续上下黑边夹持。
- 预览的镜头中间文件使用 **FFV1 无损压缩**；拼接时复制视频流，叠层、揭幕、文字合成之后只在最终 MP4 做一次 H.264 有损视频编码。无损中间编码不代表合成过程保留原像素：画幅适配、缩放、HDR 到 SDR 预览仍会改变显示；原生工程始终引用未经转码的原件。

## 文本和文案

- captions: {start,end,text,language,kind}。kind 为 speech 或 story。默认简体中文，第二选择中英双语；故事字幕承接真实事件，不虚构经历。双语可用两个对象，也兼容 {start,end,zh,en} / {start,end,zh,es}；两种语言分别在原生文字轨。
- titles: {start,end,text,language,x,y,size,rotation,animate}。x/y 使用归一化坐标 -1..1，y 正值向上；兼容旧 v5 像素坐标。默认 size=10，字幕默认 3.75。标题独立错时入场，自动安排重叠轨道。request.text_style 默认“自动搭配”，也可选“清爽现代”“温暖手写”“安静电影感”“洒脱书法”；字体与颜色依据见 typography.md。
- 单条 titles/captions 可设置 font_family（字体内部名称）、font_id（doctor 返回的字体文件编号）、font_family_en（英文搭配字体）及 color="#RRGGBB"。未指定时自动搭配；指定字体缺字时记录回退。所用精选字体随新工程打包，详见 font-catalog.md。
- chapters 记录故事结构，具体显示文字需同时写 titles；章节元数据不会凭空生成图卡。
- narration: {start,end,text,language}，仅 request.voiceover=true 时合成离线声音。language 例如 zh-CN、en-US、es-ES。保留完整文案，不能切词凑时间。
- 故事正文另存 story.txt 便于用户阅读；字幕关闭时 captions 必须为空，但可以保留片名 titles。若用户连片名也不想要，则 titles 也清空。

## 可选音乐、环境增强和音效轨（1.4）

主助手先选音乐再精剪，具体判断见 [声音设计](sound-design.md)。单曲沿用 `request.music_file`（自动配乐也可指定）；已配置 music_library 却未指定曲目时返回 MUSIC_SELECTION_REQUIRED，不再按文件名取第一首。无音乐库、未指定音乐时仍可生成明确标记的简单程序伴奏。

多段 BGM 或环境音用顶层 `audio_layers` 对象数组。每层独立可编辑，原件及来源报告随工程复制。示例路径必须换成实际本地绝对路径：

```json
{
  "kind": "ambience",
  "path": "D:/声音库/海浪.mp3",
  "start": 8,
  "duration": 6,
  "source_in": 2,
  "gain": 0.18,
  "fade_in": 0.4,
  "fade_out": 0.8,
  "loop": false,
  "source_note": "后期补充海浪，来源为库音，非本次现场实录",
  "license": {"name": "CC0", "source_url": "原发布页", "license_url": "已核对的许可页", "author": "目录中作者"}
}
```

- kind 为 `music/ambience/sfx`；start/duration 是时间线秒，source_in 是源秒，音频速度固定为 1。默认 source_in=0、gain=.25、fade_in=.2、fade_out=.3、loop=false。gain 是 0–2 的线性音量，不是 dB；需听审最终混音。
- 文件必须存在、有音频流。时间不能为负/越界，未循环时源出点不超过源时长；需显式 loop=true 才循环。淡化不超过该层时长。循环不是自动无缝，在接缝试听；分段交叉淡化可以用两层重叠和各自淡化。
- 存在 music 层时替代整片默认配乐，不再同时生成另一首。没有 music 层而允许配乐时，仍依 request 配乐。用户选“只保留原声”时 `audio_layers` 必须为空，包含外加环境音也会报错，不能绕过用户偏好。
- source_note 必填；来源/许可对象复制到 audio-plan.json，库音效须从 catalog.json 携带实际来源、作者、许可、已核验哈希。用户自己的录音可说明来源；不能凭空授予使用权。
- 可选 sha256 用于核对实际音频是否改变。未列出的执行字段会报错，不能用 source_out、source_start、speed、keys 或 duck 假装已有未实现的能力；额外说明放 source_note 或 license 元数据。
- 音乐、环境层和音效层在实际输出的 key_speech 原声与配音时段压低后平滑恢复；静音镜头的 speech 字幕或 important_speech 标记不触发压低。音量关键帧相对各自层起点，自动与预览和原生音轨一致。
- 输出 audio-plan.json 记录原件哈希、库音用途、事件和 master_gain；混音整体限制峰值，最终仍要听审。此接口不自动下载、不语义挑选、不生成环境音。

## 已审看证据与能力约束

review.status=reviewed；evidence 为实际审看时间点/转录引用。selection_reason 说明叙事；omissions 记录每个未用素材及原因。request.must_keep 非空时，review.must_keep_resolution 说明如何满足；必留文件必须真实出现在选中镜头中。

techniques 支持 montage、action_opening、slow_fast_slow、shot_size_sequence、split_screen、mask_reveal、j_cut、l_cut、beat_cut、staggered_titles、segmented_speed、zoom、fade。这些名字标记实际使用的设计，不会仅因填写就自动生成对应效果。对应轨道/参数必须由计划落实。

不支持 optical_flow、motion_tracking、complex_matting、continuous_speed_curve。validate 对这些声明直接报错。语义选片和文案由已具备视觉/语言能力的 Harness 模型完成，本地脚本不内置另一个云端模型。

## 返回约定

stdout 只输出一个 JSON 对象：{ok,code,data}，失败增加 message。退出码：0 成功/取消，2 可处理错误，1 意外错误，130 中断。进度写 stderr。取消为 CANCELLED，分析完成为 NEEDS_EDITORIAL_REVIEW，不意味着剪辑完成。
