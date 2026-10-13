# 第三方组件与素材说明

本项目原创代码和文档采用根目录 [LICENSE](LICENSE) 中的 MIT 许可证。MIT 不替代下列第三方软件、字体、音频、模型或外部运行组件各自的许可证；第三方文件保留原有版权及许可声明。

## 公开版附带字体

公开仓库只附带以下两款未修改的字体文件及完整 SIL Open Font License 1.1。字体的许可、保留名称和再分发条件以相应原始说明为准。

| 字体 | 文件 | 原始版权与许可说明 |
|---|---|---|
| 辰宇落雁 | `assets/fonts/ChenYuluoyan-Thin/ChenYuluoyan-Thin.ttf` | [license.txt](assets/fonts/ChenYuluoyan-Thin/license.txt)：Copyright (c) 2022, Wang, Li-Yu and Liu, Wei-Chen；Reserved Font Names 为“辰宇落雁”和“Chenyuluoyan” |
| 志莽行 | `assets/fonts/ZhiMangXing-Regular/ZhiMangXing-Regular.ttf` | [OFL.txt](assets/fonts/ZhiMangXing-Regular/OFL.txt)：Copyright 2018 The Zhi Mang Xing Project Authors；[原项目](https://github.com/googlefonts/zhimangxing) |

文件编号、字体名称、字形覆盖信息和 SHA256 见 [字体目录](assets/fonts/catalog.json)。开发电脑原有的 23 个字体文件属于本机扩展库，除上表两款外不随公开版分发。其他字体可通过 `font_dirs` 接入；使用、工程随附或再次分发这些字体前，应依据各字体的实际许可。公开仓库不附带 Windows 系统字体。

## 环境音与拟音

下列 5 个 MP3 来源于 BigSoundBank，目录记录其原发布页、作者、CC0 1.0 许可、下载地址、文件哈希和核验信息。详细记录见 [音效目录](assets/sound-library/catalog.json)，许可说明见 [BigSoundBank 许可页](https://bigsoundbank.com/licenses.html) 与 [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)。保留这些来源信息便于追溯，不把库音效描述为用户拍摄现场的原声。

| 包内文件 | 原作者 | 原发布页 |
|---|---|---|
| `assets/sound-library/media/sea-waves.mp3` | DenisChardonnet | [Sea: Waves](https://bigsoundbank.com/sea-waves-s0266.html) |
| `assets/sound-library/media/cicadas.mp3` | Clarisse | [Cicadas](https://bigsoundbank.com/cicadas-s3002.html) |
| `assets/sound-library/media/market-france.mp3` | Joseph SARDIN | [Outdoor Market #1](https://bigsoundbank.com/outdoor-market-1-s2728.html) |
| `assets/sound-library/media/rain-umbrella.mp3` | Pierre SIBANARCO | [Rain Under an Umbrella](https://bigsoundbank.com/rain-under-an-umbrella-s2679.html) |
| `assets/sound-library/media/keyboard.mp3` | Joseph SARDIN | [Computer Keyboard](https://bigsoundbank.com/computer-keyboard-s0229.html) |

这些 MP3 是发布方提供的有损版本，不能称为原始无损录音。是否适合某个镜头仍需实际听审；例如法国集市包含特定语言环境，伞下雨声具有特定录音视角。

## 剪映草稿依赖

`assets/vendor/pyjianyingdraft-0.3.0-py3-none-any.whl` 来自 [aoguai/pyJianYingDraft](https://github.com/aoguai/pyJianYingDraft)，固定提交 `80d521b28049bd81288b5e6ee85de310c3ac8d86`，版本 `0.3.0`，使用 Apache License 2.0。完整许可随附于 [LICENSE-pyJianYingDraft.txt](assets/vendor/LICENSE-pyJianYingDraft.txt)；来源、固定提交与 SHA256 见 [manifest.json](assets/vendor/manifest.json)。本项目的 MIT 许可不重新许可该 wheel。

## 外部运行组件与用户素材

[requirements.txt](requirements.txt) 列出的 NumPy、Pillow、fontTools、faster-whisper 及其传递依赖，安装后仍分别遵循上游许可证。Python、FFmpeg、语音模型及额外下载的运行组件也遵循各自许可；公开源码包不包含这些运行时、模型缓存或安装后的环境。另行分发离线运行包时，应保留实际组件的许可证、来源及对应版本记录，不能直接套用本项目 MIT。

剪映软件、DLL 与其资源不随本项目分发，使用接收电脑已安装的剪映。用户导入的照片、视频、录音、配乐和扩展字体不因本项目采用 MIT 而改变其权利归属或获得新的授权，也不包含在公开仓库内。
# Original color recipes and public benchmark media

The 20 BT.709 SDR creative recipes and their generator are original project assets under the repository MIT license. Official Adobe, Blackmagic Design and FFmpeg documentation is linked as tool-principle research; recipes are not copied commercial presets or exact branded film emulations. No private reference videos or previews are included.

Public benchmark videos retain their individual Commons licenses and creator attribution. The repository distributes download/replay tools and source/attribution manifests, not the video files. Downloaded official transcodes are recorded as such. Source-page metadata and discovery groups are not human-verified visual or speech annotations. See references/benchmark.md and benchmarks/commons-200 when the corpus manifest is included.
