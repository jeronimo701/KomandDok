"""Separate bundled assets from the portable folder's writable user data."""
from pathlib import Path
import sys

FROZEN=bool(getattr(sys,'frozen',False))
ASSETS=Path(__file__).resolve().parent
ROOT=Path(sys.executable).resolve().parent if FROZEN else ASSETS.parent
DATA=ROOT/'Данные'
PRINT=ROOT/'Печать'

def ensure_folders():
    for folder in (DATA,DATA/'Командировки',DATA/'Корзина',PRINT):
        folder.mkdir(parents=True,exist_ok=True)
