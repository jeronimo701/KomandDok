"""Run the shared J701 API in-process, without a listening socket."""
import json
import re
from contextlib import ExitStack
from pathlib import Path
import fonts   # Extract the packaged TrueType files before ReportLab opens them.
from pypdf import PdfReader, PdfWriter
from app import create_app

APP = ROOT = None

def start(root):
    global APP, ROOT
    requested = Path(root).resolve()
    if ROOT == requested:
        return
    APP = create_app(requested / 'Командировки', requested / 'Печать')
    APP.config['RECEIPT_DPI'] = 200
    ROOT = requested

def dispatch(method, route, payload='', uploads='[]', observer=None):
    if method not in {'GET','POST','PUT','DELETE'} or not re.fullmatch(
        r'/api/(?:defaults|suggestions|estimate|trips(?:/[a-f0-9]{32}(?:/(?:rename|copy|generate|pack|upload|signature|signature-layout/(?:request|report|memo)|preview/(?:request|report|memo|details)))?)?|trash(?:/[a-f0-9]{32}/restore)?)',
        route,
    ):
        raise ValueError('Действие недоступно.')
    with ExitStack() as stack:
        options = {}
        if method=='POST' and route.endswith(('/upload','/signature')):
            incoming = json.loads(uploads)
            options['data'] = {'files': [
                (stack.enter_context(open(item['staged'], 'rb')), item['name'])
                for item in incoming
            ]}
        elif payload:
            options.update(data=payload, content_type='application/json')
        if observer is not None and method=='POST' and route.endswith('/pack'):
            options['environ_overrides']={'j701.progress':observer.update}
        # The native bridge is the only caller, and there is no HTTP listener.
        with APP.test_client() as client:
            response = client.open(route, method=method, headers={'X-Trip-Token': APP.config['MOBILE_TOKEN']}, **options)
            return json.dumps({'ok': response.status_code < 400, 'data': response.get_json()}, ensure_ascii=False)

def attachment(key, relative):
    if not re.fullmatch(r'[a-f0-9]{32}', key):
        raise ValueError('Карточка не найдена.')
    card = json.loads((ROOT / 'Командировки' / (key + '.json')).read_text('utf-8'))
    paper = (ROOT / 'Печать').resolve()
    folder = (paper / card['folder']).resolve()
    path = (folder / relative).resolve()
    if not folder.is_relative_to(paper) or not path.is_relative_to(folder) or path.name.startswith('.') or not path.is_file():
        raise ValueError('Файл не найден.')
    return str(path)

def print_ranges(source, out, ranges):
    reader=PdfReader(source)
    writer=PdfWriter()
    for start,end in json.loads(ranges):
        for i in range(max(0,start),min(end+1,len(reader.pages))):
            writer.add_page(reader.pages[i])
    writer.write(out)
