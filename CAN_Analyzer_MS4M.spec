# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

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
        'PySide6.QtSvg',
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
    name='CAN_Analyzer MS4M',
    debug=False,
    strip=False,
    upx=True,
    console=False,
)
