from typing import Iterable, List, Dict, Iterator, Tuple
from itertools import cycle, chain
import numpy as np

from kivy.properties import NumericProperty, ObjectProperty, StringProperty, \
    BooleanProperty
from kivy.event import EventDispatcher
from kivy.graphics.texture import Texture

from base_kivy_app.config import read_config_from_object

from glitter2.storage.data_file import DataChannelBase, EventChannelData, \
    TemporalDataChannelBase, PosChannelData, ZoneChannelData

__all__ = ('ChannelController', 'ChannelBase', 'EventChannel', 'PosChannel',
           'ZoneChannel')

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

    event_channels: List['EventChannel'] = []

    pos_channels: List['PosChannel'] = []

    zone_channels: List['ZoneChannel'] = []

    overview_timestamps_index: Dict[float, int] = {}

    max_duration = 0

    overview_width = NumericProperty(0)

    overview_num_timestamps_per_pixel = []

    overview_pixel_per_time = 0

    def __init__(self, **kwargs):
        super(ChannelController, self).__init__(**kwargs)
        self.color_theme = cycle(_color_theme_tab10)
        self.event_channels = []
        self.pos_channels = []
        self.zone_channels = []
        self.overview_timestamps_index = {}

        self.fbind('max_duration', self._compute_overview)
        self.fbind('overview_width', self._compute_overview)

    def create_channel(self, channel_type, data_channel, **kwargs):
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

        if 'color' not in kwargs:
            kwargs['color'] = [int(c * 255) for c in next(self.color_theme)]
        channel = cls(
            data_channel=data_channel, channel_controller=self, **kwargs)
        channels.append(channel)
        return channel

    def delete_channel(self, channel: 'ChannelBase'):
        if channel in self.event_channels:
            self.event_channels.remove(channel)
        if channel in self.pos_channels:
            self.pos_channels.remove(channel)
        if channel in self.zone_channels:
            self.zone_channels.remove(channel)

    def delete_all_channels(self):
        del self.event_channels[:]
        del self.pos_channels[:]
        del self.zone_channels[:]

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
            for obj in self.event_channels
        }
        return events, pos, zones

    def populate_timestamps(self, timestamps):
        self.overview_timestamps_index = {t: 0 for t in timestamps}
        self._compute_overview()

    def _compute_overview(self):
        duration = self.max_duration
        w = int(self.overview_width)
        if w < 2 or duration <= 0:
            self.overview_num_timestamps_per_pixel = []
            self.overview_pixel_per_time = 0
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


class ChannelBase(EventDispatcher):

    __config_props__ = ('color', 'name', 'locked', 'hidden')

    color: List[float] = ObjectProperty(None)

    locked: bool = BooleanProperty(False)

    hidden: bool = BooleanProperty(False)

    name: str = StringProperty('')

    data_channel: DataChannelBase = None

    channel_controller: ChannelController = None

    def __init__(self, data_channel, channel_controller, **kwargs):
        super(ChannelBase, self).__init__(**kwargs)
        self.data_channel = data_channel
        self.channel_controller = channel_controller


class TemporalChannel(ChannelBase):

    __config_props__ = ()

    overview_num_timestamps_modified_per_pixel = []

    modified_count_texture = None

    modified_count_buffer = None

    data_channel: TemporalDataChannelBase = None

    current_timestamp: Tuple[float, int] = None

    current_value = None

    def __init__(self, **kwargs):
        super(TemporalChannel, self).__init__(**kwargs)
        self.overview_num_timestamps_modified_per_pixel = []

    def _paint_modified_count_texture(self, *largs):
        self.modified_count_texture.blit_buffer(
            self.modified_count_buffer.ravel(order='C'),
            colorfmt='rgb', bufferfmt='ubyte'
        )

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

    def set_current_timestamp(self, t: float, index: int):
        self.current_timestamp = t, index
        self.current_value = self.data_channel.get_timestamp_value(t)

    def change_current_value(self, value):
        self.current_value = value
        modified = self.data_channel.set_timestamp_value(
            self.current_timestamp[0], value)
        if modified:
            val = 1
        else:
            val = -1

        t, i = self.current_timestamp
        num_timestamps_per_pixel = \
            self.channel_controller.overview_num_timestamps_per_pixel
        pixels = self.overview_num_timestamps_modified_per_pixel
        texture = self.modified_count_texture
        buff = self.modified_count_buffer
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
