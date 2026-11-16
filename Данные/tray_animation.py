"""Animate the notification icon by replacing its frames."""
import threading
from PIL import Image, ImageSequence
class TrayAnimator:
    def __init__(self,icon,path):
        self.icon=icon
        with Image.open(path) as source:
            self.interval=source.info.get('duration',130)/1000
            self.frames=[frame.convert('RGBA').resize((64,64),Image.Resampling.LANCZOS) for frame in ImageSequence.Iterator(source)]
        self.ticks=0
        self._stop=threading.Event()
        self._thread=threading.Thread(target=self._run,name='J701-duck-animation',daemon=True)
    def start(self): self._thread.start()
    def _run(self):
        while not self._stop.wait(self.interval):
            if not self.icon.visible: continue
            self.icon.icon=self.frames[self.ticks%len(self.frames)]
            self.ticks+=1
    def stop(self):
        self._stop.set();self._thread.join(timeout=2)
