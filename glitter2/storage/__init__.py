"""Storage Controller
=======================

Handles all data aspects, from the storage, loading and saving of configuration
data to the acquisition and creation of experimental data.

"""
from typing import Optional
import nixio as nix
from os.path import exists, basename, splitext, split, join, isdir, dirname
from os import remove
import os
from tempfile import NamedTemporaryFile
from shutil import copy2
from functools import partial

from kivy.event import EventDispatcher
from kivy.properties import StringProperty, NumericProperty, ListProperty, \
    DictProperty, BooleanProperty, ObjectProperty
from kivy.app import App
from kivy.clock import Clock
from kivy.logger import Logger

from base_kivy_app.app import app_error
from base_kivy_app.utils import yaml_dumps, yaml_loads

from glitter2.storage.data_file import DataFile, read_nix_prop

__all__ = ('StorageController', )


class StorageController(EventDispatcher):

    __config_props__ = ('root_path', 'backup_interval', 'compression')

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

    backup_event = None

    app = None

    def __init__(self, app=None, **kwargs):
        super(StorageController, self).__init__(**kwargs)
        self.app = app
        if (not os.environ.get('KIVY_DOC_INCLUDE', None) and
                self.backup_interval):
            self.backup_event = Clock.schedule_interval(
                partial(self.write_changes_to_autosave, scheduled=True),
                self.backup_interval)

    @property
    def nix_compression(self):
        if self.compression == 'ZIP':
            return nix.Compression.DeflateNormal
        elif self.compression == 'None':
            return nix.Compression.No
        return nix.Compression.Auto

    def get_filebrowser_callback(self, func, clear_data=False, **kwargs):

        def callback(paths):
            if not paths:
                return
            fname = paths[0]
            self.root_path = dirname(fname)

            def discard_callback(discard):
                if clear_data and not discard:
                    return

                if clear_data:
                    self.close_file(force_remove_autosave=True)
                    self.app.clear_config_data()
                func(fname, **kwargs)

            if clear_data and (self.has_unsaved or self.config_changed):
                yesno = App.get_running_app().yesno_prompt
                yesno.msg = 'There are unsaved changes.\nDiscard them?'
                yesno.callback = discard_callback
                yesno.open()
            else:
                discard_callback(True)
        return callback

    def ui_close(self, app_close=False):
        """The UI asked for to close a file. We create a new one if the app
        doesn't close.

        If unsaved, will prompt if want to save
        """
        if self.has_unsaved or self.config_changed:
            def close_callback(discard):
                if discard:
                    self.close_file(force_remove_autosave=True)
                    self.app.clear_config_data()
                    if app_close:
                        App.get_running_app().stop()
                    else:
                        self.create_file('')

            yesno = App.get_running_app().yesno_prompt
            yesno.msg = ('There are unsaved changes.\n'
                         'Are you sure you want to discard them?')
            yesno.callback = close_callback
            yesno.open()
            return False
        else:
            self.close_file()
            self.app.clear_config_data()
            if not app_close:
                self.create_file('')
            return True

    def create_file(self, filename, overwrite=False):
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
        self.save()

    def open_file(self, filename, read_only=False):
        """Loads the file's config and opens the file for usage. """
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
        self.app.clear_config_data()
        self.import_file(self.backup_filename)

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
        self.data_file.write_config(self.app.gather_config_data())

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

    def import_file(self, filename, exclude_app_settings=False):
        """Loads the file's config data. """
        Logger.debug(
            'Glitter2: Importing "{}"'.format(self.filename))
        data = {}
        f = nix.File.open(filename, nix.FileMode.ReadOnly)

        try:
            for prop in f.sections['app_config']:
                data[prop.name] = yaml_loads(read_nix_prop(prop))
        finally:
            f.close()

        self.has_unsaved = self.config_changed = True
        self.app.apply_config_data(
            data, exclude_app_settings=exclude_app_settings)

    def discard_file(self,):
        if not self.has_unsaved and not self.config_changed:
            return

        f = self.filename
        read_only = self.read_only_file
        self.close_file(force_remove_autosave=True)
        self.app.clear_config_data()
        if f:
            self.open_file(f, read_only=read_only)
        else:
            self.create_file('')

    def save_as(self, filename, overwrite=False):
        if exists(filename) and not overwrite:
            raise ValueError('{} already exists'.format(filename))
        self.save(filename, True)
        self.open_file(filename)
        self.save()

    def save(self, filename=None, force=False):
        """Saves the changes to the autosave and also saves the changes to
        the file in filename (if None saves to the current filename).
        """
        if self.read_only_file and not force:
            raise TypeError('Cannot save because file was opened as read only. '
                            'Try saving as a new file')

        if not force and not self.has_unsaved and not self.config_changed:
            return

        self.write_changes_to_autosave()
        filename = filename or self.filename
        if filename:
            copy2(self.backup_filename, filename)
            self.config_changed = self.has_unsaved = False

    def write_changes_to_autosave(self, *largs, scheduled=False):
        '''Writes unsaved changes to the current (autosave) file. '''
        if not self.nix_file or scheduled and self.read_only_file:
            return

        if self.config_changed:
            self.data_file.write_config(self.app.gather_config_data())

        try:
            self.nix_file.flush()
        except AttributeError:
            self.nix_file._h5file.flush()

    def write_yaml_config(
            self, filename, overwrite=False, exclude_app_settings=False):
        if exists(filename) and not overwrite:
            raise ValueError('{} already exists'.format(filename))

        data = yaml_dumps(
            self.app.gather_config_data(
                exclude_app_settings=exclude_app_settings))
        with open(filename, 'w') as fh:
            fh.write(data)

    def read_yaml_config(self, filename, exclude_app_settings=False):
        self.config_changed = True

        with open(filename, 'r') as fh:
            data = fh.read()
        data = yaml_loads(data)
        self.app.apply_config_data(
            data, exclude_app_settings=exclude_app_settings)

    def set_data_unsaved(self):
        self.has_unsaved = True
