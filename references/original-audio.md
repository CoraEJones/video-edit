# 原声严格听审与默认静音

默认 `shots[].audio_gain=0`，省略也是静音。绝大多数素材背景声不进入成片，不能因为有音轨就自动保留。变速镜头一律静音，不使用 `atempo` 留下变速声。需要关键讲话时，选正常速度镜头单独承接；慢动作、延时和快速走马灯用已经选好的音乐/必要音效组织声音。

只有两类原声可以主动保留：清晰且串联故事的关键话语 `key_speech`；经过明确选择、音质好且特别有故事价值的同期声 `story_sound`，例如一次真实而重要的笑声/钟声。普通脚步、车辆、人群、风声和流水声不因“真实”就必留。录音含重风噪、持续杂音、爆音、失真、远而含混的讲话或无关嘈杂时静音。`important_speech` 不能替代听审，也不会单独打开原声。

## 先试听，再做保留决定

1. 从原素材取包含实际保留区间和 J/L 延伸的 PCM 样本。听开始、中间和结尾，确认内容、清晰度、噪声、失真、突变和故事用途。不能用转录成功、波形或音量常数证明音质合格。
2. 对有价值但带轻噪的关键话语，可尝试一次轻度 `afftdn`：`noise_reduction` 为 6–12 dB，默认 8。先生成结果，再实际试听同一区间；确认没有水声感、金属感、吞字或其他损伤。没有可用滤镜时报真实错误，不声称已经降噪。其他音效噪声较差时直接弃用，不为填满声音而反复修复。
3. 只有实际听完的版本清晰合格才填写 `audio_review.status="approved"`。填上 `denoise` 不等于已试听、已改善或已批准。结果仍差就 `audio_gain=0`，用**已核实**的关键文字/字幕承接；未听清、未核实的自动转录不能当作事实。必要时保留“内容待核实”，不虚构人物话语。
4. 没有音频试听能力时保持静音，并报告关键话语听审仍待完成；不编造 evidence、approved 或主观评分。程序只验证记录是否完整、区间是否覆盖，不能替人证明实际听过。

内部可调用 `video_edit.audio_policy.render_review_audio(source, output, source_start, source_end, cfg, denoise=None)` 生成 WAV；`source` 可为原视频或完整原声 WAV，`output` 必须是不同的 `.wav` 文件。函数返回 `status=needs_listening`，从不自动批准。可选降噪参数示例 `{"filter":"afftdn","noise_reduction":8}`。所有中间声音解码和处理为 48 kHz 双声道 `pcm_s16le`，没有 MP3/AAC 中间压缩；统一采样率与 16 位精度是工作格式，不是原录音逐字节无损。原素材完整副本另行保留。最终 MP4 封装时才编码 AAC。

## 写入计划

```json
{
  "audio_gain": 0.65,
  "audio_lead": 0.2,
  "audio_tail": 0.3,
  "audio_review": {
    "status": "approved",
    "purpose": "key_speech",
    "source_start": 4.8,
    "source_end": 8.3,
    "quality": "clear",
    "evidence": "填写实际试听文件或工具引用、原素材时码、实际听审结论",
    "reason": "填写这句话如何串联本片故事",
    "denoise": {
      "filter": "afftdn",
      "noise_reduction": 8,
      "evidence": "填写已实际听过的处理后样本文件及清晰度/处理痕迹结论"
    }
  }
}
```

示例仅是格式，文字占位和时间不能作为真实审核依据。不降噪时省略整个 `denoise`。`source_start/source_end` 是**原素材秒数**，必须覆盖实际输出声段和前后延伸。实际 lead 受镜头起点与源入点限制，tail 受成片末尾和原音轨末尾限制。修改入出点或增加延伸后重新计算；超出已经听过的区间就补充试听。

旧计划正 `audio_gain` 缺审核记录会返回可处理错误 `ORIGINAL_AUDIO_REVIEW_REQUIRED`，要求重审或静音。缺省增益按新规则静音；不能给旧计划批量补 approved。变速正增益报 `ORIGINAL_AUDIO_SPEED`。分屏暂不输出原声，正增益报错，避免计划声称保留而实际丢失；关键讲话应安排正常速度主轨镜头。

导出再次执行相同校验，防止绕过 `validate`。`audio-plan.json.original_audio` 记录每个主轨镜头的静音/保留、来源区间、审核声明、实际执行滤镜。`processing_verified=true` 只证明处理程序成功，不代替听审结论。只有实际输出的 `key_speech` 声音和旁白触发配乐/环境音闪避；静音画面的字幕和 `important_speech` 标记不会无故压低音乐。

用户选“只保留原声”也必须过以上审核；它只是关闭外加音乐和音效，不能放宽音质标准。若原声都不合格，说明当前初稿为静音并保留已核实文字，不偷偷补配乐。整体混音仍需试听爆音、句尾完整、衔接和可懂度。
