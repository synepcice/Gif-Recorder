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
    ['gif_recorder.py'],
    pathex=['D:\\OneDrive\\Syn Save\\Dev-Env\\gemini-temp-1760712797327'],
    binaries=imageio_ffmpeg_binaries,
    datas=[('icon.ico', '.'), ('SplashScreen.png', '.'), ('eye.png', '.'), ('Icons', 'Icons')] + copy_metadata('imageio') + copy_metadata('imageio-ffmpeg'),
    hiddenimports=['PIL', 'PIL.Image', 'PIL.ImageTk', 'PIL.ImageDraw', 'PIL.ImageFont'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Gif Recorder',
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
    splash='SplashScreen.png', # Splash screen
)

