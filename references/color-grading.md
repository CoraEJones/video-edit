# 调色：先校正，再统一镜头，最后选创意外观

20种选择来自用户已授权整合的“整理20种视频LUT调色方案”任务，保留原始
原创配方与可再生算法。名称描述色调方向，不保证还原某种胶片或相机。
不得把套 LUT 的完成等同于曝光、白平衡、肤色与相邻镜头匹配已经合格。

## 支持范围与诚实交付

- MP4 与 FFmpeg 预览共用 `input_color_filter`，执行逐镜头校正与创意 LUT。
- 输入目标为 **BT.709 SDR 编码 RGB**；不是线性 RGB LUT，也不是 Log 转换 LUT。
- 已检测 PQ/HLG 时，先执行已有 HDR→SDR tone map，再校正与 look。需要已知
  primaries/matrix，输出为 SDR；这会改变 HDR 高光，不能宣称保留 HDR 成片。
- 对未知标签，先核对相机设置或前序技术转换，再明确填写
  `input_space: "bt709_sdr"`。它是操作者声明，不会转换或证明输入正确。
  无标签照片也需声明；sRGB/广色域/ICC 照片如需严格色彩一致，应先进行受管理的
  输入转换。不得为了通过校验随意填写。
- 已知 Log、非 BT.709 primaries/matrix 或其他传递函数直接拒绝。需先正确进行
  技术转换并提供对应元数据；不能把创意 LUT 称为“Log还原”。
- 剪映原生可编辑后端尚未验证 LUT/校正参数支持。带有效调色的 editable 计划
  明确返回 `COLOR_NATIVE_UNSUPPORTED`，不会偷偷烘焙低画质素材或丢弃效果。
  可以导出 MP4，或生成 CUBE 后人工在剪映应用并检查。人工编辑结果不属于本版
  自动参数一致性的保证范围。
- 未设置调色，或完全关闭调色时，既有源文件及 HDR 处理路径保持原行为。

## 选择目录

| 编号 | look | 名称 | 关注点 |
|---|---|---|---|
| 1 | natural_vivid | 自然通透 | 浪花、白云高光层次 |
| 2 | airy_daylight | 日系空气感 | 抬黑后是否灰雾 |
| 3 | golden_hour | 金色暖阳 | 肤色是否过黄 |
| 4 | teal_orange | 青橙电影 | 暗部青色是否污染肤色 |
| 5 | nordic_cool | 北欧冷调 | 白墙是否过蓝 |
| 6 | pastel_pink | 柔粉奶油 | 脸部和白色物体的粉偏 |
| 7 | vintage_fade | 褪色旧时光 | 抬黑与压白是否符合回忆段落 |
| 8 | warm_print | 暖调胶片感 | 仅色调，不添加颗粒 |
| 9 | cool_slide | 清冷反转片感 | 蓝绿过饱和 |
| 10 | olive_cinema | 橄榄电影 | 树叶黄绿偏移 |
| 11 | mediterranean | 地中海青蓝 | 海水颜色和白浪 |
| 12 | emerald_forest | 翡翠森林 | 绿色噪点和叶片层次 |
| 13 | cocoa_brown | 可可棕调 | 蓝绿色损失与肤色 |
| 14 | moody_blue | 深蓝情绪 | 暗部是否压死 |
| 15 | violet_neon | 紫青霓虹 | 夜景色偏与肤色 |
| 16 | bleach_bypass | 漂白旁路感 | 低饱和强反差下的细节 |
| 17 | cross_process | 交叉冲洗感 | 中性色偏移属于风格 |
| 18 | sepia_memory | 怀旧棕褐 | 与回忆语义是否相符 |
| 19 | monochrome_crisp | 经典高反差黑白 | 头发、衣服暗部 |
| 20 | monochrome_matte | 柔雾黑白 | 抬黑后人物和背景分离 |

可用 `python scripts/color_luts.py catalog` 查看目录，`python scripts/color_luts.py export-luts --out OUTPUT --strength 1` 导出20个友好名称的CUBE。

准确参数与建议强度见 `assets/color/recipes.json`。暖色保护使用色相掩码，也可能
影响沙滩、木头，并非人脸识别。黑白方案在强度1时完全去色；低于1会混回原颜色。

## 计划字段与继承

```json
{
  "color": {"look": "warm_print", "strength": 0.65},
  "shots": [
    {"id": "a", "index": 1, "color": {"exposure_ev": 0.3, "white_balance": [1.02, 1, 0.97]}},
    {"id": "b", "index": 2, "color": {"look": 19, "strength": 1}},
    {"id": "c", "index": 3, "color": {"enabled": false}}
  ]
}
```

示例省略普通时间线必需字段。顶层 `color` 为默认；`shots[].color`、
`visual_layers[].color` 覆盖对应字段。分屏 panel 依次继承顶层、对应主镜头、
自身的 `color`。`white_balance` 三通道作为一个完整数组覆盖。
`enabled:false` 关闭该片段全部校正和外观；需要重新启用时明确 `enabled:true`。

| 字段 | 默认 | 范围 / 语义 |
|---|---|---|
| look | none | 编号1..20、slug 或 none |
| strength | 1 | 0..1，仅控制创意 look |
| exposure_ev | 0 | -3..3，BT.709 解码到线性光后乘2^EV |
| contrast | 1 | 0.5..1.5，编码RGB以0.5为中心 |
| gamma | 1 | 0.5..2，编码RGB的1/gamma幂 |
| saturation | 1 | 0..2，围绕BT.709加权亮度调整 |
| white_balance | [1,1,1] | 每通道0.8..1.25的线性RGB增益 |
| enabled | true | false完全关闭 |
| input_space | null | 未知标签输入需核对后声明bt709_sdr |

这些数值 **不是剪映滑块刻度**。白平衡是有限的RGB增益修正，不提供Kelvin色温
校准或自动灰卡识别。曝光修正无法恢复已经剪切的高光。处理顺序：

> 必要HDR→SDR → 线性曝光与RGB增益 → gamma → 对比 → 饱和 → 创意look混合。

`strength:0` 保留基础校正，`look:"none"` 也保留基础校正。每个完整设置组合
按需生成33³ CUBE，以 tetrahedral 插值应用。缓存清单记录生成器代码、配方、
设置与 CUBE SHA-256；读取缓存时核对哈希，损坏后重建。
`color-report.json` 记录实际片段设置、输入标签、tone map与LUT哈希。
滤镜只引用交付目录的 ASCII 哈希相对路径，避免 Windows 盘符冒号转义问题。

## 审片与验证

1. 选同场参考镜头，查看暗部、高光、中性白与肤色；先校正各镜头，再并排比较。
2. 针对故事准备少量 look 候选，在人物、天空、绿色和低光画面上统一强度试片。
3. 连续播放相邻镜头，检查曝光/冷暖跳变。风格改变应有段落或情绪依据。
4. 在目标观看环境检查完整成片。示波器/数值只能辅助；不得把全自动配色称为
   已完成专业肤色匹配、色卡校准或审美验收。
5. `tests/test_color.py` 覆盖整合前数值基准、identity、强度0保留校正、混合、
   黑白、继承、非法值、未知/Log/HDR输入限制、缓存损坏、源文件不变，以及真实
   FFmpeg LUT/透明度、不同镜头校正、预览与最终MP4一致性。
   设置 `VIDEO_EDIT_FFMPEG` / `VIDEO_EDIT_FFPROBE` 启用实际渲染检查。

合成测试只证明数学与工程路径；200段真实素材上的调色效果仍需盲评和人工审片。
