from typing import Iterable, List, Dict, Iterator, Tuple, Optional
from itertools import cycle, chain
import numpy as np

from kivy.properties import NumericProperty, ObjectProperty, StringProperty, \
    BooleanProperty
from kivy.event import EventDispatcher
from kivy.graphics.texture import Texture
from kivy.graphics import Rectangle
from kivy.app import App

from kivy_garden.painter import PaintShape

from base_kivy_app.config import read_config_from_object, apply_config, \
    get_class_config_props_names

from glitter2.storage.data_file import DataChannelBase, EventChannelData, \
    TemporalDataChannelBase, PosChannelData, ZoneChannelData
from glitter2.utils import fix_name

__all__ = ('ChannelController', 'ChannelBase', 'TemporalChannel',
           'EventChannel', 'PosChannel', 'ZoneChannel')

# matplotlib tab10 theme
_color_theme_tab10 = (
    (0.12156862745098039, 0.4666666666666667, 0.7058823529411765),
    (1.0, 0.4980392156862745, 0.054901960784313725),
    (0.17254901960784313, 0.6274509803921569, 0.17254901960784313),
    (0.8392156862745098, 0.15294117647058825, 0.1568627450980392),
    (0.5803921568627451, 0.403921568627451, 0.7411764705882353),
    (0.5490196078431373, 0.33725490196078434, 0.29411764705882354),
    (0.8901960784313725, 0.4666666666666667, 0.7607843137254902),
    (0.4980392156862745, 0.4980392156862745, 0.4980392156862745),
    (0.7372549019607844, 0.7411764705882353, 0.13333333333333333),
    (0.09019607843137255, 0.7450980392156863, 0.8117647058823529)
)


class ChannelController(EventDispatcher):

    __config_props__ = ()

    color_theme: Iterator = None

    channels: Dict[str, 'ChannelBase'] = {}

    event_channels: List['EventChannel'] = []

    pos_channels: List['PosChannel'] = []

    zone_channels: List['ZoneChannel'] = []

    overview_timestamps_index: Dict[float, int] = {}

    max_duration = 0
    """Automatically set when the video opens.
    """

    overview_width = NumericProperty(0)
    """Automatically set by the widget.
    """

    overview_num_timestamps_per_pixel = []

    overview_pixel_per_time = 0

    overview_widget = None

    n_sep_pixels_per_channel = 1

    app = None

    def __init__(self, app, **kwargs):
        super(ChannelController, self).__init__(**kwargs)
        self.color_theme = cycle(_color_theme_tab10)
        self.event_channels = []
        self.pos_channels = []
        self.zone_channels = []
        self.overview_timestamps_index = {}
        self.app = app
        self.channels = {}

        self.fbind('max_duration', self._compute_overview)
        self.fbind('overview_width', self._compute_overview)

    def set_overview_widget(self, widget):
        self.overview_widget = widget
        self._compute_overview()

    def create_channel(self, channel_type, data_channel, config=None, **kwargs):
        """Creates the requested channel as well as the widget for it.

        :param channel_type:
        :param data_channel:
        :param config:
        :param kwargs:
        :return:
        """
        if channel_type == 'event':
            cls = EventChannel
            channels = self.event_channels
        elif channel_type == 'pos':
            cls = PosChannel
            channels = self.pos_channels
        elif channel_type == 'zone':
            cls = ZoneChannel
            channels = self.zone_channels
        else:
            raise ValueError(
                'Did not understand channel type "{}"'.format(channel_type))

        if not config or 'color' not in config:
            kwargs['color'] = [int(c * 255) for c in next(self.color_theme)]
        channel = cls(data_channel=data_channel, channel_controller=self,
                      **kwargs)
        if config:
            apply_config(channel, config)
        # if it's a zone channel, kwargs would have the shape or it would be
        # reconstructed from apply_config
        channel.track_config_props_changes()

        channels.append(channel)
        channel.name = fix_name(channel.name, self.channels)
        self.channels[channel.name] = channel
        channel.fbind('name', self._change_channel_name)

        if channel_type != 'zone':
            # now display it in the overview
            if self.overview_pixel_per_time:
                w = int(self.overview_width)
                timestamps = self.overview_timestamps_index
                pixels = self.overview_num_timestamps_per_pixel
                channel.compute_modified_timestamps_count(w, timestamps, pixels)
            self._display_overview()

        self.app.create_channel_widget(channel)
        return channel

    def delete_channel(self, channel: 'ChannelBase', _recompute=True):
        if isinstance(channel, EventChannel):
            self.event_channels.remove(channel)
        elif isinstance(channel, PosChannel):
            self.pos_channels.remove(channel)
        if isinstance(channel, ZoneChannel):
            self.zone_channels.remove(channel)

        channel.funbind('name', self._change_channel_name)
        del self.channels[channel.name]

        self.app.delete_channel_widget(channel)
        if _recompute and not isinstance(channel, ZoneChannel):
            self._display_overview()

    def delete_all_channels(self):
        for channel in list(self.iterate_channels()):
            self.delete_channel(channel, _recompute=False)
        self._display_overview()

    def get_channels_metadata(self) -> Iterable[Dict[int, dict]]:
        events = {
            obj.data_channel.num: read_config_from_object(obj)
            for obj in self.event_channels
        }

        pos = {
            obj.data_channel.num: read_config_from_object(obj)
            for obj in self.pos_channels
        }

        zones = {
            obj.data_channel.num: read_config_from_object(obj)
            for obj in self.zone_channels
        }
        return events, pos, zones

    def populate_timestamps(self, timestamps):
        self.overview_timestamps_index = {t: 0 for t in timestamps}
        self._compute_overview()

    def _compute_overview(self, *args):
        duration = self.max_duration
        w = int(self.overview_width)

        if w < 2 or duration <= 0:
            self.overview_num_timestamps_per_pixel = []
            self.overview_pixel_per_time = 0

            for channel in self.event_channels:
                channel.clear_modified_timestamps_count()
            for channel in self.pos_channels:
                channel.clear_modified_timestamps_count()

            self._display_overview()
            return

        pixels = self.overview_num_timestamps_per_pixel = [0, ] * w
        self.overview_pixel_per_time = pixel_per_time = w / duration

        timestamps = self.overview_timestamps_index
        for t in timestamps:
            x = min(w - 1, max(0, int(t * pixel_per_time)))
            pixels[x] += 1
            timestamps[t] = x

        for channel in self.event_channels:
            channel.compute_modified_timestamps_count(w, timestamps, pixels)
        for channel in self.pos_channels:
            channel.compute_modified_timestamps_count(w, timestamps, pixels)
        self._display_overview()

    def _display_overview(self):
        if self.overview_widget is None:
            return

        canvas = self.overview_widget.canvas
        canvas.remove_group('overview_graphics')

        channels = [
            c for c in self.event_channels
            if c.modified_count_texture is not None and c.show_overview]
        channels += [
            c for c in self.pos_channels
            if c.modified_count_texture is not None and c.show_overview]

        if not channels:
            self.overview_widget.height = 0
            return

        pixel_sep = self.n_sep_pixels_per_channel
        n = len(channels)
        w = int(self.overview_width)
        self.overview_widget.height = n * (pixel_sep + 1)
        for i, channel in enumerate(reversed(channels)):
            y = i * (pixel_sep + 1) + pixel_sep
            with canvas:
                rect = Rectangle(pos=(0, y), size=(w, 1))
                rect.source = channel.modified_count_texture

    def set_current_timestamp(self, t):
        timestamps = self.overview_timestamps_index
        if t in timestamps:
            x = timestamps[t]
        else:
            pixels = self.overview_num_timestamps_per_pixel
            w = len(pixels)
            if w:
                pixel_per_time = self.overview_pixel_per_time
                x = min(w - 1, max(0, int(t * pixel_per_time)))
                pixels[x] += 1
                timestamps[t] = x
            else:
                x = None

        for channel in self.event_channels:
            channel.set_current_timestamp(t, x)
        for channel in self.pos_channels:
            channel.set_current_timestamp(t, x)

    def iterate_channels(self):
        for channel in self.event_channels:
            yield channel
        for channel in self.pos_channels:
            yield channel
        for channel in self.zone_channels:
            yield channel

    def _change_channel_name(self, channel: 'ChannelBase', new_name: str):
        # get the new name
        channels = self.channels
        for name, c in channels.items():
            if c is channel:
                if channel.name == name:
                    return name

                del channels[name]
                # only one change at a time happens because of binding
                break
        else:
            raise ValueError('{} has not been added'.format(channel))

        new_name = fix_name(new_name, channels)
        channels[new_name] = channel
        channel.name = new_name

        if not new_name:
            channel.name = fix_name('Channel', channels)


class ChannelBase(EventDispatcher):

    __config_props__ = ('color', 'name', 'locked', 'hidden')

    color: List[float] = ObjectProperty(None)

    locked: bool = BooleanProperty(False)

    hidden: bool = BooleanProperty(False)

    name: str = StringProperty('Channel')

    data_channel: DataChannelBase = None

    channel_controller: ChannelController = None

    def __init__(self, data_channel, channel_controller, **kwargs):
        super(ChannelBase, self).__init__(**kwargs)
        self.data_channel = data_channel
        self.channel_controller = channel_controller

    def track_config_props_changes(self):
        f = self.channel_controller.app.trigger_config_updated
        for prop in get_class_config_props_names(self.__class__):
            self.fbind(prop, f)


class TemporalChannel(ChannelBase):

    __config_props__ = ()

    overview_num_timestamps_modified_per_pixel = []

    modified_count_texture = None

    modified_count_buffer = None

    data_channel: TemporalDataChannelBase = None

    current_timestamp: Tuple[float, Optional[int]] = None

    current_value = None

    show_overview = True

    def __init__(self, **kwargs):
        super(TemporalChannel, self).__init__(**kwargs)
        self.overview_num_timestamps_modified_per_pixel = []

    def _paint_modified_count_texture(self, *largs):
        if self.modified_count_texture is None:
            return

        self.modified_count_texture.blit_buffer(
            self.modified_count_buffer.ravel(order='C'),
            colorfmt='rgb', bufferfmt='ubyte'
        )

    def clear_modified_timestamps_count(self):
        self.overview_num_timestamps_modified_per_pixel = []
        self.modified_count_texture = None
        self.modified_count_buffer = None

    def compute_modified_timestamps_count(
            self, n, overview_timestamps_index, num_timestamps_per_pixel):
        pixels = self.overview_num_timestamps_modified_per_pixel = [0, ] * n
        texture = self.modified_count_texture = Texture.create(
            size=(1, n), colorfmt='rgb',
            callback=self._paint_modified_count_texture)
        buff = self.modified_count_buffer = np.zeros((n, 3), dtype=np.uint8)

        for t, v in self.data_channel.get_timestamps_modified_state().items():
            if not v:
                pixels[overview_timestamps_index[t]] += 1

        full_color = np.array(self.color, dtype=np.uint8)
        partial_color = np.array(
            [int(c * .4) for c in self.color], dtype=np.uint8)

        i = 0
        # initially, find the first non-zero pixel to be colored
        while i < n and not pixels[i]:
            i += 1

        while i < n:
            assert 0 < pixels[i] <= num_timestamps_per_pixel[i]
            if pixels[i] == num_timestamps_per_pixel[i]:
                color = full_color
            else:
                color = partial_color
            buff[i, :] = color

            i += 1
            # fill in until the next non-zero pixel-timestamps
            while i < n and not num_timestamps_per_pixel[i]:
                assert not pixels[i]
                buff[i, :] = color
                i += 1

            # now, find the next non-zero pixel to be colored
            while i < n and not pixels[i]:
                i += 1

        texture.blit_buffer(
            buff.ravel(order='C'), colorfmt='rgb', bufferfmt='ubyte')

    def set_current_timestamp(self, t: float, index: Optional[int]):
        self.current_timestamp = t, index
        self.current_value = self.data_channel.get_timestamp_value(t)

    def change_current_value(self, value):
        # first set the value
        self.current_value = value
        modified = self.data_channel.set_timestamp_value(
            self.current_timestamp[0], value)
        if modified:
            val = 1
        else:
            val = -1

        # now change the display
        t, i = self.current_timestamp
        if i is None:  # no display available
            return

        num_timestamps_per_pixel = \
            self.channel_controller.overview_num_timestamps_per_pixel
        pixels = self.overview_num_timestamps_modified_per_pixel
        texture = self.modified_count_texture
        buff = self.modified_count_buffer
        if texture is None:
            return
        n = len(pixels)

        pixels[i] += val
        assert num_timestamps_per_pixel[i]
        assert 0 <= pixels[i] <= num_timestamps_per_pixel[i]

        # set current color
        if pixels[i] == num_timestamps_per_pixel[i]:
            color = self.color
        elif not pixels[i]:
            color = [0, 0, 0]
        else:
            color = [int(c * .4) for c in self.color]
        buff[i, :] = color

        i += 1
        # fill in until the next non-zero pixel-timestamps
        while i < n and not num_timestamps_per_pixel[i]:
            assert not pixels[i]
            buff[i, :] = color
            i += 1

        texture.blit_buffer(
            buff.ravel(order='C'), colorfmt='rgb', bufferfmt='ubyte')


class EventChannel(TemporalChannel):

    __config_props__ = ('keyboard_key', )

    keyboard_key: str = StringProperty('')

    data_channel: EventChannelData = None

    def __init__(self, **kwargs):
        super(EventChannel, self).__init__(**kwargs)

    def set_current_value(self, value):
        if value == self.current_value:
            return
        self.change_current_value(value)


class PosChannel(TemporalChannel):

    data_channel: PosChannelData = None


class ZoneChannel(ChannelBase):

    data_channel: ZoneChannelData = None

    shape: PaintShape = ObjectProperty(None)

    def get_config_properties(self):
        return {'shape_config': self.shape.get_state()}

    def apply_config_properties(self, settings):
        if 'shape_config' in settings:
            painter = App.get_running_app().image_display_manager.zone_painter
            self.shape = shape = painter.create_shape_from_state(
                settings['shape_config'], add=False)
            shape.channel = self
            painter.add_shape(shape)
            return {'shape_config'}
        return set()

    def track_config_props_changes(self):
        super(ZoneChannel, self).track_config_props_changes()
        f = self.channel_controller.app.trigger_config_updated
        assert self.shape is not None
        self.shape.fbind('on_update', f)
