"""Glitter2 App
=====================

The main module that provides the app that runs the GUI.
"""
from os.path import join, dirname
from typing import Iterable, List, Dict, Set
from ffpyplayer.pic import Image

from kivy.lang import Builder
from kivy.factory import Factory
from kivy.properties import ObjectProperty, BooleanProperty, NumericProperty
from kivy.core.window import Window
from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.behaviors.focus import FocusBehavior
from kivy.clock import Clock

import kivy_garden.graph
import kivy_garden.tickmarker

from tree_config import get_config_children_names

from base_kivy_app.app import BaseKivyApp, app_error, run_app as run_cpl_app
from base_kivy_app.graphics import BufferImage
from tree_config import get_config_prop_names

import glitter2
from glitter2.storage import StorageController
from glitter2.channel import ChannelController, ChannelBase, EventChannel, \
    PosChannel, ZoneChannel, Ruler
from glitter2.player import GlitterPlayer
import glitter2.player.player_widget
from glitter2.analysis.export import ExportManager
from glitter2.channel.channel_widgets import EventChannelWidget, \
    PosChannelWidget, ZoneChannelWidget, ImageDisplayWidgetManager, \
    ZonePainter, RulerWidget
from glitter2.analysis.export_widget import ExportStatsSelection

__all__ = ('Glitter2App', 'run_app', 'MainView')


class MainView(FocusBehavior, BoxLayout):
    """The root widget displayed in the GUI.
    """

    app: 'Glitter2App' = None

    keyboard_chars: Set[str] = set()

    ctrl_chars = {'lctrl', 'rctrl', 'ctrl'}

    def __int__(self, **kwargs):
        super(MainView, self).__int__(**kwargs)
        self.ctrl_chars = set()

    def on_focus(self, *args):
        if not self.focus:
            self.app.image_display_manager.clear_delete()

    def keyboard_on_key_down(self, window, keycode, text, modifiers):
        if super(MainView, self).keyboard_on_key_down(
                window, keycode, text, modifiers):
            return True
        if self.app.current_view != 'scoring':
            return False

        self.keyboard_chars.add(keycode[1])
        if 's' in self.keyboard_chars and \
                self.keyboard_chars & self.ctrl_chars:
            return True

        if self.app.interactive_player_mode:
            if self.app.player.player_on_key_down(
                    window, keycode, text, modifiers):
                return True
        else:
            if self.app.zone_painter.keyboard_on_key_down(
                    window, keycode, text, modifiers):
                return True
        return self.app.image_display_manager.root_on_key_down(
            window, keycode, text, modifiers)

    def keyboard_on_key_up(self, window, keycode):
        if keycode[1] == 'delete':
            # have to make sure that we always get the up-key for delete
            self.app.image_display_manager.clear_delete()
        if super(MainView, self).keyboard_on_key_up(window, keycode):
            return True

        if self.app.current_view != 'scoring':
            return False

        if 's' in self.keyboard_chars and \
                self.keyboard_chars & self.ctrl_chars:
            if keycode[1] in self.keyboard_chars:
                self.keyboard_chars.remove(keycode[1])

            self.app.save_data_file()
            return True

        if keycode[1] in self.keyboard_chars:
            self.keyboard_chars.remove(keycode[1])

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

    _config_children_ = {
        'storage': 'storage_controller', 'player': 'player',
        'channels': 'channel_controller', 'export': 'export_manager',
    }

    yesno_prompt = ObjectProperty(None, allownone=True)
    '''Stores a instance of :class:`YesNoPrompt` that is automatically created
    by this app class. That class is described in ``base_kivy_app/graphics.kv``.
    '''

    storage_controller: StorageController = ObjectProperty(None)

    channel_controller: ChannelController = ObjectProperty(None)

    player: GlitterPlayer = ObjectProperty(None)

    image_display: BufferImage = ObjectProperty(None)

    image_display_manager: ImageDisplayWidgetManager = None

    zone_painter: ZonePainter = None

    export_manager: ExportManager = None

    export_stats: ExportStatsSelection

    ruler: Ruler = None

    ruler_widget: RulerWidget = None

    source_item_log = None

    interactive_player_mode = BooleanProperty(True)

    current_view = 'scoring'

    ruler_active = BooleanProperty(False)

    def get_app_config_data(self):
        self.dump_app_settings_to_file()
        self.load_app_settings_from_file()
        return dict(self.app_settings)

    def set_app_config_data(self, data):
        # filter classes that are not of this app
        classes = get_config_children_names(self)
        self.app_settings = {cls: data[cls] for cls in classes}
        self.apply_app_settings()

    def create_channel(self, channel_type: str, **kwargs) -> ChannelBase:
        data_channel = self.storage_controller.data_file.create_channel(
            channel_type)
        return self.channel_controller.create_channel(
            channel_type, data_channel, **kwargs)

    def create_channel_widget(self, channel: ChannelBase):
        self.image_display_manager.create_channel_widget(channel)

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
        self.image_display_manager.delete_channel_widget(channel)

    def notify_video_change(self, item, value=None):
        if item == 'opened':
            self.channel_controller.overview_controller.set_max_duration(
                self.player.duration)
        return self.storage_controller.notify_video_change(item, value)

    def add_video_frame(self, t: float, image: Image):
        t = self.storage_controller.add_timestamp(t)
        self.channel_controller.set_current_timestamp(t)
        self.image_display.update_img(image)

    def clear_video(self):
        self.image_display.clear_image()

    def opened_file(self):
        self.ruler_active = False

    def save_data_file(self):
        if self.storage_controller.filename:
            self.storage_controller.save()
        else:
            self.save_data_file_as()

    @app_error
    def save_data_file_as(self):
        if not self.player.filename:
            raise TypeError(
                'Cannot save H5 file because video file is not open')

        self.open_filechooser(
            callback=self.storage_controller.get_filebrowser_callback(
                self.storage_controller.save_as, overwrite=True, ext='.h5'),
            mode='save', target=self.storage_controller.root_path,
            title='Save h5 file', filters=['*.h5', '*.*'])

    def build(self):
        base = dirname(glitter2.__file__)
        Builder.load_file(join(base, 'glitter2_style.kv'))

        self.ruler = Ruler()
        self.channel_controller = ChannelController(app=self)
        self.player = GlitterPlayer(app=self)
        self.storage_controller = StorageController(
            app=self, channel_controller=self.channel_controller,
            player=self.player, ruler=self.ruler)
        self.export_manager = ExportManager()

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
            for prop in get_config_prop_names(obj):
                obj.fbind(prop, self.trigger_config_updated)
        self.ruler.fbind(
            'pixels_per_meter', self.trigger_config_updated)

        self.export_stats.show_analysis_options()

        Clock.schedule_interval(self._set_window_focus, 0)
        self._set_window_focus()

        self.storage_controller.has_unsaved = False
        self.storage_controller.config_changed = False

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

    def _set_window_focus(self, *args):
        if not FocusBehavior._keyboards:
            self.root.focus = True

    def check_close(self):
        if not self.storage_controller.ui_close(app_close=True):
            self._close_message = ''
            return False
        if self.player is not None:
            self.player.close_file()
        return True

    def clean_up(self):
        super(Glitter2App, self).clean_up()

        if self.export_manager is not None:
            self.dump_app_settings_to_file()
            self.export_manager.stop()

        if self.player is not None:
            self.player.close_file()


def run_app():
    """The function that starts the GUI and the entry point for
    the main script.
    """
    return run_cpl_app(Glitter2App)
