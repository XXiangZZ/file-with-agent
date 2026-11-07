# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks import copy_metadata

datas = [('models', 'models'), ('resources', 'resources'), ('config/templates', 'config/templates'), ('ui', 'ui'), ('build', 'build'), ('E:\\PythonProject\\code\\archive_tool\\.venv\\Lib\\site-packages\\Cython\\Utility', 'Cython\\Utility')]
binaries = [('E:\\PythonProject\\code\\archive_tool\\.venv\\Lib\\site-packages\\paddle\\libs', 'paddle/libs')]
hiddenimports = ['paddleocr.paddleocr', 'paddle', 'tools', 'tools.program', 'tools.naive_sync_bn', 'imgaug', 'imageio']

# Manual QA uses packaged guides and LangChain's runtime metadata.
datas += copy_metadata('langchain-core')
datas += copy_metadata('langchain-text-splitters')
datas += copy_metadata('imageio')
datas += copy_metadata('imgaug')
hiddenimports += collect_submodules('ppocr')
hiddenimports += collect_submodules('ppstructure')
hiddenimports += collect_submodules('tools')
tmp_ret = collect_all('paddleocr')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('paddle')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('imgaug')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('imageio')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=['E:\\PythonProject\\code\\archive_tool\\.venv\\Lib\\site-packages'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['E:\\PythonProject\\code\\archive_tool\\build\\pyinstaller-hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'tensorflow', 'transformers', 'onnx', 'onnxruntime', 'torchvision', 'torchaudio'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='archive_tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='archive_tool',
)
