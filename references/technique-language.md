# 技巧语言 2.0

技巧服务于故事的可读性、动作和情绪。先完成主流程的需求确认、素材审看、故事与粗剪，再按具体问题检索技巧。不要因素材多就为每个镜头加效果。

## 从剪映操作到可执行参数

把“放上轨、拉到这里、放大、打关键帧、加蒙版”翻译为有单位的状态：素材身份、源入点、输出时间区间、图层顺序、变换、透明度、蒙版和混合关系。图层数组从下到上；声音始终单独建轨。教程的旧界面位置不作为自动化接口。

`python scripts/technique_tool.py catalog --query 蒙版` 返回最多10张匹配摘要（可用--limit 1..20与--offset分页），再用 `catalog --id L015` 只加载需要的完整卡。每张卡含意图、输入、操作顺序、参数、时间关系、验证点和限制。卡片里的 `code_expression` 是规划用的语义表达，不能直接当 Python 或 FFmpeg 执行。只有 `technique.2.0` 和配方工具接受的字段可以编译。

| 标签 | 含义 | 执行要求 |
|---|---|---|
| direct_math | 时间、几何或混合关系可明确表达 | 仍须找到对应运行接口；不代表每条知识都已有自动实现 |
| asset_required | 烟雾、墨迹、贴纸、声音或特定预设需要资源 | 提供实际本地资源、来源和许可，不能冒称自带 |
| approximation | 原预设算法、节奏或包络不明确 | 标明采用的近似参数，渲染后审看 |
| unverified | 现有证据不能确认 | 保留未知，不据此导出声称已复现的结果 |

卡片的 `execution_routes` 进一步区分 typed（新编译器）、recipe（可执行配方）、workflow（原流程）、external（资源要求）、knowledge（仅规划知识）。完整范围见 [学习覆盖记录](tutorial-coverage.json)。

## 时间和坐标约定

- 项目 `start/duration`、关键帧和卡点均以**输出时间线秒数**计。区间为 `[start,start+duration)`；首关键帧为0，末可见帧为 `duration−1/fps`。时长与放置时间对齐项目帧率。
- `source_in`、`freeze_at` 是**原片秒数**；恒速源跨度为 `duration*speed`。定格取解码器在指定位置取得的首帧，VFR素材须审看实际选帧，不保证任意小数秒都有对应帧。
- 连续变速的速度节点定义在输出时间上，速度在节点间线性变化；源时间 `s(t)=source_in+∫speed(t)dt`，编译器用解析逆函数映射 PTS。内部速度节点可位于子帧；端点必须覆盖完整输出时长。最后转换为项目CFR会重复/舍弃帧；**没有光流补帧**。恒速、曲线、倒放、定格有冲突时拆成独立步骤。
- `x/y=0` 为中心；x正向右、y正向上；1对应画布宽/高的一半。缩放1为适配画布后的尺寸，旋转单位为度，文字与羽化单位为像素。图层先 contain 到画布，透明补边，然后变换。旋转保留变换前图层尺寸，角可能裁切；需要完整旋转边角时先设计足够透明留边。
- 图层关键帧只支持 x/y/scale/rotation/opacity，省略的属性延续前值。`linear` 或 `smoothstep`；蒙版进度单独线性插值。音频拍点必须来自实际试听/用户核实，不把波形峰值直接当歌词或情绪重音。

## 完整最小示例

将以下内容保存为 `title.json`，字体路径替换为实际可用字体。所有资源相对路径以 spec 所在目录为基准。

```json
{
  "schema_version": "technique.2.0",
  "input_space": "bt709_sdr",
  "canvas": {"width": 1920, "height": 1080, "fps": 30, "duration": 3, "background_opacity": 0},
  "layers": [{
    "id": "title",
    "source": {"kind": "text", "text": "夏日回忆", "font_path": "your-font.ttf", "font_size_px": 120, "glow_radius_px": 10},
    "keyframes": [{"time": 0, "opacity": 0, "scale": 0.9}, {"time": 2.966666666666667, "opacity": 1, "scale": 1}],
    "easing": "smoothstep"
  }]
}
```

```text
python scripts/technique_tool.py validate --spec title.json
python scripts/technique_tool.py compile --spec title.json --output inspect-title
python scripts/technique_tool.py render --spec title.json --output rendered-title
```

输出目录必须是新目录。compile 生成可审查的 filtergraph、参数和资源哈希；render 另生成无损压缩 QTRLE ARGB `asset.mov`、完整解码/帧数报告。报告默认 `viewed_by_agent=false`、`listened=false`，不自动升级为人工审看。视频静音，保持原有声音审核规则。

## 配方入口

准备参数 JSON，运行 `recipe --name NAME --params PARAMS --output NEW_SPEC`。其输出仍要 validate、render 和审看；输出文件中资源路径转为绝对路径，避免移动 spec 后误引用。配方默认1920×1080/30fps/3秒，可传 `width/height/fps/duration`。配方没有选片或识别音乐的功能。

| name | 必需参数 | 可调参数与用途 |
|---|---|---|
| freeze | source, source_at | 原片某帧保持，时长由 duration 决定 |
| glow-title | text, font_path | font_size_px, color, glow_radius_px；透明文字平滑显现 |
| hollow-title | source, text, font_path | font_size_px；画面乘文字alpha，背景透明 |
| compare-wipe | before, after | angle；线性蒙版从0到1比较两段等长素材 |
| screen-overlay | background, overlay | overlay_in, overlay_speed；黑底烟雾滤色叠加，白底墨迹的白色会保留 |
| grid | sources | rows=columns（1..6），sources数量必须对应；hold_at可逐格设置播放后定格点；contain保留比例 |
| beat-shake | source, cues | amplitude（归一化半画布单位）, burst_seconds；按已核实拍点生成衰减抖动，属预设近似 |
| danmaku | messages, font_path | font_size_px；messages含text/start/duration/y/color，逐条从右向左运动 |
| letterbox | source | bar_fraction（单条黑边占画布高度）, text/font_path/font_size_px；检查字幕是否适合黑边 |

例如 `{"source":"clip.mp4","cues":[0.8,1.6],"width":1280,"height":720,"fps":25,"duration":3}` 可生成 beat-shake。关键帧抖动、标题、弹幕是可编辑的参数设计，视觉效果仍需要选择适合素材的强度。

## 图层可用字段

`source.kind` 为 asset（path,loop）、text（text,font_path,font_size_px,color,stroke_px,stroke_color,glow_radius_px,glow_opacity）、solid（color）。颜色为#RRGGBB。不会静默替换字体、缩小或裁掉超尺寸文字；渲染时不适合画布会报错，需改布局。

图层支持 start/duration/source_in/speed/speed_curve/freeze_at/reverse、crop、x/y/scale/rotation/opacity/keyframes/easing、fade_in/fade_out、mask/key/blend/color。未列出的参数拒绝。crop为源画面0..1的[x,y,width,height]；调色字段复用 [调色接口](color-grading.md)，先校正再套原创外观，不照搬剪映滑杆数值。

蒙版：rect/ellipse 接受 x/y/width/height/rotation；linear 接受 rotation/progress（0..1或time/value数组）；text 接受 text/font_path/font_size_px；asset 接受 path/mode（luma或alpha）/source_in/loop。所有类型可 feather_px/invert。几何羽化为边缘覆盖的近似距离模型，资源蒙版羽化用高斯模糊；两者数值含义不等同于剪映UI。蒙版与源alpha相乘。

key使用RGB colorkey：color/similarity（.01..1）/softness（0..1）。这是颜色键，不是人物分割。blend支持normal/screen/multiply/addition/lighten/darken，在当前SDR编码RGB中运算，不声称线性光合成或与剪映内部色彩处理完全相同。素材必须先明确转换为BT.709 SDR；未知标签的显式声明由实际色彩证据支撑，不可猜测Log/HDR。

资源跨度不足会拒绝；需要循环时显式声明。倒放缓冲源片段，先裁短。单技巧最多64图层、600秒、16,777,216画布像素；复杂作品分段生成。禁止用户任意FFmpeg表达式或Python代码注入参数。

## 接回原有剪辑流程

渲染 → 审看效果首中尾、边缘、文字与动作 → 把 `asset.mov` 作为新派生素材加入当前任务的 inventory → 按 [素材分析](material-analysis.md) 记录真实证据、segment_id及时间区间 → 把派生素材用于主镜头/视觉层 → 正常 validate/export。更新 inventory 后重建 [磁盘记忆](material-memory.md) 的指纹与交接，不能沿用过期缓存。保留 spec/report/源哈希和资源许可，回改从原片及参数重生成。

主计划 schema_version仍为1.0，不混入新的图层字段。完整制作单、必留内容、原声听审、20套LUT、字幕、质量和确认约束继续生效。2.3增加 [逐层原生导出](technique-native.md)：先 native-capabilities，严格拒绝无法表达的操作，明确允许时才局部或整段派生；报告可编辑与已烘焙部分。代码渲染、结构往返、剪映实际界面验收分别记录。

## 继续学习新的教程

按小批读取磁盘学习清单，每段保留源SHA256、时码转录（ASR标未核实）、联系表、实际查看的细节帧和未知项。教程文件名只能用于分组，不能据此虚构学到的内容。每个技巧记录：解决什么问题 → 输入 → 操作顺序 → 带单位参数 → 输出时间与源时间 → 资源/近似边界 → 可观察验证。

子智能体只领取少量明确课程，交接课号、输入指纹、已读范围、已看帧、抽象和未知；主助手核验指纹与证据后合并。知识卡、转录、媒体留磁盘，当前上下文只加载检索命中与待决策片段。新增运行能力必须实际执行脚本并做前向渲染测试。教程原片、截图、完整转录和私人路径不进入公共Skill包。
