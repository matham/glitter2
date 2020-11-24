# -*- mode: python ; coding: utf-8 -*-

block_cipher = None
from kivy_deps import sdl2, glew
import ffpyplayer
import base_kivy_app
import glitter2
from os.path import dirname, join
from kivy.tools.packaging.pyinstaller_hooks import get_deps_minimal, \
    get_deps_all, hookspath, runtime_hooks
import nixio.info
import ruamel.yaml

kwargs = get_deps_minimal(video=None, audio=None, camera=None)
kwargs['hiddenimports'].extend([
    'pkg_resources.py2_warn', 'ffpyplayer', 'ffpyplayer.pic', 'win32timezone',
    'ffpyplayer.threading', 'ffpyplayer.tools', 'ffpyplayer.writer',
    'ffpyplayer.player', 'ffpyplayer.player.clock', 'ffpyplayer.player.core',
    'ffpyplayer.player.decoder', 'ffpyplayer.player.frame_queue',
    'ffpyplayer.player.player', 'ffpyplayer.player.queue',
    'numpy.random.common', 'numpy.random.bounded_integers',
    'numpy.random.entropy', 'plyer.platforms.win.filechooser',
    'plyer.facades.filechooser', 'kivy.core.window.window_info',
    '_ruamel_yaml', 'ruamel.yaml.main'])


a = Analysis(['../glitter2/run_app.py'],
             pathex=['.'],
             datas=base_kivy_app.get_pyinstaller_datas() + glitter2.get_pyinstaller_datas() + [
                 (join(dirname(nixio.info.__file__), 'info.json'), 'nixio')] + [
                 (ruamel.yaml.__file__, 'ruamel/yaml')],
             hookspath=hookspath(),
             runtime_hooks=runtime_hooks(),
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False,
             **kwargs)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          *[Tree(p) for p in (sdl2.dep_bins + glew.dep_bins + ffpyplayer.dep_bins)],
          name='Glitter2',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          upx_exclude=[],
          runtime_tmpdir=None,
          console=True,
          icon='..\\doc\\source\\images\\glitter2_icon.ico')
