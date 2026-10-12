# 素材局部密集看帧工具

当粗略联系表不足以确认对焦、动作接点、短暂表情、主体遮挡或画面变化时，运行 `scripts/review_frames.py`。它只把真实源帧与时码整理出来；主助手或视觉子智能体仍须实际打开图片查看。没有视觉模型时保留待审核状态，不能用清晰度数值或文件名替代观看。

## 调用

沿用已配置的 Python 环境、FFmpeg、FFprobe 和 Pillow。`--config` 与 `video_tool.py` 共用配置，可省略以使用默认配置或 `VIDEO_EDIT_CONFIG`。

密集抽样（默认最多每秒 2 帧）：

```powershell
python scripts/review_frames.py --inventory "作品/analysis/inventory.json" --id "v0123456789ab" --start 12 --end 18 --fps 4 --output "作品/review/v0123456789ab-12-18"
```

确实需要逐帧核对某个短动作时：

```powershell
python scripts/review_frames.py --inventory "作品/analysis/inventory.json" --id "v0123456789ab" --start 12 --end 14 --every-frame --output "作品/review/v0123456789ab-12-14-all"
```

静态照片只输出一张图片，省略时间和帧率参数：

```powershell
python scripts/review_frames.py --inventory "作品/analysis/inventory.json" --id "vabcdef012345" --output "作品/review/photo-detail"
```

## 时间与覆盖范围

- 视频必须明确给出源素材秒数区间 `[start, end)`，单次最多 120 秒。超出文件时长会报错，不自动缩短。
- `--fps` 是相邻被选中真实帧的最大抽样速率；第一张为区间中可用的第一帧。它不会重采样补帧，也不保证均匀时刻恰好存在源帧。`--fps` 与 `--every-frame` 互斥。
- `--every-frame` 输出指定区间中解码器返回的每一帧，VFR 也保留原始 PTS，不按平均帧率伪造等间隔画面。JSON 保存整数 `pts`、`time_base` 和相对于容器起始时间的 `source_time`；图片标签使用 `HH:MM:SS.mmm`，以 JSON 精确时间为准。
- 默认最多 240 帧，可通过 `--max-frames` 调整为 1–600。超限会以 `FRAME_LIMIT_EXCEEDED` 失败，并留下 `INCOMPLETE.json`；该目录不能用作完整覆盖证据。缩短区间或降低抽样速率并使用新的输出目录重试。
- 长视频按相邻区间分批处理。只有实际输出并查看了所有相关区间的全部帧，才可声称这些区间已逐帧看过。提取完成不等于视觉审核完成。

## 输出与交给视觉助手的内容

成功时 stdout 只有一个 JSON，包含 `ok`、`manifest`、`mode`、`frame_count`、`contact_sheets`、`visual_review_completed: false` 与 `warnings`。进度写 stderr。错误也输出单个 JSON，`ok: false` 并返回非零退出码。

新输出目录包含 `frames/frame_*.jpg`、每页最多 12 张的 `contact_*.jpg` 和 `frame-review.json`。传给视觉助手：素材 id、请求区间、manifest 和实际图片；让它引用具体 `source_time`，标记已看的图片、事实、推测与不确定项。判断运动方向或抖动至少连看相邻帧，必要时播放对应源区间；单帧不能证明运动稳定或人物情绪。

默认导出图片最长边 960 像素且不放大，联系表只是导航。对焦与细节疑点用 `--native-size` 在新目录提取源分辨率图片并查看对应帧（仍为 JPEG 证据，原片不变），或回看原片；不能仅凭联系表给出全分辨率画质合格结论。时间戳里的 `source_time` 是源片位置，不是剪好视频的时间线位置。

工具不修改 inventory、剪辑计划或原始素材；输出目录必须不存在，避免覆盖已有成果。若 inventory 记录了指纹且素材已改变，将返回 `SOURCE_CHANGED`。动画图片会明确拒绝，不能把第一帧当作整段检查。
