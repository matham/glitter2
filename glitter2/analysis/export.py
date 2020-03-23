
from typing import Dict, List
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
from kivy.logger import Logger

from base_kivy_app.app import app_error, report_exception_in_app

from glitter2.storage.legacy import LegacyFileReader
from glitter2.analysis import FileDataAnalysis


class SourceFile(object):

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

    accumulated_stats = None

    def __init__(self, filename: pathlib.Path, source_root: pathlib.Path):
        super(SourceFile, self).__init__()
        self.filename = filename
        self.source_root = source_root
        self.file_size = filename.stat().st_size

    def get_data(self):
        return {
            'filename': str(self.filename),
            'file_size': self.file_size,
            'skip': self.skip,
            'status': self.status,
            'result': self.result,
            'source_obj': self,
        }

    def process_file(
            self, legacy_upgrade_path: str = None,
            root_raw_data_export_path: str = None, **kwargs):
        self.exception = None
        self.accumulated_stats = None

        try:
            source_file = self.filename
            if legacy_upgrade_path:
                source_file = self._upgrade_file(legacy_upgrade_path)

            self._export_file(
                source_file,
                root_raw_data_export_path=root_raw_data_export_path, **kwargs)
        except BaseException as e:
            tb = ''.join(traceback.format_exception(*sys.exc_info()))
            self.result = 'Error: {}\n\n'.format(e)
            self.result += tb
            self.status = 'failed'
            self.exception = str(e), tb
        else:
            self.result = ''
            self.status = 'done'

    def _export_file(
            self, filename: pathlib.Path,
            root_raw_data_export_path: str = None,
            **kwargs):
        analysis = FileDataAnalysis(filename=str(filename))

        try:
            analysis.load_data()

            if root_raw_data_export_path:
                root = pathlib.Path(root_raw_data_export_path)
                raw_filename = root.joinpath(
                    self.filename.relative_to(
                        self.source_root)).with_suffix('.xlsx')
                analysis.export_raw_data_to_excel(str(raw_filename))

            self.accumulated_stats = analysis.get_named_statistics(**kwargs)
        finally:
            analysis.close()

    def _upgrade_file(self, legacy_upgrade_path):
        legacy_upgrade_path = pathlib.Path(legacy_upgrade_path)
        target_filename = legacy_upgrade_path.joinpath(
            self.filename.relative_to(self.source_root))

        if not target_filename.parent.exists():
            os.makedirs(str(target_filename.parent))
        if target_filename.exists():
            raise ValueError('"{}" already exists'.format(target_filename))

        legacy_reader = LegacyFileReader()
        nix_file = nix.File.open(str(target_filename), nix.FileMode.Overwrite)
        try:
            legacy_reader.upgrade_legacy_file(str(self.filename), nix_file)
        finally:
            nix_file.close()
        return target_filename


class ExportManager(EventDispatcher):

    __config_props__ = (
        'source', 'source_match_suffix', 'legacy_upgrade_path',
        'root_raw_data_export_path', 'stats_export_path')

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

    stop_op = False

    _start_processing_time = 0

    _elapsed_time_trigger = None

    source_viz = StringProperty('')

    source: pathlib.Path = pathlib.Path()

    source_match_suffix = StringProperty('*.h5')

    legacy_upgrade_path = StringProperty('')

    upgrade_legacy_files = BooleanProperty(False)

    events_stats: Dict[str, dict] = {
        'active_duration': {}, 'delay_to_first': {}, 'scored_duration': {},
        'event_count': {}
    }

    pos_stats: Dict[str, dict] = {}

    zones_stats: Dict[str, dict] = {}

    export_raw_data = BooleanProperty(False)

    root_raw_data_export_path = StringProperty('')

    export_stats_data = BooleanProperty(False)

    stats_export_path = StringProperty('')

    source_contents: List['SourceFile'] = []

    source_processing = BooleanProperty(False)

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
        # self.fbind('elapsed_time', _update_total_estimated_time)
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

    def get_config_properties(self):
        """(internal) used by the config system to get the list of config
        sources.
        """
        return {'source': str(self.source)}

    def apply_config_properties(self, settings):
        """(internal) used by the config system to set the sources.
        """
        if 'source' in settings:
            source = pathlib.Path(settings['source'])
            self.source = source = source.expanduser().absolute()
            self.source_viz = str(source)
            return {'source', }
        return set()

    @app_error
    def set_source(self, source):
        """May only be called from Kivy thread.

        :param source: Source file/directory.
        """
        source = pathlib.Path(source)
        self.source = source = source.expanduser().absolute()
        self.source_viz = str(source)
        if not source.is_dir():
            raise ValueError

        self.source_contents = []

    @app_error
    def request_refresh_source_contents(self):
        if self.thread_has_job:
            raise TypeError('Cannot start processing while already processing')
        self.thread_has_job += 1
        self.stop_op = False
        self.source_processing = True
        self.source_contents = []
        self.internal_thread_queue.put(
            ('refresh_source_contents',
             (self.source, self.source_match_suffix)))

    def refresh_source_contents(self, source, match_suffix):
        contents = []
        total_size = 0
        num_files = 0
        for base in source.glob('**'):
            if self.stop_op:
                return [], 0, 0, []
            for file in base.glob(match_suffix):
                if self.stop_op:
                    return [], 0, 0, []

                if not file.is_file():
                    continue

                item = SourceFile(filename=file, source_root=source)
                num_files += 1
                total_size += item.file_size
                contents.append(item)

        items = self.flatten_files(contents, set_index=True)
        return contents, total_size, num_files, items

    @app_error
    def request_export_files(self):
        if self.thread_has_job:
            raise TypeError('Cannot start processing while already processing')
        self.thread_has_job += 1
        # the thread is not currently processing, so it's safe to reset it
        self.stop_op = False
        self.currently_processing = True

        self.num_processed_files = 0
        self.processed_size = 0
        self.fraction_done = 0
        self.elapsed_time = 0
        self.total_estimated_time = 0
        self.num_skipped_files = 0
        self._start_processing_time = 0
        self.num_failed_files = 0
        self.internal_thread_queue.put(('export_files', None))

    @app_error
    def request_set_skip(self, obj, skip):
        if self.thread_has_job:
            raise TypeError('Cannot set skip while processing')
        self.thread_has_job += 1
        self.internal_thread_queue.put(('set_skip', (obj, skip)))

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
                    kivy_queue_put(
                        ('update_source_item', (obj.item_index, obj.get_data()))
                    )
                    self.compute_to_be_processed_size()
                elif msg == 'refresh_source_contents':
                    res = self.refresh_source_contents(*value)
                    kivy_queue_put(('refresh_source_contents', res))
                elif msg == 'export_files':
                    self._start_processing_time = time.perf_counter()
                    self.compute_to_be_processed_size()
                    self.reset_file_status()
                    self._elapsed_time_trigger()
                    self.export_files()
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
                if msg == 'export_files':
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
                elif msg == 'increment':
                    obj, prop, val = value
                    setattr(obj, prop, getattr(obj, prop) + val)
                elif msg == 'refresh_source_contents':
                    contents, total_size, num_files, items = value
                    self.num_files = num_files
                    self.total_size = total_size
                    self.source_contents = contents
                    self.recycle_view.data = items
                elif msg == 'update_source_items':
                    self.recycle_view.data = value
                elif msg == 'update_source_item':
                    i, item = value
                    self.recycle_view.data[i] = item
                else:
                    print('Got unknown ExportManager message', msg, value)
            except Empty:
                break
            except BaseException as e:
                exc = ''.join(traceback.format_exception(*sys.exc_info()))
                report_exception_in_app(str(e), exc_info=exc)

    def flatten_files(
            self, source_contents=None, set_index=False) -> List[dict]:
        items = [item.get_data()
                 for item in source_contents or self.source_contents]

        if set_index:
            for i, item in enumerate(items):
                item['source_obj'].item_index = i
        return items

    def compute_to_be_processed_size(self):
        total_size = 0
        num_files = 0
        for item in self.source_contents:
            # we don't include skipped files
            if item.skip:
                continue
            num_files += 1
            total_size += item.file_size

        self.kivy_thread_queue.put(('setattr', (self, 'num_files', num_files)))
        self.kivy_thread_queue.put(
            ('setattr', (self, 'total_size', total_size)))
        self.trigger_run_in_kivy()

    def reset_file_status(self):
        for item in self.source_contents:
            if not item.skip:
                item.result = item.status = ''
        self.kivy_thread_queue.put(
            ('update_source_items', self.flatten_files()))
        self.trigger_run_in_kivy()

    def export_files(self):
        queue_put = self.kivy_thread_queue.put
        trigger = self.trigger_run_in_kivy

        if self.export_raw_data:
            root_raw_data_export_path = self.root_raw_data_export_path
            if not root_raw_data_export_path:
                raise ValueError('No export path specified for the raw data')
        else:
            root_raw_data_export_path = ''

        if self.export_stats_data:
            stats_export_path = self.stats_export_path
            if not stats_export_path:
                raise ValueError('No export path specified for the stats data')
        else:
            stats_export_path = '' \
                                ''
        accumulated_stats = []
        if stats_export_path:
            stats_kwargs = {
                'events': self.events_stats,
                'pos': self.pos_stats,
                'zones': self.zones_stats
            }
        else:
            stats_kwargs = {}

        for item in self.source_contents:
            if self.stop_op:
                return
            if item.skip:
                queue_put(('increment', (self, 'num_skipped_files', 1)))
                trigger()
                continue

            legacy_upgrade_path = self.legacy_upgrade_path
            if legacy_upgrade_path and self.upgrade_legacy_files:
                legacy_upgrade_path = pathlib.Path(legacy_upgrade_path)
            else:
                legacy_upgrade_path = None

            item.process_file(
                legacy_upgrade_path,
                root_raw_data_export_path=root_raw_data_export_path,
                **stats_kwargs)
            if item.accumulated_stats is not None:
                accumulated_stats.append(item.accumulated_stats)

            queue_put(
                ('update_source_item', (item.item_index, item.get_data())))
            if item.status != 'done':
                queue_put(('increment', (self, 'num_failed_files', 1)))
            queue_put(('increment', (self, 'num_processed_files', 1)))
            queue_put(
                ('increment', (self, 'processed_size', item.file_size)))
            if item.exception is not None:
                queue_put(('exception', item.exception))
            trigger()

        if stats_export_path:
            FileDataAnalysis.export_accumulated_named_statistics(
                stats_export_path, accumulated_stats)

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
            elif item == 'legacy_upgrade_path':
                self.legacy_upgrade_path = paths[0]
            elif item == 'root_raw_data_export_path':
                self.root_raw_data_export_path = paths[0]
            elif item == 'stats_export_path':
                self.stats_export_path = paths[0]
                if not self.stats_export_path.endswith('.xlsx'):
                    self.stats_export_path += '.xlsx'

        return set_path


Builder.load_file(join(dirname(__file__), 'export_style.kv'))