"""Storage Controller
=======================

Handles all data aspects, from the storage, loading and saving of configuration
data to the acquisition and creation of experimental data.

Whenever we open a new file, the GUI must be cleared and old file closed.

.. list-table:: GUI file operations
   :header-rows: 1
   :stub-columns: 1

   * - Operation
     - H5 file
     - Video file
     - App data
   * - Open file (video file selected)
     - Opens file next to video or creates a new one, if not open
     - Opens video file
     - Clears and loads data from file (if it existed)
   * - Open file (h5 file selected)
     - Opens h5 file
     - Tries to open video file in same folder, if it's found and matches.
     - Clears and loads data from file
   * - Open h5 RO
     - Closes and opens the h5 file in RO mode
     - Tries to open video file in same folder, if it's found and matches.
     - Cleared and loaded from file
   * - Open video file with current h5
     - ---
     - Opens the video file (error may occur later if the file doesn't match)
     - ---
   * - Save
     - Saves unsaved data to current h5 file
     - ---
     - ---
   * - Save as
     - Saves unsaved data to new h5 file
     - Reloads
     - Reloads all the data
   * - Discard changes
     - Discards and opens last saved h5 file state
     - Reloads
     - Reloads all the data
   * - Close and clear
     - Closes h5 file and creates new black autosave
     - Closed
     - Cleared
   * - Import H5
     - ---
     - ---
     - Import the channels from the h5 file
   * - Import YAML
     - ---
     - ---
     - Import the channels from the yaml file
"""
from typing import Optional
import nixio as nix
from os.path import exists, basename, splitext, split, join, isdir, dirname, \
    abspath
from os import remove
import os
from tempfile import NamedTemporaryFile
from shutil import copy2
from functools import partial
import h5py

from kivy.event import EventDispatcher
from kivy.properties import StringProperty, NumericProperty, ListProperty, \
    DictProperty, BooleanProperty, ObjectProperty
from kivy.app import App
from kivy.clock import Clock
from kivy.logger import Logger
from kivy.lang import Builder

from more_kivy_app.app import app_error
from more_kivy_app.utils import yaml_dumps, yaml_loads

from glitter2.storage.data_file import DataFile, read_nix_prop
from glitter2.player import GlitterPlayer

__all__ = ('StorageController', )


class StorageController(EventDispatcher):
    """This class manages the nix file. It can import config from files and
    add it to the app. Or it can clear all the config and open/create
    an existing file.
    """

    _config_props_ = (
        'root_path', 'backup_interval', 'compression', 'last_filename',
        'last_filename_summary')

    root_path = StringProperty('')

    backup_interval = NumericProperty(5.)

    filename = StringProperty('')

    read_only_file = BooleanProperty(False)
    """Whether the last file opened, was opened as read only.
    """

    backup_filename = ''

    nix_file: Optional[nix.File] = None

    data_file: Optional['DataFile'] = None

    compression = StringProperty('Auto')

    has_unsaved = BooleanProperty(False)
    """Data was written to the file and we need to save it.
    """

    config_changed = BooleanProperty(False)
    """That the config changed and we need to read the config again before
    saving.
    """

    saw_all_timestamps = BooleanProperty(False)

    backup_event = None

    app = None

    channel_controller = None

    player: GlitterPlayer = None

    ruler = None

    last_filename = StringProperty('')

    last_filename_summary = StringProperty('')

    def __init__(self, app, channel_controller, player, ruler, **kwargs):
        super(StorageController, self).__init__(**kwargs)
        self.app = app
        self.channel_controller = channel_controller
        self.player = player
        self.ruler = ruler
        if (not os.environ.get('KIVY_DOC_INCLUDE', None) and
                self.backup_interval):
            self.backup_event = Clock.schedule_interval(
                partial(self.write_changes_to_autosave, scheduled=True),
                self.backup_interval)

    def update_last_filename(self, filename):
        if not filename:
            self.last_filename = ''
            self.last_filename_summary = ''
            return

        filename = abspath(filename)
        if self.last_filename == filename:
            return

        self.last_filename = filename
        self.last_filename_summary = basename(filename)

    @property
    def nix_compression(self):
        if self.compression == 'ZIP':
            return nix.Compression.DeflateNormal
        elif self.compression == 'None':
            return nix.Compression.No
        return nix.Compression.Auto

    def get_filebrowser_callback(
            self, func, ext=None, clear_data=False, **kwargs):

        def callback(paths):
            if not paths:
                return
            fname = paths[0]
            if ext and not fname.endswith(ext):
                fname += ext

            self.root_path = dirname(fname)

            @app_error
            def discard_callback(discard):
                if clear_data and not discard:
                    return

                if clear_data:
                    self.close_file(force_remove_autosave=True)
                    self.channel_controller.delete_all_channels()
                    self.player.close_file()
                func(fname, **kwargs)

            if clear_data and (self.has_unsaved or self.config_changed):
                yesno = App.get_running_app().yesno_prompt
                yesno.msg = 'There are unsaved changes.\nDiscard them?'
                yesno.callback = discard_callback
                yesno.open()
            else:
                discard_callback(True)
        return callback

    @app_error
    def ui_close(self, app_close=False):
        """The UI asked for to close a file. We create a new one if the app
        doesn't close.

        If unsaved, will prompt if want to save
        """
        if self.has_unsaved or self.config_changed:
            def close_callback(discard):
                if discard:
                    self.close_file(force_remove_autosave=True)
                    self.channel_controller.delete_all_channels()
                    self.player.close_file()

                    if app_close:
                        App.get_running_app().stop()
                    else:
                        self.create_file('')
                        # there's no data in the empty file
                        self.config_changed = self.has_unsaved = False

            yesno = App.get_running_app().yesno_prompt
            yesno.msg = ('There are unsaved changes.\n'
                         'Are you sure you want to discard them?')
            yesno.callback = close_callback
            yesno.open()
            return False
        else:
            self.close_file()
            self.channel_controller.delete_all_channels()
            self.player.close_file()

            if not app_close:
                self.create_file('')
                # there's no data in the empty file
                self.config_changed = self.has_unsaved = False
            return True

    def create_file(self, filename, overwrite=False):
        """All channels should have been cleared before opening.
        """
        self.config_changed = self.has_unsaved = True
        if exists(filename) and not overwrite:
            raise ValueError('{} already exists'.format(filename))
        self.close_file()

        self.filename = filename
        self.read_only_file = False

        if filename:
            head, tail = split(filename)
            name, ext = splitext(tail)
        else:
            if not isdir(self.root_path):
                self.root_path = os.path.expanduser('~')
            head = self.root_path
            ext = '.h5'
            name = 'default'
        temp = NamedTemporaryFile(
            suffix=ext, prefix=name + '_', dir=head, delete=False)
        self.backup_filename = temp.name
        temp.close()

        self.nix_file = nix.File.open(
            self.backup_filename, nix.FileMode.Overwrite,
            compression=self.nix_compression)
        self.data_file = DataFile(
            nix_file=self.nix_file, unsaved_callback=self.set_data_unsaved)
        Logger.debug(
            'Glitter2: Created tempfile {}, with file "{}"'.
            format(self.backup_filename, self.filename))

        self.data_file.init_new_file()
        self.channel_controller.reset_new_file(())
        self.write_changes_to_autosave()
        self.save()
        self.saw_all_timestamps = self.data_file.saw_all_timestamps

    @app_error
    def ui_open_file(self, filename, read_only=False):
        """GUI requested that the file be opened. Previously open file should
        have been closed.

        :param filename:
        :param read_only:
        """
        self.app.opened_file()
        # did we open a h5 file? try opening its video
        if h5py.h5f.is_hdf5(filename.encode()):
            self.open_file(filename, read_only=read_only)
            self.try_open_video_from_h5()
            return

        # user selected a video file
        h5_filename = self.get_h5_filename_from_video(filename)
        # is the video's h5 already open, then just open video
        if (self.filename and os.path.abspath(h5_filename) ==
                os.path.abspath(self.filename)):
            metadata = self.data_file.video_metadata_dict
            file_size = metadata.get('file_size')
            if not file_size or file_size == os.stat(filename).st_size:
                self.player.open_file(filename)
                return

        if exists(h5_filename):
            metadata = DataFile.get_file_video_metadata(h5_filename)
            file_size = metadata.get('file_size')
            if not file_size or file_size == os.stat(filename).st_size:
                self.open_file(h5_filename, read_only=read_only)
            else:
                self.create_file('')
        else:
            self.create_file(h5_filename)
        self.player.open_file(filename)

    def open_file(self, filename, read_only=False):
        """Loads the file's config and opens the file for usage.
        """
        self.config_changed = self.has_unsaved = True
        self.close_file()

        self.filename = filename
        self.read_only_file = read_only

        head, tail = split(filename)
        name, ext = splitext(tail)
        temp = NamedTemporaryFile(
            suffix=ext, prefix=name + '_', dir=head, delete=False)
        self.backup_filename = temp.name
        temp.close()

        copy2(filename, self.backup_filename)

        self.nix_file = nix.File.open(
            self.backup_filename, nix.FileMode.ReadWrite,
            compression=self.nix_compression)
        self.data_file = DataFile(
            nix_file=self.nix_file, unsaved_callback=self.set_data_unsaved)
        Logger.debug(
            'Ceed Controller (storage): Created tempfile {}, from existing '
            'file "{}"'.format(self.backup_filename, self.filename))

        self.data_file.upgrade_file()
        self.data_file.open_file()
        self.channel_controller.reset_new_file(
            self.data_file.timestamp_data_map)
        self.create_gui_channels_from_storage()
        self.ruler.pixels_per_meter = self.data_file.pixels_per_meter
        self.write_changes_to_autosave()
        self.saw_all_timestamps = self.data_file.saw_all_timestamps

    def close_file(self, force_remove_autosave=False):
        """Closes without saving the data. But if data was unsaved, it leaves
        the backup file unchanged.
        """
        if self.nix_file:
            self.nix_file.close()
            self.nix_file = None
            self.data_file = None

        if (not self.has_unsaved and not self.config_changed or
                force_remove_autosave) and self.backup_filename:
            remove(self.backup_filename)

        Logger.debug(
            'Glitter2: Closed tempfile {}, with '
            '"{}"'.format(self.backup_filename, self.filename))

        self.filename = self.backup_filename = ''
        self.read_only_file = False

    @app_error
    def import_file(self, filename, exclude_app_settings=False):
        """Loads the file's config data. """
        Logger.debug(
            'Glitter2: Importing "{}"'.format(self.filename))

        f = nix.File.open(filename, nix.FileMode.ReadOnly)
        self.has_unsaved = self.config_changed = True
        try:
            data_file_src = DataFile(nix_file=f)
            data_file_src.open_file()

            self.create_gui_channels(
                *(item.values()
                  for item in data_file_src.read_channels_config()))
            self.ruler.pixels_per_meter = data_file_src.pixels_per_meter
            if not exclude_app_settings:
                self.app.set_app_config_data(data_file_src.app_config_dict)
        finally:
            f.close()

        self.write_changes_to_autosave()
        return True

    @app_error
    def discard_file(self):
        if not self.has_unsaved and not self.config_changed:
            return

        f = self.filename
        read_only = self.read_only_file
        self.close_file(force_remove_autosave=True)
        self.channel_controller.delete_all_channels()
        if f:
            self.open_file(f, read_only=read_only)
        else:
            self.create_file('')
        self.player.reopen_file()

    @app_error
    def save_as(self, filename, overwrite=False):
        if exists(filename) and not overwrite:
            raise ValueError('{} already exists'.format(filename))
        self.save(filename, True)

        self.close_file(force_remove_autosave=True)
        self.channel_controller.delete_all_channels()

        self.open_file(filename)
        self.player.reopen_file()
        self.save()

    @app_error
    def save(self, filename=None, force=False):
        """Saves the changes to the autosave and also saves the changes to
        the file in filename (if None saves to the current filename).
        """
        if self.read_only_file and not force:
            raise TypeError(
                'Cannot save because file was opened as read only. '
                'Try saving as a new file')

        if not force and not self.has_unsaved and not self.config_changed:
            return

        self.write_changes_to_autosave()
        filename = filename or self.filename
        if filename:
            copy2(self.backup_filename, filename)
            self.has_unsaved = False

    def write_changes_to_autosave(self, *largs, scheduled=False):
        """Writes unsaved changes to the current (autosave) file. """
        if not self.nix_file or scheduled and self.read_only_file:
            return

        if self.config_changed:
            self.data_file.app_config_dict = self.app.get_app_config_data()
            self.data_file.write_channels_config(
                *self.channel_controller.get_channels_metadata())
            self.data_file.set_pixels_per_meter(self.ruler.pixels_per_meter)
            self.config_changed = False

        try:
            self.nix_file.flush()
        except AttributeError:
            self.nix_file._h5file.flush()

    @app_error
    def write_yaml_config(
            self, filename, overwrite=False, exclude_app_settings=False):
        if exists(filename) and not overwrite:
            raise ValueError('{} already exists'.format(filename))

        data = {
            'channels': self.channel_controller.get_channels_metadata(),
            'app_config': None,
            'data_config': {
                'pixels_per_meter': self.ruler.pixels_per_meter
            }
        }
        if not exclude_app_settings:
            data['app_config'] = self.app.get_app_config_data()

        data = yaml_dumps(data)
        with open(filename, 'w') as fh:
            fh.write(data)
        self.update_last_filename(filename)

    @app_error
    def import_yaml_config(self, filename, exclude_app_settings=False):
        self.config_changed = True

        with open(filename, 'r') as fh:
            data = fh.read()
        data = yaml_loads(data)

        if not exclude_app_settings and data['app_config'] is not None:
            self.app.set_app_config_data(data['app_config'])
        self.create_gui_channels(*(item.values() for item in data['channels']))

        pixels_per_meter = data.get(
            'data_config', {}).get('pixels_per_meter', None)
        if pixels_per_meter is not None:
            self.ruler.pixels_per_meter = pixels_per_meter
        self.write_changes_to_autosave()
        self.update_last_filename(filename)
        return True

    @app_error
    def import_last_file(self):
        filename = self.last_filename
        if not filename:
            return

        if filename.endswith('.h5'):
            if not self.import_file(filename, exclude_app_settings=True):
                self.update_last_filename('')
        else:
            if not self.import_yaml_config(
                    filename, exclude_app_settings=True):
                self.update_last_filename('')

    def set_data_unsaved(self):
        self.has_unsaved = True

    @app_error
    def create_gui_channels(self, event_channels, pos_channels, zone_channels):
        data_create_channel = self.data_file.create_channel
        create_channel = self.channel_controller.create_channel

        for metadata in event_channels:
            data_channel = data_create_channel('event')
            create_channel('event', data_channel, metadata)

        for metadata in pos_channels:
            data_channel = data_create_channel('pos')
            create_channel('pos', data_channel, metadata)

        for metadata in zone_channels:
            data_channel = data_create_channel('zone')
            create_channel('zone', data_channel, metadata)

    @app_error
    def create_gui_channels_from_storage(self):
        get_channel_from_id = self.data_file.get_channel_from_id
        create_channel = self.channel_controller.create_channel

        event_channels, pos_channels, zone_channels = \
            self.data_file.read_channels_config()

        for i, metadata in event_channels.items():
            data_channel = get_channel_from_id(i)
            create_channel('event', data_channel, metadata)

        for i, metadata in pos_channels.items():
            data_channel = get_channel_from_id(i)
            create_channel('pos', data_channel, metadata)

        for i, metadata in zone_channels.items():
            data_channel = get_channel_from_id(i)
            create_channel('zone', data_channel, metadata)

    @app_error
    def notify_video_change(self, item, value=None):
        if self.data_file is None:
            return

        if item == 'opened':
            metadata = self.data_file.video_metadata_dict
            if metadata:
                if 'duration' in metadata and \
                        metadata['duration'] != value['duration'] or \
                        'src_vid_size' in metadata and \
                        tuple(metadata['src_vid_size']) != \
                        tuple(value['src_vid_size']):
                    self.player.close_file()
                    raise ValueError(
                        'Video file opened is not the original video file '
                        'that created the data file. Please make sure to '
                        'open the correct video file')
                self.data_file.set_default_video_metadata(value)
            else:
                self.data_file.video_metadata_dict = value
        elif item == 'seek':
            self.data_file.notify_interrupt_timestamps()
        elif item == 'first_ts':
            self.data_file.notify_saw_first_timestamp()
        elif item == 'last_ts':
            self.data_file.notify_saw_last_timestamp()
        self.saw_all_timestamps = self.data_file.saw_all_timestamps

    def add_timestamp(self, t: float) -> float:
        conditioned_t = self.data_file.condition_timestamp(t)
        if conditioned_t is not None:
            t = conditioned_t
        self.data_file.notify_add_timestamp(t)
        self.saw_all_timestamps = self.data_file.saw_all_timestamps
        return t

    @app_error
    def try_open_video_from_h5(self):
        metadata = self.data_file.video_metadata_dict
        if 'filename_tail' not in metadata:
            return

        head = metadata['filename_head']
        tail = metadata['filename_tail']
        f_size = metadata['file_size']

        fname = join(head, tail)
        if exists(fname) and (not f_size or os.stat(fname).st_size == f_size):
            self.player.open_file(fname)
        else:
            fname = join(dirname(self.filename), tail)
            if exists(fname) and (
                    not f_size or os.stat(fname).st_size == f_size):
                self.player.open_file(fname)
        self.app.opened_file()

    def get_h5_filename_from_video(self, filename):
        head, _ = splitext(filename)
        return head + '.h5'


Builder.load_file(join(dirname(__file__), 'storage_style.kv'))
