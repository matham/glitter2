"""Glitter2 App
=====================

The main module that provides the app that runs the GUI.
"""
from os.path import join, dirname
from typing import Iterable, List, Dict
from base_kivy_app.app import BaseKivyApp, run_app as run_cpl_app

from kivy.lang import Builder
from kivy.factory import Factory
from kivy.properties import ObjectProperty, BooleanProperty, NumericProperty

from kivy.core.window import Window

import glitter2
from glitter2.storage import StorageController
from glitter2.channel import ChannelController, ChannelBase
from glitter2.player import GlitterPlayer

__all__ = ('Glitter2App', 'run_app')


class Glitter2App(BaseKivyApp):
    """The app which runs the GUI.
    """

    __config_props__ = ()

    yesno_prompt = ObjectProperty(None, allownone=True)
    '''Stores a instance of :class:`YesNoPrompt` that is automatically created
    by this app class. That class is described in ``base_kivy_app/graphics.kv``.
    '''

    storage_controller: StorageController = None

    channel_controller: ChannelController = None

    player: GlitterPlayer = None

    @classmethod
    def get_config_classes(cls):
        d = super(Glitter2App, cls).get_config_classes()
        return d

    def get_config_instances(self):
        d = super(Glitter2App, self).get_config_instances()
        return d

    def get_app_config_data(self):
        self.dump_app_settings_to_file()
        self.load_app_settings_from_file()
        return dict(self.app_settings)

    def set_app_config_data(self, data):
        # filter classes that are not of this app
        classes = self.get_config_instances()
        self.app_settings = {cls: data[cls] for cls in classes}
        self.apply_app_settings()

    def create_channel(self, channel_type: str, **kwargs) -> ChannelBase:
        data_channel = self.storage_controller.data_file.create_channel(
            channel_type)
        return self.channel_controller.create_channel(
            channel_type, data_channel, **kwargs)

    def delete_channel(self, channel: ChannelBase):
        self.channel_controller.delete_channel(channel)
        if self.storage_controller.data_file is None:
            return
        self.storage_controller.data_file.delete_channel(
            channel.data_channel.num)

    def notify_video_change(self, item, value=None):
        if self.storage_controller.data_file is None:
            return
        if item == 'opened':
            self.storage_controller.data_file.set_video_metadata(value)
        elif item == 'seek':
            self.storage_controller.data_file.notify_interrupt_timestamps()
        elif item == 'first_ts':
            self.storage_controller.data_file.notify_saw_first_timestamp()
        elif item == 'last_ts':
            self.storage_controller.data_file.notify_saw_last_timestamp()

    def add_video_frame(self, t, image):
        self.storage_controller.data_file.add_timestamp(t)
        self.channel_controller.set_current_timestamp(t)

    def build(self):
        base = dirname(glitter2.__file__)
        Builder.load_file(join(base, 'glitter2_style.kv'))

        self.channel_controller = ChannelController()
        self.player = GlitterPlayer(app=self)
        self.storage_controller = StorageController(
            app=self, channel_controller=self.channel_controller,
            player=self.player)

        self.yesno_prompt = Factory.FlatYesNoPrompt()
        root = Factory.get('MainView')()

        self.load_app_settings_from_file()
        self.apply_app_settings()

        return super(Glitter2App, self).build(root)

    def on_start(self):
        self.set_tittle()

    def set_tittle(self, *largs):
        """ Sets the title of the window.
        """
        Window.set_title('Glitter2 v{}, CPL lab'.format(glitter2.__version__))

    def check_close(self):
        if not self.ceed_data.ui_close(app_close=True):
            self._close_message = ''
            return False
        return True

    def clean_up(self):
        super(Glitter2App, self).clean_up()


def run_app():
    """The function that starts the GUI and the entry point for
    the main script.
    """
    return run_cpl_app(Glitter2App)
