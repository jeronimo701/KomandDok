"""HTTP server and Windows tray share the same process and lifetime."""
import threading
import webbrowser
from pathlib import Path
from PIL import Image
import pystray
from werkzeug.serving import make_server
from tray_animation import TrayAnimator

def serve(app,port,open_browser=True,tray=True):
    server=make_server('127.0.0.1',port,app,threaded=True)
    url=f'http://127.0.0.1:{port}'
    stopping=threading.Event()
    icon=None
    animator=None
    def stop(source='tray'):
        if stopping.is_set(): return
        stopping.set()
        app.config['CLOSE_SOURCE']=source
        app.config['CLOSED_EVENT'].set()
        threading.Thread(target=server.shutdown,daemon=True).start()
    app.config['STOP_SERVER']=stop
    try:
        if tray:
            image=Image.open(Path(__file__).parent/'static/app.png')
            icon=pystray.Icon('J701',image,'КомандДок · '+str(port),pystray.Menu(
                pystray.MenuItem('Открыть КомандДок',lambda *_:webbrowser.open(url),default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem('Остановить сервер и выйти',lambda *_:stop())))
            icon.run_detached()
            app.config['TRAY_ICON']=icon
            animator=TrayAnimator(icon,Path(__file__).parent/'static/app.gif')
            animator.start()
            app.config['TRAY_ANIMATION']=animator
        if open_browser:
            threading.Timer(.6,lambda:webbrowser.open(url)).start()
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        if not app.config['CLOSED_EVENT'].is_set():
            app.config['CLOSE_SOURCE']='console'
            app.config['CLOSED_EVENT'].set()
        if animator is not None: animator.stop()
        if icon is not None: icon.stop()
        app.config.pop('TRAY_ANIMATION',None)
        app.config.pop('TRAY_ICON',None)
        server.server_close()
        app.config.pop('STOP_SERVER',None)
