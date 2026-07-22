# Shared PyInstaller spec setup for Canlytics.spec's onefile and onedir
# outputs. Imported via `sys.path.insert(0, SPECPATH)`.

import os
import sys
import platform
import subprocess

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)


def detect_platform() -> str:
    machine = platform.machine().lower()
    if machine in ('amd64', 'x86_64'):
        arch = 'x64'
    elif machine in ('arm64', 'aarch64'):
        arch = 'arm64'
    elif machine in ('i386', 'i686', 'x86'):
        arch = 'x86'
    else:
        arch = machine  # fallback: ARM v7, RISC-V, etc.

    if sys.platform == 'win32':
        os_name = 'win'
    elif sys.platform == 'darwin':
        os_name = 'macos'
    else:
        os_name = 'linux'
    return f'{os_name}-{arch}'


def build_icon(specpath: str):
    """Returns the platform-appropriate icon path (or None on Linux)."""
    if sys.platform == 'win32':
        return os.path.join(specpath, 'assets', 'canlytics.ico')

    if sys.platform == 'darwin':
        iconset = os.path.join(specpath, 'assets', 'canlytics.iconset')
        icns = os.path.join(specpath, 'assets', 'canlytics.icns')
        os.makedirs(iconset, exist_ok=True)
        import shutil
        from PIL import Image
        ico = Image.open(os.path.join(specpath, 'assets', 'canlytics.ico')).convert('RGBA')
        # Each (px, filename) pair -- @2x entries share the same rendered size
        icon_entries = [
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
        rendered = {}
        for sz, fname in icon_entries:
            if sz not in rendered:
                tmp = os.path.join(iconset, f'_tmp_{sz}.png')
                ico.resize((sz, sz), Image.LANCZOS).save(tmp, 'PNG')
                rendered[sz] = tmp
            shutil.copy(rendered[sz], os.path.join(iconset, fname))
        subprocess.run(['iconutil', '-c', 'icns', iconset, '-o', icns], check=True)
        return icns

    return None


def read_version(specpath: str) -> str:
    ver_ns: dict = {}
    exec(open(os.path.join(specpath, 'config', 'version.py')).read(), ver_ns)
    return ver_ns['APP_VERSION']


def resolve_name_version(app_version: str) -> str:
    """Optional build label (e.g. "alpha") for test builds that must NOT bump
    config/version.py -- set CANLYTICS_BUILD_SUFFIX before invoking PyInstaller."""
    build_suffix = os.environ.get('CANLYTICS_BUILD_SUFFIX', '').strip().strip('-')
    return f'{app_version}-{build_suffix}' if build_suffix else app_version


def write_version_info(specpath: str, app_version: str, name_version: str, platform_tag: str) -> str:
    """Generates the Windows PE version info file (overwritten on every build).
    Harmless (unused) on non-Windows builds."""
    ver_tuple = tuple(int(x) for x in app_version.split('.'))
    ver_tuple = (ver_tuple + (0, 0, 0, 0))[:4]
    vi_path = os.path.join(specpath, '_version_info.txt')
    with open(vi_path, 'w', encoding='utf-8') as vf:
        vf.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={ver_tuple},
    prodvers={ver_tuple},
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
         StringStruct(u'FileVersion', u'{app_version}'),
         StringStruct(u'InternalName', u'Canlytics'),
         StringStruct(u'OriginalFilename', u'Canlytics-{name_version}-{platform_tag}.exe'),
         StringStruct(u'ProductName', u'Canlytics'),
         StringStruct(u'ProductVersion', u'{app_version}'),
        ]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [0x0409, 1200])])
  ]
)
""")
    return vi_path


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


QT_EXCLUDES = [
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
]

# Only scipy.stats is used (Diff Analyzer's Mann-Whitney significance test) --
# not collect_submodules('scipy'), see SCIPY_EXCLUDES. Run `/build` to verify
# if scipy's dependency footprint ever changes.
SCIPY_EXCLUDES = [
    'scipy.ndimage',
    'scipy.io',
    'scipy.misc',
    'scipy.cluster',
    'scipy.spatial',
    'scipy.datasets',
    'scipy.signal',
    'scipy.interpolate',
    'scipy.odr',
    'scipy.fft',
]


def collect_app_datas():
    datas = [('assets', 'assets')]
    for mod in ('tzdata', 'pyqtgraph', 'cantools', 'paramiko', 'pytesseract', 'scipy'):
        datas += optional_collect_data_files(mod)
    return datas


def collect_app_binaries():
    binaries = []
    for mod in ('numpy', 'cv2', 'polars', 'scipy'):
        binaries += optional_collect_dynamic_libs(mod)
    return binaries


def collect_app_hiddenimports():
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
        'scipy',
        'scipy.stats',
        'PySide6',
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtOpenGL',
        'PySide6.QtSvg',
    ]
    for mod in ('polars', 'numpy', 'pyqtgraph', 'cantools', 'paramiko', 'pytesseract', 'tzdata'):
        hiddenimports += optional_collect_submodules(mod)
    return filter_hiddenimports(hiddenimports)
