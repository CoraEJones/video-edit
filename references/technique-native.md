# 技巧图层与剪映工程（2.3）

先明确故事用途，再把教程步骤展开为 [technique.2.0](technique-language.md) 图层。代码渲染和原生导出使用同一份参数，但支持范围不同。不要把生成工程或加密往返成功写成已经在剪映播放、编辑、保存或导出。

```text
python scripts/technique_tool.py --config MACHINE native-capabilities --spec SPEC
python scripts/technique_tool.py --config MACHINE export-jianying --spec SPEC --output NEW_FOLDER --name 技巧测试
python scripts/technique_tool.py --config MACHINE export-jianying --spec SPEC --output NEW_FOLDER --allow-derived
```

先读 `native-capabilities` 的逐层报告。默认严格拒绝无法原生表示的操作；只有明确允许派生素材时才使用 `--allow-derived`。输出不得覆盖已有工程；不修改剪映首页或用户工程注册表。依赖和隔离进程要求与 [运行说明](runtime.md) 相同。

| 操作 | 导出表达与复核重点 |
| --- | --- |
| 图层、素材裁入裁出、恒速 | 独立轨道，打包完整原件并校验哈希，保留原生源区间和速度 |
| 位置、缩放、旋转、透明度 | 可编辑关键帧；平滑插值和淡化乘积按项目帧率采样成线性关键帧，不能称原生贝塞尔曲线 |
| 矩形、椭圆、静态线性蒙版 | 使用本机真实缓存资源并打包；缺资源拒绝，不虚构 effect ID。椭圆范围、线性方向需界面对照 |
| 文字与描边 | 独立可编辑文字及打包字体；像素字号到编辑器单位为近似映射，字形布局需界面校准 |
| 定格 | 解码指定源帧为 PNG，保留原视频和源秒证据；图像图层可编辑，定格选择已烘焙 |
| 发光、文字/资源蒙版、颜色键、裁切、连续变速、倒放、调色 | 未校准的局部操作渲染为独立透明 MOV，仍保留其他原片图层与原生变换；报告列出已烘焙操作 |
| 依赖下层像素的混合 | 只有实际混合枚举和对应缓存资源存在时才原生绑定。缺失时可能必须合成整个技巧片段，报告为 `derived_composition` |
| 非方形像素 | 先明确显示比例，派生层中按 SAR 归一化；不把 coded width 当显示宽度 |

导出报告区分 `native_layers`、`hybrid_layers`、`derived_composition`。检查每轨 `baked_layer_operations`、文字是否可改、素材源区间、资源路径和完整原片哈希。派生层内部参数仍在 spec 中，修改须从原片重渲染；不能声称可在剪映的特效面板继续修改发光半径等已烘焙参数。

## 照片颜色入口

JPEG 的 YUV 矩阵标签不等于 RGB 原色。不能为了让校验通过，把 BT.601 矩阵直接改标签成 BT.709。

```text
python scripts/technique_tool.py normalize-image --source PHOTO --input-space embedded_icc --output NEW.png
python scripts/technique_tool.py normalize-image --source PHOTO --input-space srgb --output NEW.png
```

`embedded_icc` 必须有实际 ICC；CMYK 必须通过 ICC 转换。`srgb` 是调用者明确的解释，不是自动核实相机色彩。入口处理 EXIF 显示方向、sRGB 解码和 BT.709 编码，输出新的 PNG 与 `.color.json`，保留 alpha、原件哈希和转换声明，不覆盖原件。此功能不能代替视频 Log/HDR 转换或放宽未知输入检查。

## 验收边界

对每个技巧保存源身份、参数、代码首中尾帧、解码结果、原生路线及未知项。用相同素材区间和项目帧率在剪映实际打开、调一个参数、保存、重新读取并导出对照；比较主体/时间/透明边缘/文本及混合，允许误差应预先说明。未完成界面对照就保留 `ui_verified=false`。特定 Siri 音色、专有转场、自动人物分割和商业歌曲不因教程提到就变成内置功能。

主计划1.0的故事、确认、声音和画质流程保持不变。技巧工程是测试与复用入口；完整影片继续走 `video_tool.py`，主计划不接受技巧接口的新字段。
