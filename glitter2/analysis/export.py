"""Data Export
===============

"""
from typing import Dict, List, Optional
import numpy as np
from itertools import chain
from os.path import dirname, join
import os
import sys
import traceback
from threading import Thread
import time
from queue import Queue, Empty
import pathlib
import nixio as nix

from kivy.event import EventDispatcher
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.app import App
from kivy.logger import Logger

from more_kivy_app.app import app_error, report_exception_in_app
from base_kivy_app.utils import pretty_space

from glitter2.storage.imports.legacy import LegacyFileReader
from glitter2.analysis import FileDataAnalysis, AnalysisSpec
from glitter2.storage.data_file import DataFile
from glitter2.player import GlitterPlayer
from glitter2.storage.imports.clever_sys import read_clever_sys_file, \
    add_clever_sys_data_to_file
from glitter2.storage.imports.csv import read_csv, add_csv_data_to_file

__all__ = (
    'SourceFile', 'FileProcessBase', 'SummeryStatsExporter', 'RawDataExporter',
    'LegacyGlitterImporter', 'CleverSysImporter', 'CSVImporter',
    'ExportManager')


class SourceFile:

    filename: pathlib.Path = None

    file_size = 0

    source_root: pathlib.Path = None
    """The parent directory of the selected directory or file.
    """

    skip = False

    result = ''

    status = ''
    """Can be one of ``''``, ``'processing'``, ``'failed'``, or ``'done'``.
    """

    item_index = None

    exception = None

    def __init__(self, filename: pathlib.Path, source_root: pathlib.Path):
        super(SourceFile, self).__init__()
        self.filename = filename
        self.source_root = source_root
        self.file_size = filename.stat().st_size

    def get_gui_data(self):
        status = self.status or ('skipping' if self.skip else '(no status)')
        return {
            'filename.text': str(self.filename),
            'file_size.text': pretty_space(self.file_size),
            'skip.state': 'down' if self.skip else 'normal',
            'status.text': status,
            'result': self.result,
            'source_obj': self,
        }

    def pre_process(self):
        self.exception = None
        self.result = ''
        self.status = 'running'

    def post_process(self, e=None):
        if e is None:
            self.result = ''
            self.status = 'done'
        else:
            tb = ''.join(traceback.format_exception(*sys.exc_info()))
            self.result = 'Error: {}\n\n'.format(e)
            self.result += tb
            self.status = 'failed'
            self.exception = str(e), tb

    def reset_status(self):
        self.exception = None
        self.result = ''
        self.status = ''


class FileProcessBase:

    def init_process(self):
        pass

    def process_file(self, src: SourceFile):
        src.pre_process()
        try:
            res = self._process_file(src)
        except BaseException as e:
            src.post_process(e)
            res = None
        else:
            src.post_process()

        return res

    def _process_file(self, src: SourceFile):
        raise NotImplementedError

    def finish_process(self):
        pass

    def _create_or_open_data_file(
            self, src: SourceFile, target_filename, video_file, width, height,
            timestamps=None):
        existed = target_filename.exists()
        nix_file = nix.File.open(str(target_filename), nix.FileMode.ReadWrite)

        try:
            if existed:
                data_file = DataFile(nix_file=nix_file)
                data_file.open_file()
                if not data_file.saw_all_timestamps:
                    raise ValueError(
                        f'Did not watch all video frames for '
                        f'"{src.filename}" so we cannot add import data')

                metadata = data_file.video_metadata_dict
                if tuple(metadata['src_vid_size']) != (width, height):
                    raise ValueError(
                        f'Data file\'s ({src.filename}) video size '
                        f'does not match the original video file that created '
                        f'the h5 data file ({target_filename}).')

                use_src_timestamps = False
                if timestamps is not None and \
                        len(data_file.timestamps) == len(timestamps) and \
                        np.all(np.asarray(data_file.timestamps) ==
                               np.asarray(timestamps)):
                    use_src_timestamps = True

                return nix_file, data_file, use_src_timestamps

            data_file = DataFile(nix_file=nix_file)
            data_file.init_new_file()

            use_src_timestamps = timestamps is not None
            timestamps_, metadata = GlitterPlayer.get_file_data(
                str(video_file), metadata_only=use_src_timestamps)
            if not use_src_timestamps:
                timestamps = timestamps_

            data_file.set_file_data(
                video_file_metadata=metadata, saw_all_timestamps=True,
                timestamps=[timestamps], event_channels=[], pos_channels=[],
                zone_channels=[])

            data_file = DataFile(nix_file=nix_file)
            data_file.open_file()
        except BaseException:
            nix_file.close()
            raise

        return nix_file, data_file, use_src_timestamps


class SummeryStatsExporter(FileProcessBase):

    spec: AnalysisSpec = None

    export_filename: 'str' = ''

    results: list = []

    def __init__(self, spec, export_filename, **kwargs):
        super().__init__(**kwargs)
        self.spec = spec
        self.export_filename = export_filename

        if not export_filename:
            raise ValueError('No export path specified for the stats data')
        if pathlib.Path(export_filename).exists():
            raise ValueError('"{}" already exists'.format(export_filename))

        self.results = []

    def _process_file(self, src: SourceFile):
        spec = self.spec
        with FileDataAnalysis(filename=str(src.filename)) as data_file:
            data_file.load_file_data()

            self.results.append(data_file.compute_data_summary(spec))

    def finish_process(self):
        results = list(chain(*self.results))
        if not pathlib.Path(self.export_filename).parent.exists():
            pathlib.Path(self.export_filename).parent.mkdir(parents=True)
        FileDataAnalysis.export_computed_data_summary(
            self.export_filename, results)


class RawDataExporter(FileProcessBase):

    dump_zone_collider = False

    data_export_root: str = ''

    def __init__(
            self, dump_zone_collider=False, data_export_root='',
            **kwargs):
        super().__init__(**kwargs)
        self.dump_zone_collider = dump_zone_collider
        self.data_export_root = data_export_root

        if not data_export_root:
            raise ValueError('No export path specified for the raw data')

    def _process_file(self, src: SourceFile):
        with FileDataAnalysis(filename=str(src.filename)) as data_file:
            data_file.load_file_data()

            root = pathlib.Path(self.data_export_root)
            filename = root.joinpath(
                src.filename.relative_to(
                    src.source_root)).with_suffix('.xlsx')
            if not filename.parent.exists():
                filename.parent.mkdir(parents=True)
            data_file.export_raw_data_to_excel(
                str(filename), dump_zone_collider=self.dump_zone_collider)


class LegacyGlitterImporter(FileProcessBase):

    output_files_root: str = ''

    def __init__(self, output_files_root='', **kwargs):
        super().__init__(**kwargs)
        self.output_files_root = output_files_root

        if not output_files_root:
            raise ValueError('No export path specified for imported H5 files')

    def _process_file(self, src: SourceFile):
        output_files_root = pathlib.Path(self.output_files_root)
        target_filename = output_files_root.joinpath(
            src.filename.relative_to(src.source_root))

        if not target_filename.parent.exists():
            target_filename.parent.mkdir(parents=True)
        if target_filename.exists():
            raise ValueError(
                f'"{target_filename}" already exists and legacy upgrading '
                f'does not support appending')

        legacy_reader = LegacyFileReader()
        nix_file = nix.File.open(
            str(target_filename), nix.FileMode.Overwrite)
        try:
            legacy_reader.upgrade_legacy_file(str(src.filename), nix_file)
        finally:
            nix_file.close()
        return target_filename


class CleverSysImporter(FileProcessBase):

    output_files_root: str = ''

    import_append_if_file_exists = False

    def __init__(
            self, output_files_root='', import_append_if_file_exists=False,
            **kwargs):
        super().__init__(**kwargs)
        self.output_files_root = output_files_root
        self.import_append_if_file_exists = import_append_if_file_exists

        if not output_files_root:
            raise ValueError('No export path specified for imported H5 files')

    def _process_file(self, src: SourceFile):
        data, video_metadata, zones, calibration = read_clever_sys_file(
            src.filename)

        video_file = pathlib.Path(video_metadata['video_file'])
        if not video_file.exists():
            # linux and windows paths can both be parsed with PureWindowsPath,
            # but not with PurePosixPath, which fails on windows path
            video_file = src.filename.parent.joinpath(
                pathlib.PureWindowsPath(video_metadata['video_file']).name)
            if not video_file.exists():
                raise ValueError(
                    f"Could not find {video_metadata['video_file']} or "
                    f"{video_file}")

        target_filename = pathlib.Path(
            self.output_files_root).joinpath(
                src.filename.relative_to(src.source_root).with_name(
                    video_file.with_suffix('.h5').name))

        if not target_filename.parent.exists():
            target_filename.parent.mkdir(parents=True)

        if not self.import_append_if_file_exists and target_filename.exists():
            raise ValueError(
                f'"{target_filename}" already exists, skipping file')

        w = video_metadata['width']
        h = video_metadata['height']
        nix_file, data_file, src_timestamps = self._create_or_open_data_file(
            src, target_filename, video_file, w, h)

        try:
            add_clever_sys_data_to_file(
                data_file, data, video_metadata, zones, calibration)
        finally:
            nix_file.close()

        return target_filename


class CSVImporter(FileProcessBase):

    output_files_root: str = ''

    import_append_if_file_exists = False

    def __init__(
            self, output_files_root='', import_append_if_file_exists=False,
            **kwargs):
        super().__init__(**kwargs)
        self.output_files_root = output_files_root
        self.import_append_if_file_exists = import_append_if_file_exists

        if not output_files_root:
            raise ValueError('No export path specified for imported H5 files')

    def _process_file(self, src: SourceFile):
        metadata, timestamps, events, pos, zones = read_csv(str(src.filename))
        saw_all_timestamps = metadata.get('saw_all_timestamps', False)

        video_file = pathlib.Path(metadata['filename'])
        if not video_file.exists():
            # linux and windows paths can both be parsed with PureWindowsPath,
            # but not with PurePosixPath, which fails on windows path
            video_file = src.filename.parent.joinpath(
                pathlib.PureWindowsPath(metadata['filename']).name)
            if not video_file.exists():
                raise ValueError(
                    f"Could not find {metadata['filename']} or {video_file}")

        target_filename = pathlib.Path(
            self.output_files_root).joinpath(
                src.filename.relative_to(src.source_root).with_name(
                    video_file.with_suffix('.h5').name))

        if not target_filename.parent.exists():
            target_filename.parent.mkdir(parents=True)

        if not self.import_append_if_file_exists and target_filename.exists():
            raise ValueError(
                f'"{target_filename}" already exists, skipping file')

        w = metadata['video_width']
        h = metadata['video_height']
        # if we saw all the timestamps, use that instead of reading from file
        timestamps_used = timestamps if saw_all_timestamps else None
        nix_file, data_file, src_timestamps = self._create_or_open_data_file(
            src, target_filename, video_file, w, h, timestamps_used)

        try:
            add_csv_data_to_file(
                data_file, metadata, timestamps, events, pos, zones,
                src_timestamps)
        finally:
            nix_file.close()

        return target_filename


class ExportManager(EventDispatcher):

    _config_props_ = (
        'source', 'source_match_suffix', 'generated_file_output_path',
        'root_raw_data_export_path', 'stats_export_path',
        'raw_dump_zone_collider')

    num_files = NumericProperty(0)

    total_size = NumericProperty(0)

    num_processed_files = NumericProperty(0)

    num_failed_files = NumericProperty(0)

    num_skipped_files = NumericProperty(0)

    processed_size = NumericProperty(0)

    fraction_done = NumericProperty(0)
    """By memory.
    """

    elapsed_time = NumericProperty(0)

    total_estimated_time = NumericProperty(0)

    recycle_view = None

    trigger_run_in_kivy = None

    kivy_thread_queue = None

    internal_thread_queue = None

    thread = None

    thread_has_job = NumericProperty(0)

    currently_processing = BooleanProperty(False)

    source_processing = BooleanProperty(False)

    stop_op = False

    _start_processing_time = 0

    _elapsed_time_trigger = None

    source_viz = StringProperty('')

    source: pathlib.Path = pathlib.Path()

    source_match_suffix = StringProperty('*.h5')

    generated_file_output_path = StringProperty('')

    batch_mode = 'export_raw'

    batch_export_mode = 'legacy'

    root_raw_data_export_path = StringProperty('')

    raw_dump_zone_collider = BooleanProperty(True)

    stats_template_path = StringProperty('')

    stats_export_path = StringProperty('')

    source_contents: List['SourceFile'] = []

    spec: Optional[AnalysisSpec] = None

    currently_open_temp_h5_file: Optional[pathlib.Path] = None

    import_append_if_file_exists = False

    def __init__(self, **kwargs):
        super(ExportManager, self).__init__(**kwargs)
        self.source_contents = []
        self.set_source('/')

        self._elapsed_time_trigger = Clock.create_trigger(
            self._update_elapsed_time, timeout=.25, interval=True)

        def _update_fraction_done(*largs):
            if self.total_size:
                self.fraction_done = self.processed_size / self.total_size
            else:
                self.fraction_done = 0
        self.fbind('processed_size', _update_fraction_done)
        self.fbind('total_size', _update_fraction_done)

        def _update_total_estimated_time(*largs):
            if self.fraction_done:
                self.total_estimated_time = \
                    self.elapsed_time / self.fraction_done
            else:
                self.total_estimated_time = 0
        self.fbind('elapsed_time', _update_total_estimated_time)
        self.fbind('fraction_done', _update_total_estimated_time)

        self.kivy_thread_queue = Queue()
        self.internal_thread_queue = Queue()
        self.trigger_run_in_kivy = Clock.create_trigger(
            self.process_queue_in_kivy_thread)
        self.thread = Thread(
            target=self.run_thread,
            args=(self.kivy_thread_queue, self.internal_thread_queue))
        self.thread.start()

    def _update_elapsed_time(self, *largs):
        self.elapsed_time = time.perf_counter() - self._start_processing_time

    def get_config_property(self, name):
        """(internal) used by the config system to get the list of config
        sources.
        """
        if name == 'source':
            return str(self.source)
        return getattr(self, name)

    def apply_config_property(self, name, value):
        """(internal) used by the config system to set the sources.
        """
        if name == 'source':
            source = pathlib.Path(value)
            self.source = source = source.expanduser().absolute()
            self.source_viz = str(source)
        else:
            setattr(self, name, value)

    @app_error
    def set_source(self, source):
        """May only be called from Kivy thread.

        :param source: Source file/directory.
        """
        source = pathlib.Path(source)
        if not source.is_dir():
            raise ValueError

        self.source = source = source.expanduser().absolute()
        self.source_viz = str(source)
        self.clear_sources()

    def clear_sources(self):
        if self.thread_has_job:
            raise TypeError('Cannot change source while already processing')

        self.source_contents = []
        self.num_files = 0
        self.total_size = 0
        self.num_processed_files = 0
        self.processed_size = 0
        self.num_skipped_files = 0
        self.num_failed_files = 0
        self.elapsed_time = 0
        if self.recycle_view is not None:
            self.recycle_view.data = []

    @app_error
    def request_refresh_source_contents(self):
        if self.thread_has_job:
            raise TypeError('Cannot start processing while already processing')

        self.clear_sources()
        filename = App.get_running_app().storage_controller.backup_filename
        self.currently_open_temp_h5_file = None
        if filename:
            self.currently_open_temp_h5_file = pathlib.Path(filename)

        self.thread_has_job += 1
        self.stop_op = False
        self.source_processing = True
        self.internal_thread_queue.put(
            ('refresh_source_contents',
             (self.source, self.source_match_suffix)))

    def refresh_source_contents(self, source: pathlib.Path, match_suffix: str):
        contents = []
        total_size = 0
        num_files = 0
        temp_h5 = self.currently_open_temp_h5_file

        for base in source.glob('**'):
            # always be ready to stop
            if self.stop_op:
                return [], 0, 0, []

            for file in base.glob(match_suffix):
                if self.stop_op:
                    return [], 0, 0, []

                if not file.is_file():
                    continue

                if temp_h5 is not None and temp_h5 == file:
                    continue

                item = SourceFile(filename=file, source_root=source)
                num_files += 1
                total_size += item.file_size
                contents.append(item)

        gui_data = self.set_src_data_index(contents, set_index=True)
        return contents, total_size, num_files, gui_data

    @app_error
    def request_process_files(self, summary_template_file=None):
        if self.thread_has_job:
            raise TypeError('Cannot start processing while already processing')

        self.num_processed_files = 0
        self.processed_size = 0
        self.fraction_done = 0
        self.elapsed_time = 0
        self.total_estimated_time = 0
        self.num_skipped_files = 0
        self._start_processing_time = 0
        self.num_failed_files = 0
        self.elapsed_time = 0

        self.spec = None
        if self.batch_mode == 'export_stats':
            self.spec = App.get_running_app().export_stats.get_analysis_spec()

            if summary_template_file is not None:
                template = pathlib.Path(summary_template_file)
                item = SourceFile(
                    filename=template, source_root=template.parent)

                item.item_index = 0
                self.source_contents = [item]
                self.recycle_view.data = [item.get_gui_data()]

        self.thread_has_job += 1
        # the thread is not currently processing, so it's safe to reset it
        self.stop_op = False
        self.currently_processing = True

        self.internal_thread_queue.put(('process_files', None))

    @app_error
    def request_set_skip(self, obj, skip):
        # do it in thread because we need to recompute size
        if self.thread_has_job:
            raise TypeError('Cannot set skip while processing')

        self.thread_has_job += 1
        self.internal_thread_queue.put(('set_skip', (obj, skip)))

    def toggle_skip(self):
        n = len(self.source_contents)
        count = sum((src.skip for src in self.source_contents))
        if not count:
            # nothing skipped -> skip all
            state = True
        elif count == n:
            # all skipped -> skip none
            state = False
        else:
            # some are skipped -> all
            state = True

        for src in self.source_contents:
            src.skip = state

        gui_data = [item.get_gui_data() for item in self.source_contents]
        return gui_data

    @app_error
    def request_toggle_skip(self):
        # do it in thread because we need to recompute size
        if self.thread_has_job:
            raise TypeError('Cannot set skip while processing')

        self.thread_has_job += 1
        self.internal_thread_queue.put(('toggle_skip', None))

    def run_thread(self, kivy_queue, read_queue):
        kivy_queue_put = kivy_queue.put
        trigger = self.trigger_run_in_kivy
        Logger.info('Glitter2: Starting thread for ExportManager')

        while True:
            msg = ''
            try:
                msg, value = read_queue.get(block=True)
                if msg == 'eof':
                    Logger.info('Glitter2: Exiting ExportManager thread')
                    return

                if msg == 'set_skip':
                    obj, skip = value
                    obj.skip = skip
                    obj.status = ''
                    kivy_queue_put(
                        ('update_source_item',
                         (obj.item_index, obj.get_gui_data()))
                    )
                    self.compute_to_be_processed_size()
                elif msg == 'toggle_skip':
                    gui_data = self.toggle_skip()
                    kivy_queue_put(('toggle_skip', gui_data))
                    self.compute_to_be_processed_size()
                elif msg == 'refresh_source_contents':
                    res = self.refresh_source_contents(*value)
                    kivy_queue_put(('refresh_source_contents', res))
                elif msg == 'process_files':
                    self._start_processing_time = time.perf_counter()
                    self.compute_to_be_processed_size()
                    self.reset_file_status()
                    self._elapsed_time_trigger()
                    self.process_files()
            except BaseException as e:
                kivy_queue_put(
                    ('exception',
                     (str(e),
                      ''.join(traceback.format_exception(*sys.exc_info()))))
                )
                trigger()
            finally:
                kivy_queue_put(
                    ('increment', (self, 'thread_has_job', -1)))
                if msg == 'process_files':
                    self._elapsed_time_trigger.cancel()
                    kivy_queue_put(
                        ('setattr', (self, 'currently_processing', False)))
                elif msg == 'refresh_source_contents':
                    kivy_queue_put(
                        ('setattr', (self, 'source_processing', False)))
                trigger()

    @app_error
    def process_queue_in_kivy_thread(self, *largs):
        """Method that is called in the kivy thread when
        :attr:`trigger_run_in_kivy` is triggered. It reads messages from the
        thread.
        """
        while self.kivy_thread_queue is not None:
            try:
                msg, value = self.kivy_thread_queue.get(block=False)

                if msg == 'exception':
                    e, exec_info = value
                    report_exception_in_app(e, exc_info=exec_info)
                elif msg == 'setattr':
                    obj, prop, val = value
                    setattr(obj, prop, val)
                elif msg == 'setattrs':
                    for obj, prop, val in value:
                        setattr(obj, prop, val)
                elif msg == 'increment':
                    obj, prop, val = value
                    setattr(obj, prop, getattr(obj, prop) + val)
                elif msg == 'refresh_source_contents':
                    contents, total_size, num_files, gui_data = value
                    self.num_files = num_files
                    self.total_size = total_size
                    self.num_processed_files = 0
                    self.num_skipped_files = 0
                    self.num_failed_files = 0
                    self.elapsed_time = 0
                    self.processed_size = 0
                    self.source_contents = contents
                    self.recycle_view.data = gui_data
                elif msg == 'update_source_items':
                    self.recycle_view.data = value
                elif msg == 'toggle_skip':
                    self.recycle_view.data = value
                elif msg == 'update_source_item':
                    i, item = value
                    self.recycle_view.data[i] = item
                else:
                    assert False, f'Unknown message "{msg}", "{value}"'
            except Empty:
                break
            except BaseException as e:
                exc = ''.join(traceback.format_exception(*sys.exc_info()))
                report_exception_in_app(str(e), exc_info=exc)

    def set_src_data_index(
            self, source_contents=None, set_index=False) -> List[dict]:
        gui_data = [
            item.get_gui_data()
            for item in source_contents or self.source_contents]

        if set_index:
            for i, item in enumerate(gui_data):
                item['source_obj'].item_index = i
        return gui_data

    def compute_to_be_processed_size(self):
        total_size = 0
        num_files = 0
        skipped = 0
        for item in self.source_contents:
            # we don't include skipped files
            if item.skip:
                skipped += 1
                continue

            num_files += 1
            total_size += item.file_size

        self.kivy_thread_queue.put((
            'setattrs',
            [(self, 'num_files', num_files), (self, 'total_size', total_size),
             (self, 'num_processed_files', 0),
             (self, 'num_skipped_files', skipped),
             (self, 'num_failed_files', 0),
             (self, 'elapsed_time', 0),
             (self, 'processed_size', 0),
             ]
        ))
        self.trigger_run_in_kivy()

    def reset_file_status(self):
        for item in self.source_contents:
            if not item.skip:
                item.reset_status()

        self.kivy_thread_queue.put(
            ('update_source_items', self.set_src_data_index()))
        self.trigger_run_in_kivy()

    def process_files(self):
        queue_put = self.kivy_thread_queue.put
        trigger = self.trigger_run_in_kivy
        mode = self.batch_mode
        export_mode = self.batch_export_mode
        import_append_if_file_exists = self.import_append_if_file_exists

        if mode == 'export_raw':
            processor = RawDataExporter(
                dump_zone_collider=self.raw_dump_zone_collider,
                data_export_root=self.root_raw_data_export_path)
        elif mode == 'export_stats':
            processor = SummeryStatsExporter(
                spec=self.spec, export_filename=self.stats_export_path)
        else:
            assert mode == 'import'
            if export_mode == 'legacy':
                processor = LegacyGlitterImporter(
                    output_files_root=self.generated_file_output_path)
            elif export_mode == 'cleversys':
                processor = CleverSysImporter(
                    output_files_root=self.generated_file_output_path,
                    import_append_if_file_exists=import_append_if_file_exists)
            elif export_mode == 'csv':
                processor = CSVImporter(
                    output_files_root=self.generated_file_output_path,
                    import_append_if_file_exists=import_append_if_file_exists)
            else:
                assert False, export_mode

        processor.init_process()
        for item in self.source_contents:
            if self.stop_op:
                return
            if item.skip:
                queue_put(('increment', (self, 'num_skipped_files', 1)))
                trigger()
                continue

            item.status = 'running'
            queue_put(
                ('update_source_item', (item.item_index, item.get_gui_data())))
            processor.process_file(item)

            queue_put(
                ('update_source_item', (item.item_index, item.get_gui_data())))
            if item.status != 'done':
                queue_put(('increment', (self, 'num_failed_files', 1)))
            else:
                queue_put(('increment', (self, 'num_processed_files', 1)))
            queue_put(('increment', (self, 'processed_size', item.file_size)))

            if item.exception is not None:
                queue_put(('exception', item.exception))
            trigger()

        processor.finish_process()

    def stop(self):
        if self.internal_thread_queue:
            self.internal_thread_queue.put(('eof', None))
        if self.thread is not None:
            self.thread.join()

    def gui_set_path(self, item):
        """Called by the GUI to set the filename.
        """

        def set_path(paths):
            if not paths:
                return

            if item == 'source':
                self.set_source(paths[0])
            elif item == 'generated_file_output_path':
                self.generated_file_output_path = paths[0]
            elif item == 'root_raw_data_export_path':
                self.root_raw_data_export_path = paths[0]
            elif item == 'stats_export_path':
                self.stats_export_path = paths[0]
                if not self.stats_export_path.endswith('.xlsx'):
                    self.stats_export_path += '.xlsx'
            elif item == 'stats_template_path':
                self.stats_template_path = paths[0]

        return set_path


Builder.load_file(join(dirname(__file__), 'export_style.kv'))
