# -*- mode: python ; coding: utf-8 -*-


block_cipher = None


from PyInstaller.utils.hooks import copy_metadata, collect_data_files
import os

# Get imageio-ffmpeg binaries
imageio_ffmpeg_binaries = []
try:
    import imageio_ffmpeg
    ffmpeg_dir = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
    for file in os.listdir(ffmpeg_dir):
        if file.endswith('.exe'):
            imageio_ffmpeg_binaries.append((os.path.join(ffmpeg_dir, file), 'imageio_ffmpeg/binaries'))
except:
    pass

a = Analysis(
    ['gif_editor.py'],
    pathex=[],
    binaries=imageio_ffmpeg_binaries,
    datas=[('icons', 'icons')] + copy_metadata('imageio') + copy_metadata('imageio-ffmpeg'),
    hiddenimports=['PIL', 'PIL.Image', 'PIL.ImageTk', 'PIL.ImageDraw', 'PIL.ImageFont'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Gif Editor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_info_entries={
        '__pyinstaller_tests_passed__': 'True',
    },
    console=False, # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico', # Application icon
)

