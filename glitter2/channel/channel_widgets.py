"""Channel widgets
==================

API for all the GUI components that display channels and channel related
objects.
"""
from os.path import join, dirname

from kivy.uix.boxlayout import BoxLayout
from kivy.properties import ObjectProperty, BooleanProperty
from kivy.lang import Builder
from kivy.factory import Factory
from kivy.uix.relativelayout import RelativeLayout
from kivy.uix.widget import Widget

from kivy_garden.painter import PaintCanvasBehavior, PaintCircle,\
    PaintEllipse, PaintPolygon, PaintFreeformPolygon

from glitter2.channel import ChannelController, ChannelBase, EventChannel, \
    PosChannel, ZoneChannel, TemporalChannel

__all__ = (
    'ImageDisplayWidgetManager', 'ZonePainter', 'PosChannelPainter',
    'ChannelWidget', 'EventChannelWidget', 'PosChannelWidget',
    'ZoneChannelWidget', 'ChannelSettingsDropDown',
    'TrackPressingButtonBehavior', 'ShowMoreBehavior')


class TrackPressingButtonBehavior(object):
    """A button that keeps track whether it's currently being pressed.
    """

    __events__ = ('on_user_pressed', 'on_user_released')

    def _do_press(self):
        super(TrackPressingButtonBehavior, self)._do_press()
        self.dispatch('on_user_pressed', self)

    def _do_release(self, *args):
        super(TrackPressingButtonBehavior, self)._do_release()
        self.dispatch('on_user_released', self)

    def on_user_pressed(self, *args):
        pass

    def on_user_released(self, *args):
        pass


class ShowMoreBehavior(object):
    """Behavior that displays or hides the :attr:`more` widget when
    :attr:`show_more` is set to True or False respectively.
    """

    show_more = BooleanProperty(False)
    '''Whether the :attr:`more` widget is displayed as a child of this
    instance or removed.
    '''

    more = ObjectProperty(None)
    '''The widget to display as a child of the instance when :attr:`show_more`
    is True.
    '''

    def __init__(self, **kwargs):
        super(ShowMoreBehavior, self).__init__(**kwargs)
        self.fbind('show_more', self._show_more)
        self._show_more()

    def _show_more(self, *largs):
        if not self.more:
            return

        if self.show_more and self.more not in self.children:
            self.add_widget(self.more)
        elif not self.show_more and self.more in self.children:
            self.remove_widget(self.more)


class ImageDisplayWidgetManager(RelativeLayout):
    """Manages all the channels in the GUI.
    """

    zone_painter: 'ZonePainter' = None

    pos_channel_painter: 'PosChannelPainter' = None

    channel_controller: ChannelController = None
    """Set from kv automatically.
    """

    def clear_delete(self):
        self.channel_controller.delete_key_pressed = False

    def root_on_key_down(self, window, keycode, text, modifiers):
        item = keycode[1]
        if item == 'delete':
            self.channel_controller.delete_key_pressed = True
            channel = self.channel_controller.selected_channel
            if channel is not None and isinstance(channel, TemporalChannel):
                channel.reset_current_value()
            return True
        elif item in self.channel_controller.event_channels_keys:
            channel: EventChannel = \
                self.channel_controller.event_channels_keys[item]
            assert channel.keyboard_key == item
            channel.key_press(True)
            return True
        elif item == 'escape':
            channel = self.channel_controller.selected_channel
            if channel is not None:
                channel.deselect_channel()
            return True

        return False

    def root_on_key_up(self, window, keycode):
        item = keycode[1]
        if item == 'delete':
            self.channel_controller.delete_key_pressed = False
            return True
        elif item in self.channel_controller.event_channels_keys:
            channel: EventChannel = \
                self.channel_controller.event_channels_keys[item]
            assert channel.keyboard_key == item
            channel.key_press(False)
            return True
        elif item == 'escape':
            return True

        return False


class ZonePainter(PaintCanvasBehavior, Widget):
    """Painter class for drawing zones in the GUI.
    """

    app = None

    def create_shape_with_touch(self, touch):
        shape = super(ZonePainter, self).create_shape_with_touch(touch)
        if shape is not None:
            shape.add_shape_to_canvas(self)
        return shape

    def add_shape(self, shape):
        if super(ZonePainter, self).add_shape(shape):
            shape.add_shape_to_canvas(self)
            if getattr(shape, 'channel', None) is None:
                shape.channel = self.app.create_channel('zone', shape=shape)
            return True
        return False

    def remove_shape(self, shape):
        if super(ZonePainter, self).remove_shape(shape):
            shape.remove_shape_from_canvas()
            channel = getattr(shape, 'channel', None)
            if channel is not None:
                self.app.delete_channel(channel)
            return True
        return False

    def select_shape(self, shape):
        if super(ZonePainter, self).select_shape(shape):
            shape.channel.widget.selected = True
            return True
        return False

    def deselect_shape(self, shape):
        if super(ZonePainter, self).deselect_shape(shape):
            shape.channel.widget.selected = False
            return True
        return False


class PosChannelPainter(Widget):
    """Widget that draws the time based position for
    :class:`~glitter2.channel.PosChannel`.
    """
    pass


class ChannelWidget(BoxLayout):
    """Widget that displays the channel in the list of channels in the GUI.
    """

    selected = BooleanProperty(False)

    image_display_manager: ImageDisplayWidgetManager = None

    channel: ChannelBase = None

    def __init__(self, channel, image_display_manager, **kwargs):
        self.channel = channel
        self.image_display_manager = image_display_manager
        super(ChannelWidget, self).__init__(**kwargs)
        channel.fbind('selected', self._monitor_channel_selection)
        self.fbind('selected', self._set_selection)

    def _monitor_channel_selection(self, *args):
        self.selected = self.channel.selected

    def _set_selection(self, *args):
        if self.selected:
            self.channel.select_channel()
        else:
            self.channel.deselect_channel()


class EventChannelWidget(ChannelWidget):
    """The widget that displays the :class:`glitter2.channel.EventChannel`.
    """

    channel: EventChannel = ObjectProperty(None)


class PosChannelWidget(ChannelWidget):
    """The widget that displays the :class:`glitter2.channel.PosChannel`.
    """

    channel: PosChannel = ObjectProperty(None)


class ZoneChannelWidget(ChannelWidget):
    """The widget that displays the :class:`glitter2.channel.ZoneChannel`.
    """

    channel: ZoneChannel = ObjectProperty(None)

    def _set_selection(self, *args):
        super(ZoneChannelWidget, self)._set_selection()
        if self.selected:
            self.image_display_manager.zone_painter.select_shape(
                self.channel.shape)
        else:
            self.image_display_manager.zone_painter.deselect_shape(
                self.channel.shape)


class ChannelSettingsDropDown(Factory.FlatDropDown):
    """Widget that shows a channel's settings as a drop down.
    """

    channel: ChannelBase = ObjectProperty(None)

    def __init__(self, channel, **kwargs):
        self.channel = channel
        super(ChannelSettingsDropDown, self).__init__(**kwargs)


Factory.register(
    classname='TrackPressingButtonBehavior', cls=TrackPressingButtonBehavior)
Factory.register(classname='ShowMoreBehavior', cls=ShowMoreBehavior)
Builder.load_file(join(dirname(__file__), 'channel_style.kv'))
