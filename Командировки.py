"""Единственная точка входа. Код приложения находится в папке Данные."""
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import threading
import urllib.request
import webbrowser

FROZEN=bool(getattr(sys,'frozen',False))
ROOT=Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
DATA=ROOT/'Данные'
CODE=Path(getattr(sys,'_MEIPASS',ROOT/'Данные'))
sys.path.insert(0,str(CODE))
CONFIG=DATA/'settings.json'
RUNTIME=DATA/'runtime.json'

def message(text):
    if os.name=='nt': ctypes.windll.user32.MessageBoxW(0,text,'КомандДок',0x10)
    else: print(text)

def running(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health',timeout=.5) as response:
            status=json.load(response)
            return status.get('app')=='TripAssistant' and Path(status.get('root','')).resolve()==DATA.resolve()
    except Exception: return False

def main():
    from app_paths import ensure_folders
    ensure_folders()
    if not CONFIG.exists(): CONFIG.write_text(json.dumps({'preferred_port':20866},indent=2),encoding='utf-8')
    if sys.stdout is None: sys.stdout=(DATA/'запуск.log').open('a',encoding='utf-8',buffering=1)
    if sys.stderr is None: sys.stderr=sys.stdout
    if not FROZEN and not (DATA/'app.py').exists(): raise RuntimeError('Не найдена папка Данные рядом с программой.')
    if RUNTIME.exists():
        try:
            port=int(json.loads(RUNTIME.read_text(encoding='utf-8'))['port'])
            if 20000<=port<=65535 and running(port): webbrowser.open(f'http://127.0.0.1:{port}'); return
        except (ValueError,KeyError,OSError): pass
    settings=json.loads(CONFIG.read_text(encoding='utf-8')) if CONFIG.exists() else {'preferred_port':20866}
    preferred=int(settings.get('preferred_port',20866))
    if not 20000<=preferred<=65535: raise RuntimeError('В Данные/settings.json укажите порт от 20000 до 65535.')
    port=None
    for candidate in range(preferred,min(preferred+100,65536)):
        if running(candidate): webbrowser.open(f'http://127.0.0.1:{candidate}'); return
        with socket.socket() as probe:
            try: probe.bind(('127.0.0.1',candidate)); port=candidate; break
            except OSError: continue
    if port is None: raise RuntimeError('Нет свободного порта. Измените preferred_port в Данные/settings.json.')
    url=f'http://127.0.0.1:{port}'
    log_path=DATA/'запуск.log'
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    executable=sys.executable
    missing=[] if FROZEN else [name for name in ['flask','reportlab','pypdf','PIL','pypdfium2','pystray'] if importlib.util.find_spec(name) is None]
    with log_path.open('a',encoding='utf-8') as log:
        if missing:
            install=subprocess.run([executable,'-m','pip','install','-r',str(DATA/'requirements.txt')],stdout=log,stderr=log,creationflags=flags)
            if install.returncode: raise RuntimeError('Не удалось установить библиотеки. При первом запуске нужен интернет. Подробности: Данные/запуск.log')
    from app import create_app
    from runtime import serve
    RUNTIME.write_text(json.dumps({'port':port,'pid':os.getpid()}),encoding='utf-8')
    try:
        # One foreground process: VS Code Stop / Ctrl+C stops the server too.
        serve(create_app(),port,open_browser='--no-browser' not in sys.argv)
    finally:
        if RUNTIME.exists():
            state=json.loads(RUNTIME.read_text(encoding='utf-8'))
            if state.get('pid')==os.getpid(): RUNTIME.unlink()

if __name__=='__main__':
    try: main()
    except Exception as exc: message(str(exc))
