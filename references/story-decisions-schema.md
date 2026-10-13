# 叙事切点 sidecar：证据、保护区与显式时间映射

主助手审看后填写的独立决策文件，**不是 edit-plan**。脚本不看视频、不听音乐、不判断情绪、不修改计划、不导出媒体。通过仅表示结构和声明关系一致，不能证明声明真实。`story-decisions/1`保持兼容；2.3增加`story-decisions/2`，为连续变速和PTS样本提供显式映射。

## 调用与结果

```text
python scripts/story_decisions.py validate decisions.json
python scripts/story_decisions.py suggest decisions.json
python -m unittest discover -s tests -p test_story_decisions.py -v
```

标准库CLI与既有`video_edit.retiming`实现。stdout单个`{ok,code,data}` JSON；失败含message并退出2，成功退出0。API为`video_edit.story_decisions.validate(data)`和`suggest(data)`，兼容CLI模块导入。语义错误抛`Invalid`；CLI也将基本类型、读取和溢出错误报告为`INVALID_SIDECAR`。输入不被修改。

suggest只排序原有候选，结果包含`legal`、带拒绝原因的`rejected`及`selected`。无合法点返回`selected:null / NO_LEGAL_CANDIDATE`；有合法点仍是`REQUIRES_EDITORIAL_REVIEW`。永远`applied_to_plan:false`，不会自动吸附、裁剪或写入主计划。

## 共用字段契约

所有对象拒绝未知字段；以下字段都必须提供，空数组可用。时间全部为有限秒值，不接受布尔冒充数值。ID/说明为非空字符串。

- 根：`schema_version`, `fps`, `assets`, `events`, `shots`, `protected`, `candidates`, `music`, `max_beat_distance`。
- `fps`：桥接计划支持的24/25/30/50/60，是输出帧率。它不是源素材帧率。
- `assets:[{id,duration}]`：真实清单ID与探测出的正时长。示例中的fictional_*及FICTIONAL_TEST_ONLY不得用作真实证据。
- `events:[{id,evidence:[{asset_id,source_start,source_end,review_ref}]}]`：经审看支持的事件/行动—反应单元，ID唯一，至少一个有效源区间。review_ref指向实际回放/转录/视觉证据；脚本不读取引用内容，外部审查必须核验。剧情beat不是音乐拍点。
- `protected:[{asset_id,source_start,source_end,kind,review_ref}]`：kind为semantic/action/reaction。切在严格内部被拒，恰在两端允许；需呼吸/动作余量时由审看者扩展保护区。保护按asset生效，包括同素材复用。
- `candidates:[{id,shot_id,source_time,dramatic_beat_id,review_ref}]`：实际审看后提出的候选，位于镜头源区间严格内部。dramatic_beat_id必须等于镜头event_id，不能填音乐时间；ID唯一。机器不生成或移动候选。
- `music:null`表示无配乐约束；否则为`{asset_id,source_start,source_end,timeline_start,listened_ranges:[{source_start,source_end,review_ref}],beats:[源秒...]}`。音乐固定正常速度，beats严格递增且在选用区间及已试听声明内。拍点检测值不是听审；空beats按无音乐目标处理。
- `max_beat_distance`：候选全片时间与最近已试听音乐拍点允许的最大秒差，≥0。不是自动移镜容差；无配乐/拍点时不使用。

两个版本镜头均包含`shot_id,asset_id,event_id,reaction_to_event_id,source_start,source_end,timeline_start`。源区间须在素材时长内，并被同一event的一条证据完整覆盖。reaction_to_event_id无反应关系时null，有关系时必须等于本镜头event_id；采用保守的同一真实事件约束。时间线起点与输出时长须对齐fps；镜头不重叠，允许空隙，本文件不是完整主轨。

## /1：兼容恒速镜头

根`schema_version:"story-decisions/1"`，镜头额外必需`speed`，范围0.25–4，正向恒速。

```text
output_duration = (source_end-source_start)/speed
candidate_timeline = timeline_start + (candidate.source_time-source_start)/speed
```

旧文件继续执行原有映射；不能把连续曲线、倒放、冻结或未知软件预设作为`speed:1`塞进旧版本。库内[虚构示例](../assets/story-decisions-fictional.json)演示/1。

## /2：明确声明时序模型

根`schema_version:"story-decisions/2"`，镜头用`output_duration`和`time_map`替代`speed`；两者不可混用。输出时长>0且对齐输出帧网格，源区间必须与映射消耗量一致。

### 恒速

```json
{"kind":"constant","speed":2}
```

范围仍为0.25–4；`source_end-source_start == output_duration*speed`。

### 连续速度曲线

```json
{"kind":"speed_curve","knots":[{"time":0,"speed":1},{"time":5,"speed":3}]}
```

time是镜头内**输出秒**；speed是源秒/输出秒，范围0.1–10。首点time=0，末点time=output_duration；中间点可在子帧时间，时刻严格递增。速度在输出时间上分段线性，积分得到源消耗，再用既有`retiming.output_time`解析逆映射求候选输出秒。上述5秒曲线消耗10源秒；输出局部3秒消耗4.8源秒，不能用平均速度2代替。

此模型与`technique.2.0`速度曲线一致。它不声称与剪映未知预设插值完全相同；原生后端能否保留相同曲线另查实际能力。源时间以source_start为局部原点。曲线不能表示零速冻结、负速或多值倒放。

### 显式PTS样本对

```json
{"kind":"pts","review_ref":"实际解码或渲染映射记录",
 "points":[{"source_time":10,"output_time":0},
           {"source_time":10.033,"output_time":0.04},
           {"source_time":10.1,"output_time":0.08},
           {"source_time":20,"output_time":5}]}
```

这是示意数据，不是真实审看证据。source_time为与inventory/source_in相同原点的源呈现秒，不是帧序号；output_time为镜头内输出秒。样本两轴均严格递增；首/末点对应source_start/0与source_end/output_duration，末点可作为已知区间终点记录。全部输出样本对齐fps。记录解码PTS时先扣除原始起始PTS，不能忽略视频edit-list或非零起点。

候选源时间必须有一个实际声明的PTS样本对，**不在样本之间插值**，不由平均帧率发明VFR帧。允许有意仅提供与候选相关的抽样记录；缺记录即拒绝，不代替连续曲线。脚本仅检查声明结构，PTS真实性和解码所见须由审查者确认。倒放、定格、重复帧构成非单调或多值关系时，先生成并审看独立衍生素材，使用新ID及新时基；本sidecar明确拒绝冒充支持。

## 选择、保护与音乐

```text
candidate_timeline = shot.timeline_start + map_source_to_output(candidate.source_time)
music_beat_timeline = music.timeline_start + beat_source - music.source_start
```

只在原候选不变时检查输出帧对齐（帧单位浮点容差1e-7）、源保护区和拍点窗口。保护区始终在原源坐标，不受镜头变速或复用改变。拒绝原因包含NOT_FRAME_ALIGNED/PROTECTED_INTERIOR/OUTSIDE_BEAT_WINDOW。合法点依次按拍点距离、时间线时间、候选ID排序，无配乐时用后两项。这是可重复的技术排序，不是审美评分。

保护只禁止**切断区间内部**，不保证整段被保留：在保护区开始处选出点仍可能删掉后面整段。必须另检must_keep、场景功能和切后覆盖，不能把此工具当成语义/连续性全面验收。

## 桥接主计划与技巧资产

原`plan-format.md`的恒速主镜头仍用`id/source_in/start/duration/speed`；不把sidecar新增字段直接塞进严格schema。/1和/2 constant经审看接受后才可映射：asset_id→id，接受的源入点→source_in，speed→speed，源范围除speed→duration，再按新序列重排start。

曲线或PTS映射先通过真实技巧编译/其他已验后端生成并审看素材；该衍生资源加入inventory后，主计划引用新ID和输出时基。保留原源映射与哈希，不能对衍生文件继续套旧source_start/end。selected不包含保留哪一侧、下一镜是谁、声音如何延续等编辑决定。

任何镜头时长/位置、音乐入点或技法内部时序变化后，重算全部受影响时间，再运行suggest与主计划validate。原需求确认、review.evidence、must_keep、声音审核、字幕/画幅检查仍必需；变速原声静音。`beat_cut`标签不能替代真实参数/渲染证据。

## 验证边界

机器检查数值边界、ID关系、证据声明覆盖、映射消耗/端点、帧网格、保护区、试听声明覆盖、同事件反应关系、排序和无解回退。人或有视听能力的模型仍须确认事实、真正审看、语义、反应语境、音乐、可读性及最终声画效果。

24项测试用虚构材料验证恒速兼容、连续速度积分、VFR/PTS样本、错误曲线/时基、保护与无解回退等行为；它们不代表真实片段已审看。原始书籍、教程、完整转录及个人路径不进入发布包。
