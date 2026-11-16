"""Local browser application for travel paperwork. Run: python app.py"""
import argparse
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import uuid
import webbrowser
from base64 import b64encode
from datetime import datetime
from pathlib import Path
from io import BytesIO
from urllib.parse import urlsplit
from flask import Flask, jsonify, request, send_file, render_template, Response
from PIL import Image
from werkzeug.exceptions import HTTPException
from domain import CATEGORIES, default_trip, normalize, totals, calculate, apply_plan_defaults
from printing import form, combine, DEFAULT_PLACEMENT
from signature import save_signature
from app_paths import ASSETS, DATA, PRINT

BASE=ASSETS
SUPPORTED={'.pdf','.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff'}
DOCS={'request':'01_Заявка.pdf','report':'02_Авансовый_отчет.pdf','memo':'03_Служебная_записка.pdf','details':'04_Расшифровка_расходов.pdf'}
SIGNED={kind:name.removesuffix('.pdf')+'_с_подписью.pdf' for kind,name in DOCS.items() if kind!='details'}
FORM_FILES={name:(kind,signed) for variants,signed in ((DOCS,False),(SIGNED,True)) for kind,name in variants.items()}
SIGNATURE='.signature.png'

def create_app(data_root=None, print_root=None):
    app=Flask(__name__)
    app.config['MAX_CONTENT_LENGTH']=200*1024*1024
    app.config['CLOSED_EVENT']=threading.Event()
    app.config['CLOSE_SOURCE']='unknown'
    store=Path(data_root or DATA/'Командировки').resolve()
    paper=Path(print_root or PRINT).resolve()
    trash=store.parent/'Корзина'
    store.mkdir(parents=True,exist_ok=True); paper.mkdir(parents=True,exist_ok=True)
    lock=threading.RLock()
    token=secrets.token_urlsafe(32)
    app.config['MOBILE_TOKEN']=token
    layout_path=store.parent/'signature-layouts.json'

    def layouts():
        if not layout_path.exists():
            return {}
        return json.loads(layout_path.read_text(encoding='utf-8'))

    def active_layouts(trip):
        return {kind:placement for kind,placement in layouts().items() if trip.get('include_'+kind)}

    def atomic(path, data):
        temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        temp.replace(path)

    def trip_path(key):
        if not re.fullmatch(r'[a-f0-9]{32}',key): raise ValueError('Неизвестная командировка.')
        return store/(key+'.json')

    def load(key):
        path=trip_path(key)
        if not path.exists(): raise ValueError('Командировка не найдена.')
        trip=json.loads(path.read_text(encoding='utf-8'))
        # Existing manually entered expenses retain their meaning.
        trip.setdefault('issued_from_plan',False)
        trip.setdefault('daily_from_plan',False)
        trip.setdefault('name','')
        trip.setdefault('report_date','')
        trip.setdefault('memo_date','')
        if (trip.get('generated_revision')==trip['revision'] and (paper/trip['folder']/SIGNATURE).is_file()
                and trip.get('generated_signature_layouts',{})!=active_layouts(trip)):
            trip.pop('generated_revision',None)
        return trip

    def trip_dir(trip):
        path=(paper/trip['folder']).resolve()
        if not path.is_relative_to(paper): raise ValueError('Недопустимая папка.')
        path.mkdir(exist_ok=True)
        (path/'Чеки').mkdir(exist_ok=True)
        (path/'Документы').mkdir(exist_ok=True)
        return path

    def safe_file(trip, relative):
        path=(trip_dir(trip)/relative).resolve()
        if not path.is_relative_to(trip_dir(trip)) or path.name.startswith('.') or not path.is_file():
            raise ValueError('Файл не найден или недоступен.')
        return path

    def files(trip):
        root=trip_dir(trip)
        result=[]
        for path in sorted(root.rglob('*')):
            if not path.is_file() or path.name.startswith('.') or not path.resolve().is_relative_to(root): continue
            relative=path.relative_to(root).as_posix()
            if relative.startswith('Предпросмотр/'): continue
            # Old generated forms are never offered if disabled or stale.
            generated=path.parent==root/'Документы' and path.name in FORM_FILES
            kind,signed=FORM_FILES[path.name] if generated else (None,False)
            if generated and (not trip.get('include_'+kind) or trip.get('generated_revision')!=trip['revision'] or
                              (signed and not (root/SIGNATURE).is_file())): continue
            if path.name.startswith('Комплект_'): continue
            result.append(dict(path=relative,name=path.name,size=path.stat().st_size,
                supported=path.suffix.lower() in SUPPORTED,generated=generated,kind=kind,signed=signed))
        return sorted(result,key=lambda item:not item['generated'])

    def response_trip(trip):
        folder=trip_dir(trip)
        signature=folder/SIGNATURE
        thumbnail=None
        if signature.is_file():
            try:
                with Image.open(signature) as preview:
                    preview.thumbnail((300, 140), Image.Resampling.LANCZOS)
                    buffer=BytesIO()
                    preview.save(buffer,format='PNG')
                    thumbnail='data:image/png;base64,'+b64encode(buffer.getvalue()).decode('ascii')
            except OSError:
                pass
        return dict(**trip,totals=totals(trip),files=files(trip),print_folder=str(folder),
                    has_signature=signature.is_file(),signature_thumbnail=thumbnail)

    @app.before_request
    def local_only():
        if request.host.split(':')[0] not in ('127.0.0.1','localhost','[::1]'):
            return jsonify(error='Доступ только с этого компьютера.'),403
        if request.method in ('POST','PUT','DELETE'):
            origin=request.headers.get('Origin')
            if origin and urlsplit(origin).netloc!=request.host:
                return jsonify(error='Недопустимый источник запроса.'),403
            if not secrets.compare_digest(request.headers.get('X-Trip-Token',''),token):
                return jsonify(error='Обновите страницу приложения.'),403

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['Cache-Control']='no-store'
        return response

    @app.errorhandler(Exception)
    def error(exc):
        if isinstance(exc,HTTPException): return jsonify(error=exc.description),exc.code
        if isinstance(exc,ValueError): return jsonify(error=str(exc)),400
        app.logger.exception('Ошибка приложения')
        return jsonify(error='Не удалось выполнить действие: '+str(exc)),500

    @app.get('/')
    def index(): return render_template('index.html',token=token)

    @app.get('/api/health')
    def health(): return jsonify(app='TripAssistant',version=3,root=str(DATA),frozen=bool(getattr(sys,'frozen',False)),tray=bool(app.config.get('TRAY_ICON') and app.config['TRAY_ICON'].visible),animation_frames=len(app.config['TRAY_ANIMATION'].frames) if app.config.get('TRAY_ANIMATION') else 0,animation_ticks=app.config['TRAY_ANIMATION'].ticks if app.config.get('TRAY_ANIMATION') else 0)

    @app.post('/api/shutdown')
    def shutdown():
        callback=app.config.get('STOP_SERVER')
        if callback is None: return jsonify(error='Этот способ запуска не поддерживает остановку. Запускайте Командировки.py.'),503
        timer=threading.Timer(.3,callback,args=('browser',));timer.daemon=True;timer.start()
        return jsonify(stopping=True)

    @app.get('/api/lifecycle')
    def lifecycle():
        closed=app.config['CLOSED_EVENT']
        def events():
            yield 'event: state\ndata: {"state":"running"}\n\n'
            while not closed.wait(10):
                yield ': keepalive\n\n'
            data=json.dumps({'state':'closed','source':app.config['CLOSE_SOURCE']})
            yield 'event: state\ndata: '+data+'\n\n'
        return Response(events(),mimetype='text/event-stream',headers={'X-Accel-Buffering':'no'})

    @app.get('/api/trips')
    def all_trips():
        result=[]
        with lock:
            for path in store.glob('*.json'):
                if path.stem in ('defaults','history'): continue
                trip=json.loads(path.read_text(encoding='utf-8'))
                result.append({**{k:trip[k] for k in ('id','city','start','end','employee','updated')},'name':trip.get('name','')})
        return jsonify(sorted(result,key=lambda x:x['updated'],reverse=True))

    @app.get('/api/defaults')
    def defaults():
        trip=default_trip()
        if (store/'defaults.json').exists(): trip.update(json.loads((store/'defaults.json').read_text(encoding='utf-8')))
        return jsonify(trip)

    def suggestions():
        result={'cities':[], 'purposes':['участия в партнерской конференции','выезда на объект клиента']}
        def add(group,value):
            if value and value.casefold() not in {v.casefold() for v in result[group]}:
                result[group].append(value)
        history=store/'history.json'
        if history.exists():
            for group,values in json.loads(history.read_text(encoding='utf-8')).items():
                if group in result:
                    for value in values: add(group,value)
        for path in store.glob('*.json'):
            if path.stem in ('defaults','history'): continue
            trip=json.loads(path.read_text(encoding='utf-8'))
            add('cities',trip.get('city',''));add('purposes',trip.get('purpose',''))
        return result

    @app.get('/api/suggestions')
    def get_suggestions():
        with lock: return jsonify(suggestions())

    @app.post('/api/calculate')
    def calculator():
        return jsonify(value=str(calculate((request.get_json() or {}).get('expression',''))))

    @app.post('/api/estimate')
    def estimate():
        data=request.get_json() or {}
        values={}; errors={}
        def amount(key,expression):
            try: values[key]=str(calculate(expression)); return values[key]
            except ValueError as exc: errors[key]=str(exc); return '0'
        trip=default_trip()
        trip['issued_from_plan']=bool(data.get('issued_from_plan',False))
        trip['daily_from_plan']=bool(data.get('daily_from_plan',False))
        trip['issued']=amount('issued','0' if trip['issued_from_plan'] else data.get('issued','0'))
        trip['planned']={k:amount('planned_'+k,data.get('planned',{}).get(k,'0')) for k in CATEGORIES}
        trip['expenses']=[]
        for i,row in enumerate(data.get('expenses',[])[:1000]):
            category=row.get('category','other')
            if category not in CATEGORIES: raise ValueError('Неизвестный вид расхода.')
            expression=trip['planned']['daily'] if trip['daily_from_plan'] and category=='daily' and row.get('quick') else row.get('amount','0')
            trip['expenses'].append(dict(category=category,quick=bool(row.get('quick')),amount=amount('expense_'+str(i),expression)))
        apply_plan_defaults(trip)
        values['issued']=trip['issued']
        for i,row in enumerate(trip['expenses']):
            values['expense_'+str(i)]=str(calculate(row['amount']))
        amount('memo_amount',data.get('memo_amount','0'))
        return jsonify(totals=totals(trip),values=values,errors=errors)

    @app.get('/api/trips/<key>')
    def get_trip(key):
        with lock: return jsonify(response_trip(load(key)))

    @app.post('/api/trips/<key>/rename')
    def rename_trip(key):
        from domain import text
        name=text((request.get_json() or {}).get('name',''),120)
        if not name: raise ValueError('Введите название проекта.')
        with lock:
            trip=load(key)
            if (request.get_json() or {}).get('revision')!=trip['revision']:
                raise ValueError('Проект изменился в другой вкладке. Откройте меню заново.')
            generated=trip.get('generated_revision')==trip['revision']
            trip.update(name=name,revision=trip['revision']+1,updated=datetime.now().isoformat(timespec='seconds'))
            if generated: trip['generated_revision']=trip['revision']
            atomic(trip_path(key),trip)
            return jsonify(response_trip(trip))

    @app.post('/api/trips/<key>/copy')
    def copy_trip(key):
        with lock:
            original=load(key)
            trip=normalize(original)
            trip.update(id=uuid.uuid4().hex,name=(original.get('name') or original['city'])[:110]+' — копия',revision=1,updated=datetime.now().isoformat(timespec='seconds'))
            slug=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',trip['city']).strip(' .')[:60]
            trip['folder']=f"{trip['start']}_{slug}_{trip['id'][:6]}"
            atomic(trip_path(trip['id']),trip)
            return jsonify(response_trip(trip))

    @app.delete('/api/trips/<key>')
    def delete_trip(key):
        with lock:
            trip=load(key)
            if (request.get_json() or {}).get('revision')!=trip['revision']:
                raise ValueError('Проект изменился в другой вкладке. Откройте меню заново.')
            destination=trash/key
            if destination.exists(): raise ValueError('В корзине уже есть проект с этим идентификатором.')
            destination.mkdir(parents=True)
            source=trip_dir(trip)
            # Both paths are resolved and checked before moving the project tree.
            if not source.is_relative_to(paper) or source==paper or not destination.resolve().is_relative_to(trash.resolve()):
                raise ValueError('Недопустимый путь проекта.')
            shutil.move(str(source),str(destination/'Печать'))
            try: trip_path(key).replace(destination/'trip.json')
            except Exception:
                shutil.move(str(destination/'Печать'),str(source))
                raise
            return jsonify(deleted=True)

    @app.get('/api/trash')
    def list_trash():
        with lock:
            result=[]
            for path in trash.glob('*/trip.json'):
                trip=json.loads(path.read_text(encoding='utf-8'))
                result.append(dict(id=trip['id'],name=trip.get('name') or trip['city'],city=trip['city'],start=trip['start']))
            return jsonify(result)

    @app.post('/api/trash/<key>/restore')
    def restore_trip(key):
        with lock:
            active=trip_path(key)
            source=trash/key
            record=source/'trip.json'
            if active.exists() or not record.is_file(): raise ValueError('Проект уже восстановлен или не найден.')
            trip=json.loads(record.read_text(encoding='utf-8'))
            destination=(paper/trip['folder']).resolve()
            if not destination.is_relative_to(paper) or destination==paper: raise ValueError('Недопустимая папка проекта.')
            if destination.exists(): raise ValueError('Папка для этой поездки уже существует. Переместите её перед восстановлением.')
            shutil.move(str(source/'Печать'),str(destination))
            old_revision=trip['revision']
            trip['revision']+=1
            if trip.get('generated_revision')==old_revision: trip['generated_revision']=trip['revision']
            trip['updated']=datetime.now().isoformat(timespec='seconds')
            try: atomic(active,trip)
            except Exception:
                shutil.move(str(destination),str(source/'Печать'))
                raise
            record.unlink();source.rmdir()
            return jsonify(response_trip(trip))

    @app.post('/api/trips')
    @app.put('/api/trips/<key>')
    def save_trip(key=None):
        data=request.get_json()
        clean=normalize(data)
        with lock:
            history=suggestions()
            if key:
                previous=load(key)
                if data.get('revision')!=previous['revision']:
                    raise ValueError('Карточка изменена в другой вкладке. Сохраните введенный текст отдельно и откройте командировку заново.')
                clean.update({k:previous[k] for k in ('id','folder')})
                clean['revision']=previous['revision']+1
            else:
                clean['id']=uuid.uuid4().hex
                slug=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',clean['city']).strip(' .')[:60]
                clean['folder']=f"{clean['start']}_{slug}_{clean['id'][:6]}"
                clean['revision']=1
            clean['updated']=datetime.now().isoformat(timespec='seconds')
            atomic(trip_path(clean['id']),clean)
            for group,field in [('cities','city'),('purposes','purpose')]:
                if clean[field] and clean[field].casefold() not in {v.casefold() for v in history[group]}:
                    history[group].append(clean[field])
            atomic(store/'history.json',history)
            atomic(store/'defaults.json',{k:clean[k] for k in ('organization','recipient_title','recipient','role','employee','employee_genitive','employee_dative')})
            return jsonify(response_trip(clean))

    @app.post('/api/trips/<key>/generate')
    def generate(key):
        with lock:
            trip=load(key)
            if (request.get_json() or {}).get('revision')!=trip['revision']: raise ValueError('Сначала сохраните изменения и обновите карточку.')
            folder=trip_dir(trip)
            root=folder/'Документы'
            signature=folder/SIGNATURE
            placements=active_layouts(trip)
            for name,(kind,signed) in FORM_FILES.items():
                target=root/name
                if trip['include_'+kind] and (not signed or signature.is_file()):
                    temp=root/('.'+name)
                    try:
                        form(temp,trip,kind,signature if signed else None,placements.get(kind))
                        temp.replace(target)
                    finally:
                        temp.unlink(missing_ok=True)
                else:
                    target.unlink(missing_ok=True)
            trip['generated_revision']=trip['revision']
            trip['generated_signature_layouts']=placements
            atomic(trip_path(key),trip)
            return jsonify(response_trip(trip))

    @app.route('/api/trips/<key>/signature',methods=['POST','DELETE'])
    def update_signature(key):
        with lock:
            trip=load(key)
            root=trip_dir(trip)
            target=root/SIGNATURE
            if request.method=='POST':
                items=request.files.getlist('files')
                if len(items)!=1: raise ValueError('Выберите один файл PNG или JPEG.')
                source=items[0].stream.read(10*1024*1024+1)
                if len(source)>10*1024*1024: raise ValueError('Файл подписи должен быть не больше 10 МБ.')
                temp=target.with_suffix('.tmp')
                try:
                    save_signature(BytesIO(source),temp)
                    temp.replace(target)
                finally:
                    temp.unlink(missing_ok=True)
            else:
                target.unlink(missing_ok=True)
            for subdir in ('Документы','Предпросмотр'):
                for name in SIGNED.values():
                    (root/subdir/name).unlink(missing_ok=True)
            trip.pop('generated_revision',None)
            trip['revision']+=1
            atomic(trip_path(key),trip)
            return jsonify(response_trip(trip))

    @app.post('/api/trips/<key>/upload')
    def upload(key):
        with lock:
            trip=load(key); folder=trip_dir(trip)/'Чеки'
            items=request.files.getlist('files')
            if not items: raise ValueError('Выберите файлы.')
            for uploaded in items:
                name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',uploaded.filename or 'Файл').strip(' .')[:160]
                if not name: name='Файл'
                # A browser may submit a full Windows path; it becomes a harmless filename.
                target=folder/name; counter=2
                while target.exists():
                    target=folder/f'{Path(name).stem} ({counter}){Path(name).suffix}'; counter+=1
                if not target.resolve().is_relative_to(folder.resolve()): raise ValueError('Недопустимое имя файла.')
                uploaded.save(target)
            return jsonify(response_trip(trip))

    @app.get('/api/trips/<key>/file')
    def view_file(key):
        trip=load(key); path=safe_file(trip,request.args.get('path',''))
        inline=path.suffix.lower() in SUPPORTED
        return send_file(path,as_attachment=not inline or request.args.get('download')=='1',download_name=path.name)

    @app.post('/api/trips/<key>/folder')
    def open_folder(key):
        folder=trip_dir(load(key))
        if os.name=='nt':
            # Explicit Explorer launch works with hidden pythonw sessions too.
            explorer=Path(os.environ.get('WINDIR','C:/Windows'))/'explorer.exe'
            subprocess.Popen([str(explorer),str(folder)],close_fds=True)
        elif sys.platform=='darwin': subprocess.Popen(['open',str(folder)])
        else: subprocess.Popen(['xdg-open',str(folder)])
        return jsonify(path=str(folder),opened=True)

    @app.post('/api/trips/<key>/preview/<kind>')
    def preview(key,kind):
        if kind not in DOCS: raise ValueError('Неизвестная печатная форма.')
        with lock:
            trip=load(key)
            data=request.get_json() or {}
            if data.get('revision')!=trip['revision']:
                raise ValueError('Сначала сохраните изменения.')
            folder=trip_dir(trip)
            signature=folder/SIGNATURE if data.get('signed') else None
            if signature and (kind not in SIGNED or not signature.is_file()):
                raise ValueError('Добавьте образец подписи на вкладке «Печать и чеки».')
            root=folder/'Предпросмотр'
            root.mkdir(exist_ok=True)
            path=root/(SIGNED[kind] if signature else DOCS[kind])
            temp=path.with_suffix('.tmp')
            form(temp,trip,kind,signature,layouts().get(kind));temp.replace(path)
            return jsonify(path=path.relative_to(trip_dir(trip)).as_posix())

    @app.route('/api/trips/<key>/signature-layout/<kind>',methods=['POST','PUT'])
    def signature_layout(key,kind):
        if kind not in SIGNED:
            raise ValueError('У этой формы нет подписи.')
        data=request.get_json() or {}
        with lock:
            trip=load(key)
            if data.get('revision')!=trip['revision']:
                raise ValueError('Сначала сохраните изменения.')
            folder=trip_dir(trip)
            signature=folder/SIGNATURE
            if not signature.is_file():
                raise ValueError('Загрузите подпись на вкладке «Печать и чеки».')
            settings=layouts()
            previous=settings.get(kind,DEFAULT_PLACEMENT)
            if request.method=='POST':
                root=folder/'Предпросмотр'
                root.mkdir(exist_ok=True)
                path=root/f'Макет_{DOCS[kind]}'
                temp=path.with_suffix('.tmp')
                try:
                    anchor=form(temp,trip,kind,signature,editing=True)
                    temp.replace(path)
                finally:
                    temp.unlink(missing_ok=True)
                return jsonify(path=path.relative_to(folder).as_posix(),anchor=anchor,placement=previous)

            if data.get('previous')!=previous:
                raise ValueError('Настройку уже изменили в другом окне. Откройте её заново.')
            placement=data.get('placement')
            ranges={'dx':(-596,596),'dy':(-842,842),'scale':(.35,3.5)}
            if not isinstance(placement,dict) or any(
                type(placement.get(field)) not in (int,float)
                or not low<=placement[field]<=high
                or not math.isfinite(placement[field])
                for field,(low,high) in ranges.items()
            ):
                raise ValueError('Укажите допустимое положение и размер подписи.')
            value={field:round(placement[field],3) for field in ranges}
            if value!=previous:
                if value==DEFAULT_PLACEMENT:
                    settings.pop(kind,None)
                else:
                    settings[kind]=value
                atomic(layout_path,settings)
            return jsonify(response_trip(load(key)))

    @app.get('/api/trips/<key>/preview-view')
    def preview_view(key):
        import pypdfium2 as pdfium
        with lock:
            relative=request.args.get('path','')
            path=safe_file(load(key),relative)
            if path.suffix.lower()!='.pdf': raise ValueError('Нужен PDF для предпросмотра.')
            with pdfium.PdfDocument(str(path)) as document: pages=len(document)
            return render_template('preview.html',key=key,path=relative,pages=pages)

    @app.get('/api/trips/<key>/preview-page')
    def preview_page(key):
        import pypdfium2 as pdfium
        with lock:
            path=safe_file(load(key),request.args.get('path',''))
            if path.suffix.lower()!='.pdf': raise ValueError('Нужен PDF для предпросмотра.')
            try: number=int(request.args.get('page','0'))
            except ValueError: raise ValueError('Некорректный номер страницы.') from None
            with pdfium.PdfDocument(str(path)) as document:
                if not 0<=number<len(document): raise ValueError('Страница не найдена.')
                page=document[number]
                bitmap=page.render(scale=2.5)
                image=bitmap.to_pil()
                buffer=BytesIO();image.save(buffer,format='PNG');buffer.seek(0)
                image.close();bitmap.close();page.close()
            return send_file(buffer,mimetype='image/png')

    @app.post('/api/trips/<key>/pack')
    def pack(key):
        progress=request.environ.get('j701.progress')
        if progress:
            progress(2,'Проверяем выбранные файлы')
        with lock:
            trip=load(key); data=request.get_json() or {}
            if data.get('revision')!=trip['revision']: raise ValueError('Сначала сохраните изменения и обновите документы.')
            entries=data.get('files',[])
            if not isinstance(entries,list) or len(entries)>500: raise ValueError('Слишком много файлов.')
            ready=[]
            available={item['path']:item for item in files(trip)}
            for entry in entries:
                relative=entry.get('path','')
                item=available.get(relative)
                if not item or not item['supported']: raise ValueError('Обновите список файлов или заново подготовьте документы.')
                path=safe_file(trip,relative)
                try: copies=int(entry.get('copies',1))
                except (ValueError,TypeError): raise ValueError('Некорректное количество копий.') from None
                if not 1<=copies<=10: raise ValueError('Допустимо от 1 до 10 копий.')
                ready.append((not item['generated'],path,copies))
            ready.sort(key=lambda item:item[0])
            name='Комплект_'+datetime.now().strftime('%Y-%m-%d_%H-%M-%S')+'_'+secrets.token_hex(2)+'.pdf'
            destination=trip_dir(trip)/name
            temp=destination.with_suffix('.tmp')
            try:
                pages=combine([(path,copies) for _,path,copies in ready],temp,
                              progress=progress,receipt_dpi=app.config.get('RECEIPT_DPI'))
                temp.replace(destination)
            finally:
                if temp.exists(): temp.unlink()
            if progress:
                progress(100,'PDF готов')
            return jsonify(path=name,pages=pages)

    app.trip_store=store
    return app

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=20866)
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    if not 20000 <= args.port <= 65535:
        parser.error('Порт должен быть от 20000 до 65535.')
    from runtime import serve
    serve(create_app(),args.port,open_browser=not args.no_browser)
