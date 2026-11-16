"""Build a fresh portable executable without copying business/user records."""
from pathlib import Path
import argparse,subprocess,sys,shutil
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser()
p.add_argument('--output',required=True,type=Path)
a=p.parse_args();out=a.output.resolve()
if out.exists():raise SystemExit('Output exists; select a new directory. Nothing is deleted.')
if out==ROOT or ROOT in out.parents and 'work' not in out.relative_to(ROOT).parts:raise SystemExit('Select a separate build destination.')
out.mkdir(parents=True)
work=ROOT/'work/pyinstaller'
args=[sys.executable,'-m','PyInstaller','--noconfirm','--onefile','--windowed','--noupx','--distpath',str(out),'--workpath',str(work/'cache'),'--specpath',str(work),'--hidden-import','pystray._win32','--log-level','WARN','--add-data',str(ROOT/'publication-notices')+';publication-notices']
code=ROOT/'Данные'
args+=['--name','J701','--icon',str(code/'static/app.ico'),'--paths',str(code),'--add-data',str(code/'static')+';static','--add-data',str(code/'templates')+';templates','--collect-all','pypdfium2_raw','--collect-data','pypdfium2']
for module in ['tkinter','matplotlib','numpy','pandas','IPython','pytest']:args+=['--exclude-module',module]
args.append(str(ROOT/'Командировки.py'))
subprocess.run(args,check=True)
for directory in ['Данные/Командировки','Данные/Корзина','Печать']:(out/directory).mkdir(parents=True,exist_ok=True)
shutil.copy2(code/'settings.json',out/'Данные/settings.json')
for filename in ['LICENSE.txt','LICENSE-SCOPE.md','THIRD-PARTY.md','SOURCES.json']:
    shutil.copy2(ROOT/filename,out/filename)
shutil.copytree(ROOT/'publication-notices',out/'publication-notices')
print('Built portable folder:',out)
