import os
import pytest
import trio
import time
from pathlib import Path
import gc
import weakref
from collections import defaultdict
import shutil
import logging
from typing import Type, List
import nixio

from glitter2.storage.data_file import DataFile
from glitter2.tests.app import Glitter2TestApp

os.environ['KIVY_USE_DEFAULTCONFIG'] = '1'

file_count = defaultdict(int)

examples_dir = Path(__file__).parent.parent.parent.joinpath('examples')


@pytest.fixture()
def temp_file(tmp_path):
    def temp_file_gen(fname: str) -> Path:
        i = file_count[fname]
        file_count[fname] += 1

        root, ext = os.path.splitext(fname)
        if (tmp_path / fname).exists():
            return tmp_path / '{}_{}{}'.format(root, i, ext)
        return tmp_path / fname

    return temp_file_gen


@pytest.fixture(scope='session')
def app_list():
    apps = []

    yield apps

    gc.collect()
    alive_apps = []
    for i, (app, request) in enumerate(apps[1:-1]):
        app = app()
        request = request()
        if request is None:
            request = '<dead request>'

        if app is not None:
            alive_apps.append((app, request))
            logging.error(
                'Memory leak: failed to release app for test ' + repr(request))

            # import objgraph
            # objgraph.show_backrefs(
            #     [app], filename=r'E:\backrefs{}.png'.format(i), max_depth=50,
            #     too_many=1)
            # objgraph.show_chain(
            #     objgraph.find_backref_chain(
            #         last_app(), objgraph.is_proper_module),
            #     filename=r'E:\chain.png')

    assert not len(alive_apps), 'Memory leak: failed to release all apps'


@pytest.fixture()
async def glitter_app(
        request, nursery, temp_file, tmp_path, tmp_path_factory, app_list):
    ts0 = time.perf_counter()
    from kivy.core.window import Window
    from kivy.context import Context
    from kivy.clock import ClockBase
    from kivy.animation import Animation
    from kivy.base import stopTouchApp
    from kivy.factory import FactoryBase, Factory
    from kivy.lang.builder import BuilderBase, Builder
    from kivy.logger import LoggerHistory

    context = Context(init=False)
    context['Clock'] = ClockBase(async_lib='trio')
    # context['Factory'] = FactoryBase.create_from(Factory)
    # have to make sure all app files are imported before this because
    # globally read kv files will not be loaded again in the new builder,
    # except if manually loaded, which we don't do
    # context['Builder'] = BuilderBase.create_from(Builder)
    context.push()

    Window.create_window()
    Window.register()
    Window.initialized = True
    Window.canvas.clear()

    from kivy.clock import Clock
    Clock._max_fps = 0

    app = Glitter2TestApp(
        yaml_config_path=str(temp_file('config.yaml')),
        data_path=str(tmp_path))

    try:
        app.set_async_lib('trio')
        nursery.start_soon(app.async_run)

        ts = time.perf_counter()
        while not app.app_has_started:
            await trio.sleep(.1)
            if time.perf_counter() - ts >= 120:
                raise TimeoutError()

        await app.wait_clock_frames(5)

        ts1 = time.perf_counter()
        yield weakref.proxy(app)
        ts2 = time.perf_counter()

        app.storage_controller.has_unsaved = False
        app.storage_controller.config_changed = False

        stopTouchApp()

        ts = time.perf_counter()
        while not app.app_has_stopped:
            await trio.sleep(.1)
            if time.perf_counter() - ts >= 40:
                raise TimeoutError()

    finally:
        stopTouchApp()
        for anim in list(Animation._instances):
            anim._unregister()
        app.clean_up()
        for child in Window.children[:]:
            Window.remove_widget(child)

        context.pop()
        del context
        LoggerHistory.clear_history()

    app_list.append((weakref.ref(app), weakref.ref(request)))

    ts3 = time.perf_counter()
    print(ts1 - ts0, ts2 - ts1, ts3 - ts2)


@pytest.fixture()
def coded_data_file(temp_file):
    src = examples_dir.joinpath('video_data.h5')
    target = temp_file('video.h5')
    shutil.copy(src, target)
    return target


@pytest.fixture()
def sample_video_file(temp_file):
    src = examples_dir.joinpath('video.mp4')
    target = temp_file('video.mp4')
    shutil.copy(src, target)
    return target


@pytest.fixture()
def sample_csv_data_file(temp_file):
    src_video = examples_dir.joinpath('video.mp4')
    target_video = temp_file('video.mp4')
    shutil.copy(src_video, target_video)

    src_csv = examples_dir.joinpath('data').joinpath('video_data.csv')
    target_csv = target_video.with_name(src_csv.name)
    shutil.copy(src_csv, target_csv)
    return target_csv


@pytest.fixture()
def sample_clever_sys_data_file(temp_file):
    src_video = examples_dir.joinpath('video.mp4')
    target_video = temp_file('video.mp4')
    shutil.copy(src_video, target_video)

    data_dir = examples_dir.joinpath('data')
    shutil.copy(
        data_dir.joinpath('CleverSys_1_TCG.TXT'),
        target_video.with_name('CleverSys_1_TCG.TXT')
    )

    src_txt = data_dir.joinpath('CleverSys_1_TCR.TXT')
    target_txt = target_video.with_name(src_txt.name)
    shutil.copy(src_txt, target_txt)
    return target_txt


@pytest.fixture()
def sample_legacy_data_file(temp_file):
    src_video = examples_dir.joinpath('video.mp4')
    target_video = temp_file('video.mp4')
    shutil.copy(src_video, target_video)

    src_h5 = examples_dir.joinpath('data').joinpath('video_legacy.h5')
    target_h5 = target_video.with_name('video.h5')
    shutil.copy(src_h5, target_h5)
    return target_h5


@pytest.fixture()
def raw_data_file(sample_video_file):
    data_filename = str(sample_video_file.with_suffix('.h5'))

    nix_file = nixio.File.open(data_filename, nixio.FileMode.Overwrite)
    data_file = DataFile(nix_file=nix_file)
    data_file.init_new_file()

    yield data_file

    nix_file.close()
