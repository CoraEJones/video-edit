# 书法标题引入实验渲染 API

此工具是主计划1.0之外的独立标题实验接口，同时交付静音MP4和剪映工程。确认制作单前，只运行 `synthetic-self-test`，不处理用户素材。主成片仍使用video_tool原流程；只要MP4时不要求剪映。

```powershell
python scripts/render_titles.py synthetic-self-test --output NEW_SYNTHETIC_DIR
python scripts/render_titles.py validate --design CASE/design.json
python scripts/render_titles.py render --design CASE/design.json --output NEW_CASE_OUTPUT
python scripts/render_titles.py render --design CASE/design.json --output SAME_CASE_OUTPUT --resume
```

`--config MACHINE.json` 放在子命令前，可指定本机video-edit配置；不指定时用本包config.local.json或VIDEO_EDIT_CONFIG，并发现本机工具。不含用户配置的分发包从config.example.json取得默认值。render与synthetic-self-test需要FFmpeg、FFprobe、pyJianYingDraft严格0.3.0，以及实际可用的剪映安装DLL；validate只读检查源与PNG，不需要写原生工程。输出目录必须全新，或使用匹配输入指纹的 `--resume`。

`references/title-intro.schema.json`说明独立设计接口，`references/title-visual-qa.schema.json`说明QA请求；跨字段帧对齐、源范围、alpha、曲线终点和原件哈希以可执行validate为准。合成自检自己生成测试底片、笔画与配件，无用户素材、无中文生成或审美通过声明。`python scripts/title_qa_example.py --output NEW_QA_EXAMPLE`另生成无需剪映的QA像素例子。

视觉QA入口为 `python scripts/visual_qa.py --request QA_REQUEST.json --output NEW_REPORT.json --preview-dir NEW_PREVIEWS`。请求中的画布字段是width_px/height_px，和title-intro的width/height不同。输入实际背景帧必须已适配到相同画布；transform需要x_px/y_px/width_px/height_px，可以逐帧覆盖。它绕整张重采样PNG中心旋转；要检查渲染器自定义pivot的某一帧，应从共享运动表解算等价PNG中心坐标，不能直接把path_dx_px传作绝对x。可另将实际最终视频帧交给人审看。每帧提供源秒、标签和人工保护矩形；无自动人脸识别、主体追踪或OCR。数字报告默认human_visual_review=pending。

每条 JSON 的 `schema_version` 是 `title-intro.1.0`。`id` 为唯一编号；`title_text` 用于人工核字。`source` 包含 `path`、`source_in_s`、`duration_s`（4–6 秒，精确项目帧边界）、可选 `sha256`。`canvas` 默认为 854×480、60 fps。

`title` 与每个 `accessories` 元素包含 `path`（真实透明 PNG）、`x_px`、`y_px`、`width_px`、`start_s`、`end_s`、`motion`。配件还需唯一 `id`。坐标均为静止状态 PNG 整张画布的左上像素，宽度是整张 PNG 宽度；含透明留白的画布允许合理越界，实际 alpha>16 的字形范围在静止时必须位于安全区域。标题默认安全边距16像素，配件默认0，可设置 `safe_margin_px`。生成原件不裁剪、不覆盖。

`motion.type` 可为 `slide_fade`、`scale_fade`、`staggered`。公共参数为 `enter_s`、`exit_s`、`dx_px`、`dy_px`、`from_scale`、`stagger_s`、`exit_dx_px`、`exit_dy_px`、`easing`（`smoothstep` 或 `linear`）。`dx_px/dy_px` 表示入场起点相对静止位置的偏移；`from_scale` 只用于 `scale_fade`；错时由 `stagger_s` 决定。每层都生成独立逐项目帧运动表，FFmpeg 与原生工程共用这些时间和值。

新增流水线 `title-intro-pipeline.1.1.0`，设计 schema 仍兼容 `title-intro.1.0`。流水线版本进入输入指纹，旧版本结果不得当作新版本恢复。

- `curved_path`：`cubic_bezier_points_px` 必须显式给4个 `[dx,dy]` 控制点，单位为画布像素、相对PNG静止位置的偏移。最后一点必须 `[0,0]`。入场进度由 easing 调整后进入真实三次贝塞尔位置公式；不是把4点折线相连。没有从静态参考图推断真实轨迹。
- `rotate_settle`：`from_rotation_deg` 到 `rotation_deg`；正角为顺时针，负角为逆时针。所有类型都可附带这两个角度。
- `rotation_keyframes=[{time_s,rotation_deg},...]`：可显式设置入场、稳态和退场角度。局部时间从0开始、严格递增、落在项目帧上。提供时覆盖自动角度/角度overshoot。
- `settle_s`：入场走完后用于轻微回落的时长。`overshoot_px` 最大24像素，方向沿入场起点到稳态的延长方向；`overshoot_rotation_deg` 为达到稳态时额外的角度。必须给正 settle_s，之后回到设计稳态。没有物理弹簧或本机贝塞尔曲线原生控件的等价承诺。
- `pivot_px=[canvas_x,canvas_y]`：旋转/缩放中心，默认实际 alpha 字形包围框中心。原生PNG围绕画布中心变换，脚本自动补偿位移，使指定字形中心按同一轨迹运动。

`motion-table.json` 保存逻辑路径 `path_dx_px/path_dy_px`，以及实际送给原生全画布 PNG 的补偿 `dx_px/dy_px`、`scale`、`rotation_deg`、`opacity`。原生工程逐帧线性关键帧使用相同样本，没有冒充原生Bezier控制柄。

```json
"motion": {
  "type": "curved_path",
  "cubic_bezier_points_px": [[-90,35],[-45,-50],[30,-25],[0,0]],
  "enter_s": 0.8,
  "settle_s": 0.25,
  "overshoot_px": 5,
  "from_rotation_deg": -8,
  "rotation_deg": 0,
  "overshoot_rotation_deg": 1,
  "exit_s": 0.45,
  "easing": "smoothstep"
}
```

`python -m unittest discover -s tests -p "test_title_motion.py"` 使用非对称标记像素测试顺时针方向、自定义中心、真实曲线中点、首中尾alpha、有限回落和显式角度关键帧。`synthetic-self-test` 另外实际渲染曲线路径与旋转配件，并回读实际加密工程，逐项比较所有运动样本。它们证明代码像素方向与工程参数符号，不代替剪映界面中的实际画面验收。

`design` 对象原样保留，可写配色、字体类型、小配件依据与审美检查。脚本不会把这些描述自动视为实际审看结果。

原片仅在最终 H.264 输出编码一次；图形显式按 sRGB 声明经现有 image_color 转入 BT.709、保留 alpha。背景没有加 LUT；未核实色彩的源视频不会被冒称已验证。最终视频无音轨，原声静音、无配乐。实际生成源素材、生成器 PNG 原件均复制到工程中并校验 SHA256。

源视频的 SAR 作为真实显示宽高比解释，不擅自改写输入元数据。`source.display_geometry` 保存显示尺寸、最接近的整数栅格适配尺寸、黑边位置，以及原生原片轨对应的缩放和位移。FFmpeg直接读取原片按该尺寸适配，原生保留原片并写相同参数；编辑器是否额外解释SAR仍需实际UI核对。实际合成SAR2:1样本验证了854×480编码源应在目标854×480中显示为854×240、上下120像素黑边，并验证原生工程回读y缩放0.5。该测试不代替编辑器实际视觉验收。

剪映工程保留原片、书法 PNG、小配件 PNG 独立轨；移动、缩放、旋转、透明度可编辑。每张 PNG 内部字形和静止布局属于像素素材，不是可编辑汉字。工程使用独立 pyJianYingDraft0.3.0 和实际本机 DLL 加密回读，不注册用户草稿、不操作剪映界面。`ui_verified=false`，不能用加密结构验证替代打开、播放、编辑、保存检查。

技术输出包括 `case-report.json`、`case-state.json`、首中尾取帧以及每层 `motion-table.json`。`visual_reviewed` 与 `audio_auditioned` 默认都是 false；主助手实际审看后另写审看记录。完整解码、准确帧数、源哈希、透明通道与实际 native codec 回读是自动检查范围。
