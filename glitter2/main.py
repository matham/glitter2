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
from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.behaviors.focus import FocusBehavior

import kivy_garden.graph
import kivy_garden.tickmarker

from base_kivy_app.app import BaseKivyApp, run_app as run_cpl_app
from base_kivy_app.graphics import BufferImage
from base_kivy_app.config import get_class_config_props_names

import glitter2
from glitter2.storage import StorageController
from glitter2.channel import ChannelController, ChannelBase, EventChannel, \
    PosChannel, ZoneChannel
from glitter2.player import GlitterPlayer
from glitter2.channel.channel_widgets import EventChannelWidget, \
    PosChannelWidget, ZoneChannelWidget, ImageDisplayWidgetManager, ZonePainter

__all__ = ('Glitter2App', 'run_app', 'MainView')


class MainView(FocusBehavior, BoxLayout):
    """The root widget displayed in the GUI.
    """

    app: 'Glitter2App' = None

    def on_focus(self, *args):
        if not self.focus:
            self.app.image_display_manager.clear_delete()

    def keyboard_on_key_down(self, *args, **kwargs):
        if super(MainView, self).keyboard_on_key_down(*args, **kwargs):
            return True
        if self.app.interactive_player_mode:
            if self.app.player.player_on_key_down(*args, **kwargs):
                return True
        else:
            if self.app.zone_painter.keyboard_on_key_down(*args, **kwargs):
                return True
        return self.app.image_display_manager.root_on_key_down(*args, **kwargs)

    def keyboard_on_key_up(self, window, keycode):
        if keycode[1] == 'delete':
            # have to make sure that we always get the up-key for delete
            self.app.image_display_manager.clear_delete()
        if super(MainView, self).keyboard_on_key_up(window, keycode):
            return True
        if self.app.interactive_player_mode:
            if self.app.player.player_on_key_up(window, keycode):
                return True
        else:
            if self.app.zone_painter.keyboard_on_key_up(window, keycode):
                return True
        return self.app.image_display_manager.root_on_key_up(window, keycode)


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

    event_container_widget: Widget = None

    pos_container_widget: Widget = None

    zone_container_widget: Widget = None

    image_display_manager: ImageDisplayWidgetManager = None

    zone_painter: ZonePainter = None

    interactive_player_mode = BooleanProperty(True)

    @classmethod
    def get_config_classes(cls):
        d = super(Glitter2App, cls).get_config_classes()
        d['storage'] = StorageController
        d['player'] = GlitterPlayer
        d['channels'] = ChannelController
        return d

    def get_config_instances(self):
        d = super(Glitter2App, self).get_config_instances()
        d['storage'] = self.storage_controller
        d['player'] = self.player
        d['channels'] = self.channel_controller
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

    def create_channel_widget(self, channel: ChannelBase):
        if isinstance(channel, EventChannel):
            channel.widget = widget = EventChannelWidget(
                channel=channel,
                image_display_manager=self.image_display_manager)
            self.event_container_widget.add_widget(widget)
        elif isinstance(channel, PosChannel):
            channel.widget = widget = PosChannelWidget(
                channel=channel,
                image_display_manager=self.image_display_manager)
            self.pos_container_widget.add_widget(widget)
        else:
            channel.widget = widget = ZoneChannelWidget(
                channel=channel,
                image_display_manager=self.image_display_manager)
            self.zone_container_widget.add_widget(widget)

    def delete_channel(self, channel: ChannelBase):
        self.channel_controller.delete_channel(channel)
        if isinstance(channel, ZoneChannel):
            if channel.shape is not None:
                channel.shape.channel = None
                self.image_display_manager.zone_painter.remove_shape(
                    channel.shape)

        if self.storage_controller.data_file is None:
            return
        self.storage_controller.data_file.delete_channel(
            channel.data_channel.num)

    def delete_channel_widget(self, channel: ChannelBase):
        if isinstance(channel, EventChannel):
            container = self.event_container_widget
        elif isinstance(channel, PosChannel):
            container = self.pos_container_widget
        else:
            container = self.zone_container_widget

        for widget in container.children:
            if widget.channel is channel:
                container.remove_widget(widget)
                return
        assert False

    def notify_video_change(self, item, value=None):
        if item == 'opened':
            self.channel_controller.max_duration = self.player.duration
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

        self.channel_controller = ChannelController(app=self)
        self.player = GlitterPlayer(app=self)
        self.storage_controller = StorageController(
            app=self, channel_controller=self.channel_controller,
            player=self.player)

        self.yesno_prompt = Factory.FlatYesNoPrompt()
        root = MainView()
        root.app = self
        self.channel_controller.zone_painter = \
            self.image_display_manager.zone_painter

        self.load_app_settings_from_file()
        self.apply_app_settings()

        return super(Glitter2App, self).build(root)

    def on_start(self):
        self.storage_controller.create_file('')
        self.storage_controller.fbind('has_unsaved', self.set_tittle)
        self.storage_controller.fbind('config_changed', self.set_tittle)
        self.storage_controller.fbind('filename', self.set_tittle)
        self.player.fbind('filename', self.set_tittle)
        self.set_tittle()

        for obj in (self.player, self.channel_controller,
                    self.storage_controller):
            for prop in get_class_config_props_names(obj.__class__):
                obj.fbind(prop, self.trigger_config_updated)

    def trigger_config_updated(self, *args):
        self.storage_controller.config_changed = True

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
