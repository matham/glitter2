"""Glitter2 App
=====================

The main module that provides the app that runs the GUI.
"""
import glitter2
from os.path import join, dirname

from base_kivy_app.app import BaseKivyApp, run_app as run_cpl_app

from kivy.lang import Builder
from kivy.factory import Factory
from kivy.properties import ObjectProperty, BooleanProperty, NumericProperty

from kivy.core.window import Window

from glitter2.storage import StorageController
from glitter2.channel import ChannelController

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

    def get_channels_config_data(self):
        return (), (), ()

    def clear_config_data(self):
        pass

    def apply_config_data(self, channels, app_config=None):
        """Appends channels to the channels.

        :param channels:
        :param app_config:
        :return:
        """
        if app_config:
            # filter classes that are not of this app
            classes = self.get_config_instances()
            self.app_settings = {cls: app_config[cls] for cls in classes}
            self.apply_app_settings()

    def build(self):
        base = dirname(glitter2.__file__)
        Builder.load_file(join(base, 'glitter2_style.kv'))

        self.storage_controller = StorageController(app=self)
        self.channel_controller = ChannelController()

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
