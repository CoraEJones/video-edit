"""Beginner request wizard; no processing or file writes before confirmation."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
from .common import EditError, resolve_path
from .intake import DEFAULTS, confirm_request, inspect_request, suggest_output, summary_lines


def show(cfg, request=None):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    try:
        root = tk.Tk(); root.withdraw()
    except tk.TclError as exc:
        raise EditError('DESKTOP_UNAVAILABLE', '图形向导未能启动。请在本机桌面运行“开始选素材.cmd”，或在对话中补齐需求。', {'reason': str(exc)})
    result = deepcopy(DEFAULTS)
    if cfg.get('delivery_mode') in ('mp4', 'editable'):
        result['delivery_mode'] = cfg['delivery_mode']
    result.update(deepcopy(request or {}))
    result.pop('confirmation', None)
    media = result.get('media_dir')
    check = inspect_request({'media_dir': media}) if media else None
    if not media or any(p['field'] == 'media_dir' for p in check['invalid_paths']):
        media = filedialog.askdirectory(parent=root, title='第一步：选择放视频和照片的文件夹', mustexist=True)
        if not media:
            root.destroy(); return None
    result['media_dir'] = str(resolve_path(media))
    if not result.get('output_dir'):
        result['output_dir'] = suggest_output(result, cfg) or ''
    result.update(schema_version='1.0', entry_mode='wizard')
    root.title('回忆剪辑 · 制作向导'); root.geometry('860x770'); root.minsize(740, 660)
    root.configure(bg='#f4f6fa')
    style = ttk.Style(root); style.theme_use('clam')
    style.configure('.', font=('Microsoft YaHei UI', 14), background='#f4f6fa')
    style.configure('TButton', padding=(14, 10), font=('Microsoft YaHei UI', 14))
    style.configure('TCheckbutton', padding=6)
    style.configure('Title.TLabel', font=('Microsoft YaHei UI', 23, 'bold'), foreground='#153348')
    style.configure('Note.TLabel', font=('Microsoft YaHei UI', 12), foreground='#526477')
    page = tk.IntVar(value=0); widgets = {}; completed = [None]
    shell = ttk.Frame(root, padding=26); shell.pack(fill='both', expand=True)
    progress = ttk.Label(shell, style='Note.TLabel'); progress.pack(anchor='w')
    title = ttk.Label(shell, style='Title.TLabel'); title.pack(anchor='w', pady=(10, 12))
    viewport = ttk.Frame(shell); viewport.pack(fill='both', expand=True)
    canvas = tk.Canvas(viewport, bg='#f4f6fa', highlightthickness=0)
    scroll = ttk.Scrollbar(viewport, orient='vertical', command=canvas.yview)
    scroll.pack(side='right', fill='y'); canvas.pack(side='left', fill='both', expand=True)
    canvas.configure(yscrollcommand=scroll.set)
    body = ttk.Frame(canvas); window = canvas.create_window((0, 0), window=body, anchor='nw')
    body.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window, width=event.width))
    root.bind('<MouseWheel>', lambda event: canvas.yview_scroll(int(-event.delta / 120), 'units'))
    nav = ttk.Frame(shell); nav.pack(fill='x', pady=(14, 0))

    def note(text, parent=None):
        ttk.Label(parent or body, text=text, style='Note.TLabel', wraplength=750).pack(anchor='w', pady=9)

    def entry(key, label, parent=None):
        host = parent or body
        ttk.Label(host, text=label, wraplength=750).pack(anchor='w', pady=(9, 5))
        var = tk.StringVar(value=str(result.get(key) or '')); widgets[key] = var
        ttk.Entry(host, textvariable=var).pack(fill='x', ipady=7)
        return var

    def choice(key, label, values, parent=None, onchange=None):
        host = parent or body
        ttk.Label(host, text=label, wraplength=750).pack(anchor='w', pady=(10, 5))
        labels = {value: text for text, value in values}; current = result.get(key)
        if current not in labels: labels[current] = str(current)
        var = tk.StringVar(value=labels[current]); inverse = {text: value for value, text in labels.items()}
        box = ttk.Combobox(host, state='readonly', textvariable=var, values=list(labels.values()), font=('Microsoft YaHei UI', 14))
        box.pack(fill='x', ipady=6); widgets[key] = lambda: inverse[var.get()]
        if onchange: box.bind('<<ComboboxSelected>>', lambda event: onchange())
        return box

    def value(key):
        item = widgets[key]
        return item() if callable(item) else item.get()

    def checkbox(key, label, onchange=None):
        var = tk.BooleanVar(value=bool(result.get(key))); widgets[key] = var
        control = ttk.Checkbutton(body, text=label, variable=var, command=onchange)
        control.pack(anchor='w', pady=8)
        return control

    def save_page():
        for key in widgets: result[key] = value(key)
        if page.get() == 1:
            raw = result['target_seconds']
            if raw == 'custom': raw = result.get('custom_seconds', '')
            if raw == 'auto': result['target_seconds'] = None
            else:
                try:
                    seconds = float(raw)
                    if not 10 <= seconds <= 7200: raise ValueError()
                    result['target_seconds'] = seconds
                except (TypeError, ValueError):
                    messagebox.showinfo('请填写时长', '填写 10 到 7200 秒，或选择“由助手推荐”。', parent=root); return False
        if page.get() == 4 and result['music'] == '使用我自己的音乐' and not result.get('music_file'):
            messagebox.showinfo('请选择音乐', '选择音乐文件，或改选自动配乐。', parent=root); return False
        return True

    def choose_folder(key):
        selected = filedialog.askdirectory(parent=root, title='选择素材文件夹' if key == 'media_dir' else '选择交付文件夹', mustexist=True)
        if selected: widgets[key].set(selected)

    def draw():
        canvas.yview_moveto(0); widgets.clear()
        for child in body.winfo_children(): child.destroy()
        n = page.get(); progress.config(text=f'第 {n + 1} / 9 步 · 已给出的答案会保留，随时可返回修改')
        back.config(state='normal' if n else 'disabled')
        next_button.config(text='确认方案并开始制作' if n == 8 else '下一步 →')
        if n == 0:
            title.config(text='想保留可编辑的工程吗？')
            choice('delivery_mode', '选择交付方式', [('只要 MP4 成片 · 无需剪映', 'mp4'), ('MP4＋可编辑工程 · 需要本地剪映', 'editable')])
            note('Codex 和 DeepSeek Harness 只需一个。需要工程时，会先扫描本地剪映；已经安装就直接使用。')
            entry('media_dir', '素材文件夹')
            ttk.Button(body, text='重新选择素材…', command=lambda: choose_folder('media_dir')).pack(anchor='w', pady=7)
            entry('output_dir', '输出位置（建议值，最后确认后才使用）')
            ttk.Button(body, text='选择其他输出位置…', command=lambda: choose_folder('output_dir')).pack(anchor='w', pady=7)
            note('可以填写尚未创建的交付文件夹。选择输出位置不会开始处理素材。')
        elif n == 1:
            title.config(text='你希望视频大约多长？')
            raw = result['target_seconds']
            if raw is None: result['target_seconds'] = 'auto'
            elif raw not in (30, 60, 90, 180, 300, 'auto', 'custom'):
                result['custom_seconds'] = str(raw); result['target_seconds'] = 'custom'
            custom = ttk.Frame(body)
            def duration_toggle():
                if value('target_seconds') == 'custom': custom.pack(fill='x')
                else: custom.pack_forget()
            choice('target_seconds', '目标时长', [('30 秒 · 精彩小片段', 30), ('1 分钟', 60), ('1 分半钟', 90), ('3 分钟', 180), ('5 分钟', 300), ('由助手推荐', 'auto'), ('填写秒数', 'custom')], onchange=duration_toggle)
            result.setdefault('custom_seconds', '120'); entry('custom_seconds', '秒数', custom); duration_toggle()
            note('这是期望时长，默认可为重要片刻适度调整；不会擅自降低原片画质。')
        elif n == 2:
            title.config(text='这段回忆，想讲什么？')
            choice('category', '素材类型', [(x, x) for x in ('旅行', '家庭', '活动纪念', '由助手推荐')])
            entry('theme', '主题（一句话即可；也可写“由助手推荐”）')
            choice('rhythm', '风格与节奏', [(x, x) for x in ('温馨舒缓', '轻快活泼', '安静纪实', '有电影感', '由助手推荐')])
            note('会先看真实素材再组织故事；地点、人物关系和经历不会凭画面或文件名编造。')
        elif n == 3:
            title.config(text='要字幕和配音吗？')
            subtitle_area, voice_area = ttk.Frame(body), ttk.Frame(body)
            def subtitle_toggle():
                if value('subtitles'): subtitle_area.pack(fill='x', after=subtitle_button)
                else: subtitle_area.pack_forget()
            def voice_toggle():
                if value('voiceover'): voice_area.pack(fill='x')
                else: voice_area.pack_forget()
            subtitle_button = checkbox('subtitles', '显示字幕：故事文字和重要讲话', subtitle_toggle)
            choice('subtitle_language', '字幕语言', [(x, x) for x in ('简体中文', '中英双语', '英文', '中西双语', '保持讲话原语言', '由助手推荐')], subtitle_area); subtitle_toggle()
            checkbox('voiceover', '需要配音：把故事文案读出来', voice_toggle)
            choice('voice_gender', '声音偏好', [(x, x) for x in ('女声', '男声', '由助手推荐')], voice_area); voice_toggle()
            note('字幕默认清晰简洁、中文优先。配音关闭时无需选声音；重要现场讲话仍须通过声音审核。')
        elif n == 4:
            title.config(text='在哪里看？喜欢什么音乐？')
            choice('aspect', '画面比例', [(x, x) for x in ('横屏 16:9', '竖屏 9:16', '方形 1:1', '由助手推荐')])
            music_area = ttk.Frame(body)
            def music_toggle():
                if value('music') == '使用我自己的音乐': music_area.pack(fill='x')
                else: music_area.pack_forget()
            choice('music', '音乐方式', [(x, x) for x in ('自动配乐', '使用我自己的音乐', '只保留原声')], onchange=music_toggle)
            selected = ttk.Label(music_area, text=Path(result['music_file']).name if result.get('music_file') else '尚未选择', style='Note.TLabel'); selected.pack(anchor='w', pady=9)
            def choose_music():
                path = filedialog.askopenfilename(parent=root, title='选择音乐', filetypes=[('音频', '*.mp3 *.wav *.m4a *.flac'), ('所有文件', '*.*')])
                if path: result['music_file'] = path; selected.config(text=Path(path).name)
            ttk.Button(music_area, text='选择音乐文件…', command=choose_music).pack(anchor='w'); music_toggle()
            note('自动配乐会按故事选择少量、自然衔接的音乐。“只保留原声”也会严格审核可听性。')
        elif n == 5:
            title.config(text='标题和原声，怎样处理？')
            choice('title_mode', '是否接受艺术字图片', [('接受：艺术字优先，失败时用字体排版', 'art_preferred'), ('只用字体库：文字内容继续可编辑', 'fonts_only')])
            note('艺术字图片的字形不能直接改成其他文字；位置、大小和显示时间仍可调整。')
            choice('text_style', '文字风格', [(x, x) for x in ('自动搭配', '清爽现代', '温暖手写', '安静电影感', '洒脱书法')])
            choice('audio_policy', '原声保留方式', [('严格审核：不清楚就静音，变速静音（推荐）', 'strict'), ('仅保留清楚的关键讲话，变速静音', 'key_speech_only'), ('全部原声静音', 'mute_all')])
            note('关键讲话可先轻度降噪；仍听不清就静音，用核实后的字幕承接。')
        elif n == 6:
            title.config(text='怎样开场，怎样收尾？')
            choice('opening_style', '片头偏好', [('精彩快闪＋上下黑幕揭题，灵活调整（推荐）', 'highlight_reveal'), ('照片和视频横向／竖向走马灯', 'photo_carousel'), ('由助手按故事推荐', 'story_based')])
            choice('ending_style', '结尾偏好', [('慢下来、呼应前文、无字留白（推荐）', 'slow_echo'), ('有意味的长镜头与声音余韵', 'linger'), ('由助手按故事推荐', 'story_based')])
            note('首尾与中段形成节奏差异；模板会按素材和故事调整。')
        elif n == 7:
            title.config(text='补充故事背景和必留内容')
            entry('name', '作品名称'); entry('context', '地点、人物关系或故事背景（没有补充可留空）')
            entry('must_keep', '一定要保留或不想出现的人、场景、片段（可留空）')
            selected = ttk.Label(body, text=f'已选 {len(result["must_keep_files"])} 个必留文件', style='Note.TLabel'); selected.pack(anchor='w', pady=9)
            def choose_keep():
                paths = filedialog.askopenfilenames(parent=root, title='选择必留素材', initialdir=result['media_dir'])
                if paths: result['must_keep_files'] = list(paths); selected.config(text=f'已选 {len(paths)} 个必留文件')
            def clear_keep():
                result['must_keep_files'] = []; selected.config(text='已选 0 个必留文件')
            ttk.Button(body, text='直接挑选必留素材…', command=choose_keep).pack(anchor='w', pady=4)
            ttk.Button(body, text='清空必留文件', command=clear_keep).pack(anchor='w', pady=4)
        else:
            title.config(text='确认这份制作方案')
            note('以下包含你的选择和助手推荐值。确认后才开始分析、剪辑和导出；可返回修改或取消。')
            for line in summary_lines(result): note(line)
            note('原始素材保留，剪辑中保持画质，仅最终 MP4 有损编码。后续可用日常语言要求修改。')

    def move(delta):
        if not save_page(): return
        if page.get() == 8 and delta > 0:
            try:
                completed[0] = confirm_request(result, True, method='wizard_confirm_button', cfg=cfg)
            except EditError as exc:
                details = exc.details
                issues = [q['label'] for q in details.get('questions', [])]
                issues += [p['reason'] for p in details.get('invalid_paths', []) + details.get('invalid_fields', [])]
                messagebox.showinfo('请先补齐方案', '\n'.join(issues) or str(exc), parent=root); return
            root.destroy(); return
        page.set(page.get() + delta); draw()

    ttk.Button(nav, text='取消', command=root.destroy).pack(side='left')
    back = ttk.Button(nav, text='← 上一步', command=lambda: move(-1)); back.pack(side='left', padx=10)
    next_button = ttk.Button(nav, text='下一步 →', command=lambda: move(1)); next_button.pack(side='right')
    root.protocol('WM_DELETE_WINDOW', root.destroy)
    draw(); root.deiconify(); root.lift(); root.mainloop()
    return completed[0]
