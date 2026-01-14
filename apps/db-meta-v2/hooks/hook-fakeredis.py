# PyInstaller hook for fakeredis
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files('fakeredis', include_py_files=False)
