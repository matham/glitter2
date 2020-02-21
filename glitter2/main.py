"""Glitter2 App
=====================

The main module that provides the app that runs the GUI.
"""
from os.path import join, dirname
from typing import Iterable, List, Dict

from kivy.lang import Builder
from kivy.factory import Factory
from kivy.properties import ObjectProperty, BooleanProperty, NumericProperty
from kivy.core.window import Window
import kivy_garden.graph

from base_kivy_app.app import BaseKivyApp, run_app as run_cpl_app
from base_kivy_app.graphics import BufferImage

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

    storage_controller: StorageController = ObjectProperty(None)

    channel_controller: ChannelController = ObjectProperty(None)

    player: GlitterPlayer = ObjectProperty(None)

    image_display: BufferImage = ObjectProperty(None)

    scoring_viewer = ObjectProperty(None)
    """The widget that displays the channel status for time based channels.
    """

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
        return self.storage_controller.notify_video_change(item, value)

    def add_video_frame(self, t, image):
        self.storage_controller.add_timestamp(t)
        self.channel_controller.set_current_timestamp(t)
        self.image_display.update_img(image)

    def clear_video(self):
        self.image_display.clear_image()

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
        self.storage_controller.fbind('has_unsaved', self.set_tittle)
        self.storage_controller.fbind('config_changed', self.set_tittle)
        self.storage_controller.fbind('filename', self.set_tittle)
        self.player.fbind('filename', self.set_tittle)
        self.set_tittle()

    def set_tittle(self, *largs):
        """ Sets the title of the window.
        """
        storage_controller = self.storage_controller
        star = ''
        if storage_controller.has_unsaved or storage_controller.config_changed:
            star = '*'
        s = 'Glitter2 v{}, CPL lab.'.format(glitter2.__version__)

        video_file = self.player.filename
        h5_file = self.storage_controller.filename
        if video_file and h5_file:
            s = '{}{} {} ({})'.format(star, s, video_file, h5_file)
        elif video_file:
            s = '*{} {} Missing data file'.format(s, video_file)
        elif h5_file:
            s = '{}{} No video file ({})'.format(star, s, h5_file)
        else:
            s = '*{} No file'.format(s)

        Window.set_title(s)

    def check_close(self):
        if not self.storage_controller.ui_close(app_close=True):
            self._close_message = ''
            return False
        if self.player is not None:
            self.player.close_file()
        return True

    def clean_up(self):
        super(Glitter2App, self).clean_up()


def run_app():
    """The function that starts the GUI and the entry point for
    the main script.
    """
    return run_cpl_app(Glitter2App)
