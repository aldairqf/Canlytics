# -*- mode: python ; coding: utf-8 -*-
# Builds BOTH distribution artifacts from a single Analysis() pass:
#   - onefile: Canlytics-{version}-{platform}(.exe)          -- self-extracting, single file
#   - onedir:  Canlytics-{version}-{platform}-dir/            -- folder, no self-extraction at runtime

import os
import sys

sys.path.insert(0, SPECPATH)
import _build_common as common

_platform = common.detect_platform()
_icon = common.build_icon(SPECPATH)
APP_VERSION = common.read_version(SPECPATH)
_NAME_VERSION = common.resolve_name_version(APP_VERSION)
_VI_PATH = common.write_version_info(SPECPATH, APP_VERSION, _NAME_VERSION, _platform)

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=common.collect_app_binaries(),
    datas=common.collect_app_datas(),
    hiddenimports=common.collect_app_hiddenimports(),
    hookspath=[],
    runtime_hooks=[],
    excludes=common.QT_EXCLUDES + common.SCIPY_EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

_name = f'Canlytics-{_NAME_VERSION}-{_platform}'
# Onefile has no extension on Linux/macOS -- a onedir folder of the same name
# would collide with it in dist/ (can't have a file and a directory sharing one
# name). Give the onedir output its own distinct name on every platform.
_name_dir = f'{_name}-dir'
_version_arg = _VI_PATH if sys.platform == 'win32' else None
_upx = sys.platform == 'win32'

# Onefile: single self-extracting exe (current default distribution artifact).
exe_onefile = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=_name,
    debug=False,
    strip=False,
    upx=_upx,
    console=False,
    icon=_icon,
    version=_version_arg,
)

# Onedir: a folder with the exe + its deps alongside it, no self-extraction at
# runtime. Antivirus heuristics flag onefile's self-extracting stub far more
# often than a plain folder of files -- offering this as an alternative
# distribution avoids that without needing a code-signing certificate.
exe_onedir = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=_name,
    debug=False,
    strip=False,
    upx=_upx,
    console=False,
    icon=_icon,
    version=_version_arg,
)

coll = COLLECT(
    exe_onedir,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=_upx,
    name=_name_dir,
)
