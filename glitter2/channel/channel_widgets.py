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
    PosChannel, ZoneChannel


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

    zone_painter: 'ZonePainter' = None

    pos_channel_painter: 'PosChannelPainter' = None

    def root_on_key_down(self, window, keycode, text, modifiers):
        print(keycode, text, modifiers)
        return False

    def root_on_key_up(self, window, keycode):
        print(keycode)
        return False


class ZonePainter(PaintCanvasBehavior, Widget):

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
            return True
        return False

    def deselect_shape(self, shape):
        if super(ZonePainter, self).deselect_shape(shape):
            return True
        return False


class PosChannelPainter(Widget):
    pass


class ChannelWidget(BoxLayout):

    def __init__(self, channel, **kwargs):
        self.channel = channel
        super(ChannelWidget, self).__init__(**kwargs)


class EventChannelWidget(ChannelWidget):

    channel: EventChannel = ObjectProperty(None)


class PosChannelWidget(ChannelWidget):

    channel: PosChannel = ObjectProperty(None)


class ZoneChannelWidget(ChannelWidget):

    channel: ZoneChannel = ObjectProperty(None)


Factory.register(classname='ShowMoreBehavior', cls=ShowMoreBehavior)
Builder.load_file(join(dirname(__file__), 'channel_style.kv'))
