# -*- mode: python ; coding: utf-8 -*-

import os
import sys
import platform
import subprocess
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

_machine = platform.machine().lower()
if _machine in ('amd64', 'x86_64'):
    _arch = 'x64'
elif _machine in ('arm64', 'aarch64'):
    _arch = 'arm64'
elif _machine in ('i386', 'i686', 'x86'):
    _arch = 'x86'
else:
    _arch = _machine  # fallback: ARM v7, RISC-V, etc.

if sys.platform == 'win32':
    _os = 'win'
elif sys.platform == 'darwin':
    _os = 'macos'
else:
    _os = 'linux'

_platform = f'{_os}-{_arch}'

# ── Icon per platform ─────────────────────────────────────────────────────────
if sys.platform == 'win32':
    _icon = os.path.join(SPECPATH, 'assets', 'canlytics.ico')
elif sys.platform == 'darwin':
    _iconset = os.path.join(SPECPATH, 'assets', 'canlytics.iconset')
    _icns = os.path.join(SPECPATH, 'assets', 'canlytics.icns')
    os.makedirs(_iconset, exist_ok=True)
    import shutil
    from PIL import Image
    _ico = Image.open(os.path.join(SPECPATH, 'assets', 'canlytics.ico')).convert('RGBA')
    # Each (px, filename) pair — @2x entries share the same rendered size
    _icon_entries = [
        (16,   'icon_16x16.png'),
        (32,   'icon_16x16@2x.png'),
        (32,   'icon_32x32.png'),
        (64,   'icon_32x32@2x.png'),
        (128,  'icon_128x128.png'),
        (256,  'icon_128x128@2x.png'),
        (256,  'icon_256x256.png'),
        (512,  'icon_256x256@2x.png'),
        (512,  'icon_512x512.png'),
        (1024, 'icon_512x512@2x.png'),
    ]
    _rendered = {}
    for _sz, _fname in _icon_entries:
        if _sz not in _rendered:
            _tmp = os.path.join(_iconset, f'_tmp_{_sz}.png')
            _ico.resize((_sz, _sz), Image.LANCZOS).save(_tmp, 'PNG')
            _rendered[_sz] = _tmp
        shutil.copy(_rendered[_sz], os.path.join(_iconset, _fname))
    subprocess.run(['iconutil', '-c', 'icns', _iconset, '-o', _icns], check=True)
    _icon = _icns
else:
    _icon = None

# ── Read version from single source of truth ─────────────────────────────────
_ver_ns: dict = {}
exec(open(os.path.join(SPECPATH, 'config', 'version.py')).read(), _ver_ns)
APP_VERSION: str = _ver_ns['APP_VERSION']
_ver_tuple = tuple(int(x) for x in APP_VERSION.split('.'))
_ver_tuple = (_ver_tuple + (0, 0, 0, 0))[:4]

# Generate Windows PE version info file (overwritten on every build)
_VI_PATH = os.path.join(SPECPATH, '_version_info.txt')
with open(_VI_PATH, 'w', encoding='utf-8') as _vf:
    _vf.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={_ver_tuple},
    prodvers={_ver_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'MS4M SAC'),
         StringStruct(u'FileDescription', u'Canlytics CAN Analyzer'),
         StringStruct(u'FileVersion', u'{APP_VERSION}'),
         StringStruct(u'InternalName', u'Canlytics'),
         StringStruct(u'OriginalFilename', u'Canlytics-{APP_VERSION}-{_platform}.exe'),
         StringStruct(u'ProductName', u'Canlytics'),
         StringStruct(u'ProductVersion', u'{APP_VERSION}'),
        ]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [0x0409, 1200])])
  ]
)
""")

block_cipher = None


def optional_collect_data_files(module_name):
    try:
        return collect_data_files(module_name)
    except Exception:
        return []


def optional_collect_dynamic_libs(module_name):
    try:
        return collect_dynamic_libs(module_name)
    except Exception:
        return []


def optional_collect_submodules(module_name):
    try:
        return collect_submodules(module_name)
    except Exception:
        return []


def filter_hiddenimports(modules):
    blocked_fragments = (
        '.tests',
        '.testing',
        'pyqtgraph.opengl',
    )
    result = []
    seen = set()
    for module in modules:
        if any(fragment in module for fragment in blocked_fragments):
            continue
        if module in seen:
            continue
        seen.add(module)
        result.append(module)
    return result


datas = []
datas += [('assets', 'assets')]
datas += optional_collect_data_files('tzdata')
datas += optional_collect_data_files('pyqtgraph')
datas += optional_collect_data_files('cantools')
datas += optional_collect_data_files('paramiko')
datas += optional_collect_data_files('pytesseract')

binaries = []
binaries += optional_collect_dynamic_libs('numpy')
binaries += optional_collect_dynamic_libs('cv2')
binaries += optional_collect_dynamic_libs('polars')

hiddenimports = [
    'serial',
    'can',
    'can.interfaces.kvaser',
    'can.interfaces.j2534',
    'cantools',
    'cv2',
    'numpy',
    'paramiko',
    'polars',
    'pyqtgraph',
    'pytesseract',
    'tzdata',
    'PySide6',
    'PySide6.QtWidgets',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtOpenGL',
    'PySide6.QtSvg',
]
hiddenimports += optional_collect_submodules('polars')
hiddenimports += optional_collect_submodules('numpy')
hiddenimports += optional_collect_submodules('pyqtgraph')
hiddenimports += optional_collect_submodules('cantools')
hiddenimports += optional_collect_submodules('paramiko')
hiddenimports += optional_collect_submodules('pytesseract')
hiddenimports += optional_collect_submodules('tzdata')
hiddenimports = filter_hiddenimports(hiddenimports)

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'pytest',
        'doctest',

        'PySide6.QtPrintSupport',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuickWidgets',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebSockets',
        'PySide6.QtNetwork',
        'PySide6.QtNetworkAuth',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtSvgWidgets',
        'PySide6.QtSql',
        'PySide6.QtTest',
        'PySide6.QtDesigner',
        'PySide6.QtPositioning',
        'PySide6.QtBluetooth',
        'PySide6.QtSerialBus',
        'PySide6.QtSerialPort',
        'PySide6.QtRemoteObjects',
        'PySide6.QtScxml',
        'PySide6.QtSensors',
        'PySide6.QtStateMachine',
        'PySide6.QtTextToSpeech',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtHttpServer',
        'PySide6.QtLocation',
        'PySide6.QtNfc',
        'PySide6.QtOpcUa',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DRender',
        'PySide6.Qt3DInput',
        'PySide6.Qt3DExtras',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=f'Canlytics-{APP_VERSION}-{_platform}',
    debug=False,
    strip=False,
    upx=sys.platform == 'win32',
    console=False,
    icon=_icon,
    version=_VI_PATH if sys.platform == 'win32' else None,
)
