from pathlib import Path
r=Path(__file__).resolve().parent/'app/src/main/assets'
desktop=r.parents[4]/'Данные'
p=r/'index.html'
s=(desktop/'templates/index.html').read_text(encoding='utf-8-sig')
s=s.replace('href="/static/style.css"','href="/static/style.css"><link rel="stylesheet" href="/static/android.css"')
s=s.replace('<script>window.TRIP_TOKEN={{ token|tojson }};</script>','<script src="/static/android.js"></script>')
s=s.replace('<label class="upload">Загрузить подпись<input id="signature-upload" type="file" accept="image/png,image/jpeg" hidden></label>','<button type="button" id="signature-pick">Загрузить подпись</button>')
for kind in ('request','report','memo','pack'):
    marker=f'<button type="button" data-print="{kind}"'
    share=f'<button type="button" data-share="{kind}">Поделиться PDF</button>'
    if kind!='pack':
        share+=f'<button type="button" data-share-signed="{kind}" hidden>Поделиться с подписью</button>'
    s=s.replace(marker,share+marker)
s=s.replace('<label class="upload">＋ Добавить чеки / файлы<input id="upload" type="file" multiple hidden></label>','<button type="button" id="add-receipts">＋ Добавить чеки</button>')
s=s.replace('Можно просто положить файлы в папку командировки и нажать «Обновить из папки». Для общего PDF подходят PDF, JPG, PNG, WEBP, BMP и TIFF. Остальные файлы сохраняются и доступны для скачивания.','Выберите фото чеков, скриншоты или PDF в системном окне. Вложения хранятся в карточке поездки.')
s=s.replace('Данные сохраняются локально · Папка «Печать» находится рядом с EXE','Данные сохраняются на этом телефоне')
s=s.replace('● Локально на этом компьютере','● Локально на телефоне')
s=s.replace('Если диалог печати не появился, откройте PDF и нажмите Ctrl+P или значок принтера.','Можно распечатать PDF, сохранить его в файлы или отправить.')
s=s.replace('<button type="button" id="preview-close">','<button type="button" id="preview-share">Поделиться</button><button type="button" id="preview-export">Сохранить PDF</button><button type="button" id="preview-close">')
s=s.replace('После сохранения появится отдельная папка командировки.','Чеки и документы хранятся в карточке поездки.')
s=s.replace('<div class="spinner"></div><span>Подготавливаю…</span>',
    '<div id="busy-spinner" class="busy-spinner"><div class="spinner"></div><span>Подготавливаю…</span></div>'
    '<div id="pack-progress-box" hidden><div class="pack-progress-title"><strong>Подготовка PDF</strong>'
    '<output id="pack-progress-percent">0%</output></div><progress id="pack-progress" max="100" value="0" '
    'aria-label="Прогресс подготовки PDF"></progress><span id="pack-progress-status" role="status">Проверяем файлы</span></div>')
p.write_text(s,encoding='utf-8')
(r/'static/style.css').write_bytes((desktop/'static/style.css').read_bytes())
layout=(desktop/'static/signature-layout.js').read_text(encoding='utf-8')
layout=layout.replace("return '/api/trips/'+key+'/preview-page?path='+encodeURIComponent(path)+'&page='+page;",
    "return '/page.jpg?id='+encodeURIComponent(key)+'&path='+encodeURIComponent(path)+'&n='+page;")
(r/'static/signature-layout.js').write_text(layout,encoding='utf-8')
p=r/'static/app.js'
s=(desktop/'static/app.js').read_text(encoding='utf-8-sig')
start=s.index('async function api('); end=s.index('\n',start)
s=s[:start]+"async function api(path,options={}){return androidRequest(path,options);}"+s[end:]
s=s.replace('let savedSidebar=false;', 'let savedSidebar=true;').replace("savedSidebar=localStorage.getItem('J701.sidebarCollapsed')==='true'","savedSidebar=localStorage.getItem('J701.sidebarCollapsed')!=='false'")
start=s.index("$('#signature-upload').onchange="); end=s.index('\n});',start)+len('\n});')
s=s[:start]+s[end:]
s=s.replace("data.print_folder||'После сохранения появится отдельная папка командировки.'","'Чеки и документы хранятся в карточке поездки.'").replace("$('#folder-path').textContent=saved.print_folder;","")
start=s.index('    frame.onload='); end=s.index('\n}',start)
s=s[:start]+"""    ['print','share','export'].forEach(mode=>$('#preview-'+mode).onclick=()=>androidDocument(mode,path));
    if(shareNow){androidDocument('share',path);return;}
    if(printNow){androidDocument('print',path);return;}
    frame.src='/preview?id='+encodeURIComponent(current.id)+'&path='+encodeURIComponent(path);
    dialog.showModal();"""+s[end:]
lines=s.splitlines()
lines=[line for line in lines if not line.startswith(("function printPreview()", "$('#preview-print').onclick=", "$('#shutdown').onclick=", "$('#folder').onclick=", "$('#upload').onchange=", "window.addEventListener('beforeunload'"))]
s='\n'.join(lines)
s=s[:s.index('let lifecycleStream=')]
s=s.replace("const a=el('a',{href:fileURL(result.path),target:'_blank',rel:'noopener',text:'Открыть PDF и напечатать'});","const a=el('button',{type:'button',text:'Поделиться PDF'});a.onclick=()=>androidDocument('share',result.path);")
s=s.replace("text:'Скачать PDF'","text:'Сохранить PDF'").replace("В окне PDF нажмите значок принтера или Ctrl+P. Выберите A4; для бланков используйте фактический размер. Число копий каждой формы уже учтено при сборке.","Число копий уже учтено при сборке. PDF можно сохранить или отправить.")
s=s.replace("fill(await api('/api/trips/'+trip.id));", "fill(await api('/api/trips/'+trip.id));if(innerWidth<=760)setSidebarCollapsed(true);")
s=s.replace("fileRows=[];fill(await api('/api/defaults'));activate('trip')", "fileRows=[];fill(await api('/api/defaults'));activate('trip');if(innerWidth<=760)setSidebarCollapsed(true)")
p.write_text(s+'\nconfigureAndroid();\n',encoding='utf-8')
