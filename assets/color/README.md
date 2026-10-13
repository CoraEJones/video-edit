# 原创 SDR 调色配方

`recipes.json` 保存用户“整理20种视频LUT调色方案”任务的20套原创配方；
`research_sources.json` 记录该任务查阅的官方技术资料；`reference_samples.json`
是整合前从原始 `LUT_lab_20261013/grade.py` 导出的数值基准及其源代码 SHA-256。
它们是原创创意色调，不是商业 LUT、相机 Log 转换、真实胶片测量或降噪工具。

生成器位于 `scripts/video_edit/color.py`。默认在交付目录按需生成33³ CUBE，
每个组合包含基础校正、外观和强度；缓存键包括设置、配方和生成器代码哈希。
不在 Git 中提交全部 CUBE 大文件。

生成可手工导入剪映的完整20套默认强度 LUT：

```powershell
$env:PYTHONPATH = 'scripts'
python -m video_edit.color export-luts --out 'output/luts' --strength 1
```

该命令生成普通 CUBE 与 `catalog.json`，不会安装或应用剪映效果。
在剪映中仍需选择正确输入空间、手工导入并检查实际预览/导出。详细流程见
`references/color-grading.md`。CUBE 内容属于本仓库现有许可范围。
