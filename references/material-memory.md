# 大素材库的磁盘记忆与交接

素材信息的真源是任务目录中的文件与索引，不能依靠某一轮上下文记住全部视频，也不能假设子智能体记得上一批。`scripts/material_memory.py` 是确定性索引/交接工具，不自带模型、不自动审看。

## 主助手保留什么

上下文中只保留：已确认制作需求摘要、当前故事方向、阶段状态、关键事实/不确定项、下一步任务，以及少量检索结果。完整 inventory、转录、联系表、区间观察、原声声明和历史版本留在磁盘。事实共享文件 `JOB/memory/facts.json` 记录 `{id,text,source,confidence}`；身份、时序与人物关系只引用用户说明或可核验证据。尚未写入的文件不能称为已保存记忆。

`memory/index.sqlite3` 存素材/区间索引和批次租约；`memory/records/<id>.json` 存完整分析输入；`memory/submissions` 是工作者写入区，`memory/results/<batch>.json` 仅由ingest保存已核验交接；`memory/segments` 保存单区间详情。包内result_path与previous_result_path不同，不能直接覆盖canonical前版。检索返回短摘要和detail_path，密集帧证据按需读，避免单个候选挤满上下文。路径和索引可重新生成；已有审看结果只有输入指纹一致时才复用。模型上下文压缩或重启后先读 request、memory status、workflow-state 与当前故事文件，再检索所需片段，不重塞整库。

## 分批、领取、交接

在 analyze 后初始化；通常每批 8–12 条，长转录/复杂动作再缩小。批次包默认最多 14,000 字符，这不是精确 token 数；为当前模型和宿主留足工具结果与图片预算。包过大时工具先移除转录摘要，保留每条分配编号和记录路径；必要信息仍超预算就报错，必须缩批，不能静默漏掉素材。

```text
python scripts/material_memory.py init --job JOB --batch-size 12
python scripts/material_memory.py status --job JOB
python scripts/material_memory.py claim --job JOB --worker worker-1
python scripts/material_memory.py packet --job JOB --batch BATCH_ID --worker worker-1
python scripts/material_memory.py ingest --job JOB --batch BATCH_ID --worker worker-1 --result RESULT.json
python scripts/material_memory.py query --job JOB --query "海边 反应" --limit 8 --max-chars 12000
python scripts/material_memory.py compile --job JOB
python scripts/material_memory.py reopen --job JOB --batch BATCH_ID
```

主助手用宿主真实委派工具传递批次包或其路径、相关审看指南、输出路径。不要给每个子任务整个库，也不要为每条视频建立一个长期子智能体。复用少量工作者，完成一批再领取下一批；实际并发服从宿主上限。无委派工具时由主助手领取并逐批执行，同样持久化结果。

领取是 SQLite 事务；不同工作者不会同时领取同一批。默认租约 30 分钟，长任务主动按预计耗时设置 `--lease-seconds`；过期批次可重新领取，旧工作者不能提交。租约过期不等于审看失败或素材不好。子任务失败先保存已做证据与未知项，主助手缩批/接管，不无限重试。

## 结果合同

返回 `schema_version="material-analysis-1.0"`、`time_basis="source_seconds"`、`assets`，每项必须包含分配的 `id`、包内 `input_fingerprint`、真实 `status`、`coverage` 和 `segments`；观察/解释/未知分开。格式细节见 material-analysis.md。所有分配项都要有处置状态，不能只返回喜欢的镜头。

`reviewed` 需要实际看过的文件与时码。不能看图返回 `blocked_visual`，没有听音能力保留 `audio_reviewed=false`。联系表只能证明初筛声明；候选精审使用密集帧或短片回放，并记录范围。交接工具检查编号、指纹、文件、区间和范围一致性，不能证明模型真的看过/听过。

ingest 拒绝漏项、越权项、重复区间编号、变化后的输入、无效证据和未审候选。通过后索引可按观察、标签和故事用途检索。无候选时，metadata_navigation 仅用于找到待审记录，不能升级为画面事实。compile 生成 material-analysis.json，未审/失败素材仍保留状态；不能因为合并成功就把全库标为 reviewed。

## 故事与最终校验

故事岗位读取当前事实表与少量检索候选，按缺口追加检索，例如动作结果、人物反应、建立环境、收尾。记录每段真正使用的 segment_id，跨批人物/地点身份由主助手统一核实。

新任务的计划使用 `review.analysis_path` 关联合并结果，入选镜头填 `segment_id`。严格校验要求选段处于该候选和已审范围内；单张帧或稀疏联系表不能证明整个动态片段稳定。用户必留瞬间用 request.must_keep_ranges 的 asset_id/source_start/source_end 记录，检查完整源区间而非仅文件出现过。

初筛完成后需要追加候选或精审，用 reopen 显式重开该批，再领取。原结果通过previous_result_path可读，新结果保留历史审看归属并只追加实际完成的观察；旧版本自动归档。重开期间该批候选暂不参与检索，避免把待修订内容当最终结论；有效运行租约不能被抢占。无需重复抽帧或改inventory伪造输入变化。

仅换标题无需重新审整库；素材/取帧/ASR配置变化后重新 analyze/init，相关批次失效。修改故事只重新检索与编排；换音乐需复查节拍映射、声音和受影响剪口；色彩变化只重渲染与颜色复核。保留旧交付，主助手唯一修改最终计划。
