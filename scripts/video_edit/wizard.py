"""Local desktop request wizard; cancellation never starts processing."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import uuid
from .common import EditError, write

DEFAULTS = {'target_seconds':90,'category':'旅行','theme':'把值得记住的片刻留住','rhythm':'温馨舒缓',
            'subtitle_language':'简体中文','subtitles':True,'voiceover':False,'voice_gender':'女声',
            'aspect':'横屏 16:9','music':'自动配乐','music_file':None,'must_keep':'','must_keep_files':[],
            'context':'','name':'我的回忆','text_style':'自动搭配','allow_select':True,'duration_policy':'soft',
            'quality_policy':'preserve_source'}

def show(cfg):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    try:root=tk.Tk();root.withdraw()
    except tk.TclError as exc:
        raise EditError('DESKTOP_UNAVAILABLE','图形向导未能启动。请在本机桌面运行“开始选素材.cmd”；受限环境需要允许访问本机窗口。',{'reason':str(exc)})
    # The first visible interaction is the native folder chooser, never a path textbox.
    folder=filedialog.askdirectory(parent=root,title='第一步：请选择放视频和照片的文件夹',mustexist=True)
    if not folder:
        root.destroy();return None
    result=DEFAULTS.copy();result['media_dir']=str(Path(folder).resolve());result['must_keep_files']=[]
    root.title('回忆剪辑 · 制作向导');root.geometry('820x690');root.minsize(720,620)
    root.configure(bg='#f4f6fa')
    style=ttk.Style(root);style.theme_use('clam')
    style.configure('.',font=('Microsoft YaHei UI',14),background='#f4f6fa')
    style.configure('TButton',padding=(16,10),font=('Microsoft YaHei UI',14))
    style.configure('TRadiobutton',padding=6)
    style.configure('TCheckbutton',padding=6)
    style.configure('Title.TLabel',font=('Microsoft YaHei UI',23,'bold'),foreground='#153348')
    style.configure('Note.TLabel',font=('Microsoft YaHei UI',12),foreground='#526477')
    page=tk.IntVar(value=0);widgets={};finished=[False]
    shell=ttk.Frame(root,padding=28);shell.pack(fill='both',expand=True)
    progress=ttk.Label(shell,style='Note.TLabel');progress.pack(anchor='w')
    title=ttk.Label(shell,style='Title.TLabel');title.pack(anchor='w',pady=(10,12))
    viewport=ttk.Frame(shell);viewport.pack(fill='both',expand=True)
    canvas=tk.Canvas(viewport,bg='#f4f6fa',highlightthickness=0)
    scrollbar=ttk.Scrollbar(viewport,orient='vertical',command=canvas.yview)
    scrollbar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
    canvas.configure(yscrollcommand=scrollbar.set)
    body=ttk.Frame(canvas);body_window=canvas.create_window((0,0),window=body,anchor='nw')
    body.bind('<Configure>',lambda event:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>',lambda event:canvas.itemconfigure(body_window,width=event.width))
    root.bind('<MouseWheel>',lambda event:canvas.yview_scroll(int(-event.delta/120),'units'))
    nav=ttk.Frame(shell);nav.pack(fill='x',pady=(14,0))
    def cancel():
        root.destroy()
    def radio(key,choices,parent=None,onchange=None):
        var=tk.StringVar(value=str(result[key]));widgets[key]=var
        for label,value in choices:
            ttk.Radiobutton(parent or body,text=label,value=str(value),variable=var,command=onchange).pack(anchor='w',fill='x')
        return var
    def entry(key,label,parent=None):
        host=parent or body
        ttk.Label(host,text=label,wraplength=730).pack(anchor='w',pady=(9,5))
        var=tk.StringVar(value=str(result[key]));widgets[key]=var
        ttk.Entry(host,textvariable=var).pack(fill='x',ipady=7)
    def optional(key,label,build):
        var=tk.BooleanVar(value=bool(result.get(key,False)));widgets[key]=var
        holder=ttk.Frame(body);holder.pack(fill='x')
        area=ttk.Frame(holder)
        def toggle():
            if var.get():area.pack(fill='x',pady=(0,12))
            else:area.pack_forget()
        ttk.Checkbutton(holder,text=label,variable=var,command=toggle).pack(anchor='w',pady=9)
        build(area);toggle()
    def note(text):
        ttk.Label(body,text=text,style='Note.TLabel',wraplength=730).pack(anchor='w',pady=9)
    def save_page():
        for k,var in widgets.items():
            result[k]=var.get()
        if page.get()==0:
            raw=result['target_seconds']
            if raw=='custom':raw=result.get('custom_seconds','')
            if raw=='auto':result['target_seconds']=None
            else:
                try:
                    value=float(raw)
                    if not 10<=value<=7200:raise ValueError()
                    result['target_seconds']=value
                except ValueError:
                    messagebox.showinfo('请填写时长','请填写 10 到 7200 之间的秒数，或者选“由助手推荐”。',parent=root);return False
        if page.get()==4 and result['music']=='使用我自己的音乐' and not result.get('music_file'):
            messagebox.showinfo('请选择音乐','点击“选择音乐文件”，或者改选自动配乐。',parent=root);return False
        return True
    def draw():
        canvas.yview_moveto(0)
        widgets.clear()
        for w in body.winfo_children():w.destroy()
        n=page.get();progress.config(text=f'第 {n+1} / 7 步   ·   随时可以返回修改')
        back.config(state='normal' if n>0 else 'disabled')
        next_button.config(text='开始制作' if n==6 else '下一步  →')
        if n==0:
            title.config(text='你希望视频大约多长？')
            note('时长是期望值。重要的片刻可以适度多留一点。')
            value=result['target_seconds']
            if value is None:result['target_seconds']='auto'
            elif value not in (30,60,90,180,300,'30','60','90','180','300'):
                result['custom_seconds']=str(value);result['target_seconds']='custom'
            else:result['target_seconds']=str(int(float(value)))
            custom=ttk.Frame(body)
            def custom_toggle():
                if widgets['target_seconds'].get()=='custom':custom.pack(fill='x')
                else:custom.pack_forget()
            radio('target_seconds',[('30 秒 · 精彩小片段',30),('1 分钟',60),('1 分半钟',90),('3 分钟',180),('5 分钟',300),('由助手推荐','auto'),('自己填写秒数','custom')],onchange=custom_toggle)
            result.setdefault('custom_seconds','120');entry('custom_seconds','填写秒数',custom);custom_toggle()
        elif n==1:
            title.config(text='这段回忆，是什么感觉？')
            radio('category',[(x,x) for x in ('旅行','家庭','活动纪念')])
            optional('_custom_theme','我想自己描述主题',lambda host:entry('theme','用一句话说说主题',host))
            ttk.Label(body,text='喜欢的节奏').pack(anchor='w',pady=(10,0))
            radio('rhythm',[(x,x) for x in ('温馨舒缓','轻快活泼','安静纪实','有电影感','由助手推荐')])
        elif n==2:
            title.config(text='字幕用什么语言？')
            radio('subtitle_language',[(x,x) for x in ('简体中文','中英双语','英文','中西双语','保持讲话原语言')])
            note('下一页可以关闭字幕。中英或中西双语会保留成独立文字轨道。')
        elif n==3:
            title.config(text='故事要读出来吗？')
            for key,label in [('voiceover','需要配音，把故事文案读出来'),('subtitles','显示字幕，包括故事文字和重要讲话')]:
                var=tk.BooleanVar(value=bool(result[key]));widgets[key]=var
                ttk.Checkbutton(body,text=label,variable=var).pack(anchor='w',pady=12)
            note('会先写故事文案。不开配音也能做出完整视频；现场的重要讲话仍会保留。')
            voice_area=ttk.Frame(body)
            radio('voice_gender',[('女声','女声'),('男声','男声')],voice_area)
            def voice_toggle(*args):
                if widgets['voiceover'].get():voice_area.pack(fill='x')
                else:voice_area.pack_forget()
            widgets['voiceover'].trace_add('write',voice_toggle);voice_toggle()
            optional('_custom_style','我想自己挑文字风格',lambda host:radio('text_style',[(s,s) for s in ('自动搭配','清爽现代','温暖手写','安静电影感','洒脱书法')],host))
            note('第一版使用电脑已安装的离线声音。缺少所需声音时会说明，不能冒充已配音。')
        elif n==4:
            title.config(text='在哪里看？喜欢什么音乐？')
            radio('aspect',[(x,x) for x in ('横屏 16:9','竖屏 9:16','方形 1:1')])
            ttk.Label(body,text='配乐').pack(anchor='w',pady=(10,0))
            music_area=ttk.Frame(body)
            def music_toggle():
                if widgets['music'].get()=='使用我自己的音乐':music_area.pack(fill='x')
                else:music_area.pack_forget()
            radio('music',[(x,x) for x in ('自动配乐','使用我自己的音乐','只保留原声')],onchange=music_toggle)
            music_label=ttk.Label(music_area,text=Path(result['music_file']).name if result.get('music_file') else '尚未选择音乐',style='Note.TLabel');music_label.pack(anchor='w')
            def choose_music():
                p=filedialog.askopenfilename(parent=root,title='选择一首音乐',filetypes=[('音频','*.mp3 *.wav *.m4a *.flac'),('所有文件','*.*')])
                if p:result['music_file']=p;widgets['music'].set('使用我自己的音乐');music_label.config(text=Path(p).name)
            ttk.Button(music_area,text='选择音乐文件…',command=choose_music).pack(anchor='w',pady=8);music_toggle()
        elif n==5:
            title.config(text='有没有一定要留下的回忆？')
            note('没有特别要求，直接点“下一步”即可。')
            optional('_custom_name','我想给作品起名字',lambda host:entry('name','作品名称',host))
            optional('_has_context','我想补充一些背景',lambda host:entry('context','地点、人物关系或故事背景',host))
            def keep_area(host):
                entry('must_keep','一定要留下的人、场景或片段',host)
                chosen=ttk.Label(host,text=f'已选 {len(result["must_keep_files"])} 个必留文件',style='Note.TLabel');chosen.pack(anchor='w',pady=10)
                def choose_keep():
                    paths=filedialog.askopenfilenames(parent=root,title='选择必须保留的素材',initialdir=folder)
                    if paths:result['must_keep_files']=list(paths);chosen.config(text=f'已选 {len(paths)} 个必留文件')
                ttk.Button(host,text='直接挑选必留文件…',command=choose_keep).pack(anchor='w')
            optional('_has_keep','我有一定要留下的内容',keep_area)
            note('人物描述不够明确时，助手会结合画面核实。不会仅凭文件名猜测人物和经历。')
        else:
            title.config(text='准备好了，开始留住回忆')
            duration='由助手推荐' if result['target_seconds'] is None else f'约 {result["target_seconds"]:g} 秒'
            summary_name=result['name'] if result.get('_custom_name') else DEFAULTS['name']
            summary_theme=result['theme'] if result.get('_custom_theme') else DEFAULTS['theme']
            lines=[f'素材：{folder}',f'作品：{summary_name}',f'时长：{duration}',f'主题：{summary_theme}',f'感觉：{result["rhythm"]}  ·  {result["aspect"]}',
                   f'字幕：{result["subtitle_language"] if result["subtitles"] else "关闭"}  ·  配音：{"开启" if result["voiceover"] else "关闭"}',f'音乐：{result["music"]}']
            note('\n\n'.join(lines));note('原始素材会保留。完成后可用日常语言告诉助手“缩短一些”“多留家人的镜头”等。')
    def move(delta):
        if not save_page():return
        if page.get()==6 and delta>0:
            finished[0]=True;root.destroy();return
        page.set(page.get()+delta);draw()
    ttk.Button(nav,text='取消',command=cancel).pack(side='left')
    back=ttk.Button(nav,text='←  上一步',command=lambda:move(-1));back.pack(side='left',padx=12)
    next_button=ttk.Button(nav,text='下一步  →',command=lambda:move(1));next_button.pack(side='right')
    root.protocol('WM_DELETE_WINDOW',cancel);draw();root.deiconify();root.lift();root.mainloop()
    if not finished[0]:return None
    for toggle,field in [('_custom_theme','theme'),('_custom_name','name'),('_has_context','context'),('_has_keep','must_keep'),('_custom_style','text_style')]:
        if not result.get(toggle):result[field]=DEFAULTS[field]
    if not result.get('_has_keep'):result['must_keep_files']=[]
    base=Path(cfg['output_root']) if cfg.get('output_root') else Path(folder).parent/'剪辑成品'
    result['output_dir']=str(base/(datetime.now().strftime('%Y%m%d-%H%M%S')+'_'+uuid.uuid4().hex[:6]))
    result['schema_version']='1.0'
    return result
