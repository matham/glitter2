"""Channels
===========
API for a channel controller as well as the channel types that the user can
create. E.g. an event channel, a position based channel, etc.
"""
from typing import Iterable, List, Dict, Iterator, Tuple, Optional
from itertools import cycle, chain
import numpy as np
from collections import defaultdict

from kivy.properties import NumericProperty, ObjectProperty, StringProperty, \
    BooleanProperty, ListProperty
from kivy.event import EventDispatcher
from kivy.graphics.texture import Texture
from kivy.graphics import Rectangle, Color

from kivy_garden.painter import PaintShape, PaintCanvasBehaviorBase

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
    """Manages all the channels shown to the user.
    """

    __config_props__ = ('n_sep_pixels_per_channel', 'n_pixels_per_channel')

    color_theme: Iterator = None

    channels: Dict[str, 'ChannelBase'] = {}

    event_channels: List['EventChannel'] = []

    pos_channels: List['PosChannel'] = []

    zone_channels: List['ZoneChannel'] = []

    overview_timestamps_index: Dict[float, int] = {}

    max_duration = NumericProperty(0)
    """Automatically set when the video opens.
    """

    overview_width = NumericProperty(0)
    """Automatically set by the widget.
    """

    overview_num_timestamps_per_pixel: list = []

    overview_pixel_per_time: float = 0

    overview_widget = None

    n_sep_pixels_per_channel: int = 1

    n_pixels_per_channel: int = 1

    app = None

    zone_painter: PaintCanvasBehaviorBase = None

    event_channels_keys: Dict[str, 'EventChannel'] = {}

    channel_temporal_back_selection_color = .45, .45, .45, 1

    selected_channel: Optional['ChannelBase'] = None

    delete_key_pressed = False

    event_groups: Dict[str, List['EventChannel']] = {}

    def __init__(self, app, **kwargs):
        super(ChannelController, self).__init__(**kwargs)
        self.color_theme = cycle(_color_theme_tab10)
        self.event_channels = []
        self.pos_channels = []
        self.zone_channels = []
        self.overview_timestamps_index = {}
        self.app = app
        self.channels = {}

        from kivy.metrics import dp
        self.n_sep_pixels_per_channel = int(dp(3))
        self.n_pixels_per_channel = int(dp(5))

        self.fbind('max_duration', self._compute_overview)
        self.fbind('overview_width', self._compute_overview)

    def set_overview_widget(self, widget):
        self.overview_widget = widget
        self._compute_overview()

    def create_channel(self, channel_type, data_channel, config=None, **kwargs):
        """Creates the requested channel as well as the widget for it.

        If the channel is created from the GUI, config is not passed in, but
        shape must be passed a kwarg for a zone channel. Otherwise, the shape
        is created from the config.

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
            kwargs['color_gl'] = next(self.color_theme)
            kwargs['color'] = [int(c * 255) for c in kwargs['color_gl']]
        channel = cls(data_channel=data_channel, channel_controller=self,
                      **kwargs)
        if config:
            apply_config(channel, config)
        # if it's a zone channel, kwargs would have the shape or it would be
        # reconstructed from apply_config
        if self.app is not None:
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

            if channel_type == 'event':
                channel.fbind('keyboard_key', self._track_event_key)
                channel.fbind('channel_group', self._track_event_group)
                self._track_event_group()
                self._track_event_key()

        if self.app is not None:
            self.app.create_channel_widget(channel)
        return channel

    def delete_channel(self, channel: 'ChannelBase', _recompute=True):
        if isinstance(channel, EventChannel):
            self.event_channels.remove(channel)
            channel.funbind('keyboard_key', self._track_event_key)
            channel.funbind('channel_group', self._track_event_group)
            channel.clear_modified_timestamps_count()
            self._track_event_group()
            self._track_event_key()
        elif isinstance(channel, PosChannel):
            self.pos_channels.remove(channel)
        elif isinstance(channel, ZoneChannel):
            self.zone_channels.remove(channel)

        channel.funbind('name', self._change_channel_name)
        del self.channels[channel.name]

        if self.app is not None:
            self.app.delete_channel_widget(channel)

        if isinstance(channel, ZoneChannel):
            # always delete the shape from the painter
            painter = self.zone_painter
            if channel.shape is not None:
                channel.shape.channel = None
                painter.remove_shape(channel.shape)
                channel.shape = None
        else:
            if _recompute:
                self._display_overview()

    def delete_all_channels(self):
        for channel in list(self.iterate_channels()):
            self.delete_channel(channel, _recompute=False)
        self._display_overview()

    def _track_event_key(self, *args):
        self.event_channels_keys = {
            c.keyboard_key: c for c in self.event_channels if c.keyboard_key}

    def _track_event_group(self, *args):
        groups = defaultdict(list)
        for c in self.event_channels:
            if c.channel_group:
                groups[c.channel_group].append(c)
        self.event_groups = groups

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
        """Seeds timestamps before any channels are created from file.

        :param timestamps:
        :return:
        """
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

        if not self.overview_num_timestamps_per_pixel:
            self.overview_widget.height = 0
            return

        channels = [
            c for c in chain(self.event_channels, self.pos_channels)
            if c.show_overview
        ]

        if not channels:
            self.overview_widget.height = 0
            return

        canvas = self.overview_widget.canvas
        pixel_sep = self.n_sep_pixels_per_channel
        pixel_h = self.n_pixels_per_channel
        n = len(channels)
        w = int(self.overview_width)
        self.overview_widget.height = n * (pixel_sep + pixel_h) + pixel_sep

        for i, channel in enumerate(reversed(channels)):
            offset = i * (pixel_sep + pixel_h)
            channel.create_modified_canvas_items(
                canvas, 'overview_graphics_{}'.format(channel), (0, offset),
                (w, 2 * pixel_sep + pixel_h), (0, offset + pixel_sep),
                (w, pixel_h))

    def set_current_timestamp(self, t):
        timestamps = self.overview_timestamps_index
        pixels = self.overview_num_timestamps_per_pixel
        w = len(pixels)

        if w:
            if t in timestamps:
                x = timestamps[t]
            else:
                pixel_per_time = self.overview_pixel_per_time
                x = min(w - 1, max(0, int(t * pixel_per_time)))
                pixels[x] += 1
                timestamps[t] = x
        else:
            x = None
            if t not in timestamps:
                timestamps[t] = 0

        for channel in self.event_channels:
            channel.set_current_timestamp(t, x)
        for channel in self.pos_channels:
            channel.set_current_timestamp(t, x)

        chan = self.selected_channel
        if chan is not None and self.delete_key_pressed and \
                isinstance(chan, TemporalChannel):
            chan.reset_current_value()

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
    """Base class for all the channels.
    """

    __config_props__ = ('color', 'color_gl', 'name', 'locked', 'hidden')

    color: List[int] = ObjectProperty(None)

    color_gl: List[float] = ObjectProperty(None)

    locked: bool = BooleanProperty(False)

    hidden: bool = BooleanProperty(False)

    name: str = StringProperty('Channel')

    data_channel: DataChannelBase = None

    channel_controller: ChannelController = None

    widget = None

    selected: bool = BooleanProperty(False)

    def __init__(self, data_channel, channel_controller, **kwargs):
        super(ChannelBase, self).__init__(**kwargs)
        self.data_channel = data_channel
        self.channel_controller = channel_controller

    def track_config_props_changes(self):
        f = self.channel_controller.app.trigger_config_updated
        for prop in get_class_config_props_names(self.__class__):
            self.fbind(prop, f)

    def select_channel(self):
        raise NotImplementedError

    def deselect_channel(self):
        raise NotImplementedError


class TemporalChannel(ChannelBase):
    """Channels the have a time component.
    """

    __config_props__ = ()

    overview_num_timestamps_modified_per_pixel = []

    modified_count_texture: Optional[Texture] = None

    selection_color_instruction: Optional[Color] = None

    selection_rect: Optional[Rectangle] = None

    texture_rect: Optional[Rectangle] = None

    modified_count_buffer: Optional[np.ndarray] = None

    data_channel: TemporalDataChannelBase = None

    current_timestamp: float = None

    current_timestamp_array_index: Optional[int] = None

    current_value = ObjectProperty(None)

    show_overview = True

    eraser_pressed = False

    def __init__(self, **kwargs):
        super(TemporalChannel, self).__init__(**kwargs)
        self.overview_num_timestamps_modified_per_pixel = []

    def _paint_modified_count_texture(self, *largs):
        if self.modified_count_texture is None:
            return

        buff2 = np.repeat(
            self.modified_count_buffer[np.newaxis, ...],
            self.channel_controller.n_pixels_per_channel, axis=0)
        self.modified_count_texture.blit_buffer(
            buff2.ravel(order='C'), colorfmt='rgb', bufferfmt='ubyte')

    def clear_modified_timestamps_count(self):
        self.channel_controller.overview_widget.canvas.remove_group(
            'overview_graphics_{}'.format(id(self)))
        self.overview_num_timestamps_modified_per_pixel = []
        self.modified_count_texture = None
        self.modified_count_buffer = None
        self.selection_color_instruction = None
        self.selection_rect = None
        self.texture_rect = None

    def create_modified_canvas_items(
            self, canvas, canvas_name, back_pos, back_size, tex_pos, tex_size):
        """Called after compute_modified_timestamps_count.

        :param canvas:
        :param canvas_name:
        :param back_pos:
        :param back_size:
        :param tex_pos:
        :param tex_size:
        :return:
        """
        controller = self.channel_controller
        # only recreate texture if size changed
        texture = self.modified_count_texture
        if texture is None or tuple(texture.size) != tex_size:
            texture = self.modified_count_texture = Texture.create(
                size=tex_size, colorfmt='rgb',
                callback=self._paint_modified_count_texture)
            if self.texture_rect is not None:
                self.texture_rect.texture = texture

            buff2 = np.repeat(
                self.modified_count_buffer[np.newaxis, ...],
                self.channel_controller.n_pixels_per_channel, axis=0)
            texture.blit_buffer(
                buff2.ravel(order='C'), colorfmt='rgb', bufferfmt='ubyte')

        # for these instructions we can simply re-adjust the pos/size
        if self.selection_color_instruction is None:
            with canvas:
                color = controller.channel_temporal_back_selection_color \
                    if self.selected else (0, 0, 0, 0)
                self.selection_color_instruction = Color(
                    *color, name=canvas_name)
                self.selection_rect = Rectangle(
                    pos=back_pos, size=back_size, name=canvas_name)
                Color(1, 1, 1, 1, name=canvas_name)
                rect = self.texture_rect = Rectangle(
                    pos=tex_pos, size=tex_size, name=canvas_name)
                rect.texture = texture
        else:
            self.selection_rect.pos = back_pos
            self.selection_rect.size = back_size
            self.texture_rect.pos = tex_pos
            self.texture_rect.size = tex_size

    def compute_modified_timestamps_count(
            self, n, overview_timestamps_index, num_timestamps_per_pixel):
        assert n >= 2
        pixels = self.overview_num_timestamps_modified_per_pixel = [0, ] * n
        buff = self.modified_count_buffer = np.zeros((n, 3), dtype=np.uint8)

        for t, v in self.data_channel.get_timestamps_modified_state().items():
            if v:
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

    def set_current_timestamp(self, t: float, index: Optional[int]):
        self.current_timestamp = t
        self.current_timestamp_array_index = index

    def change_current_value(self, value):
        # first set the value
        self.current_value = value
        t = self.current_timestamp
        modified = self.data_channel.set_timestamp_value(t, value)
        if modified:
            val = 1
        else:
            val = -1

        # now change the display
        i = self.current_timestamp_array_index
        texture = self.modified_count_texture
        if i is None or texture is None:  # no display available
            return

        num_timestamps_per_pixel = \
            self.channel_controller.overview_num_timestamps_per_pixel
        pixels = self.overview_num_timestamps_modified_per_pixel
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

        buff2 = np.repeat(
            buff[np.newaxis, ...],
            self.channel_controller.n_pixels_per_channel, axis=0)
        texture.blit_buffer(
            buff2.ravel(order='C'), colorfmt='rgb', bufferfmt='ubyte')

    def select_channel(self):
        if self.selected:
            return
        self.channel_controller.selected_channel = self
        if self.selection_color_instruction is not None:
            self.selection_color_instruction.rgba = \
                self.channel_controller.channel_temporal_back_selection_color
        self.selected = True

    def deselect_channel(self):
        if not self.selected:
            return
        if self.channel_controller.selected_channel is self:
            self.channel_controller.selected_channel = None
        if self.selection_color_instruction is not None:
            self.selection_color_instruction.rgba = 0, 0, 0, 0
        self.selected = False

    def reset_current_value(self):
        raise NotImplementedError


class EventChannel(TemporalChannel):
    """Channel that can be set to either True or False for each time step.
    """

    __config_props__ = ('keyboard_key', 'channel_group', 'is_toggle_button')

    keyboard_key: str = StringProperty('')

    channel_group: str = StringProperty('')

    is_toggle_button: bool = BooleanProperty(False)

    button_toggled_down: bool = False

    data_channel: EventChannelData = None

    button_pressed = False

    key_pressed = False

    def __init__(self, **kwargs):
        super(EventChannel, self).__init__(**kwargs)

    def set_current_timestamp(self, t: float, index: Optional[int]):
        super(EventChannel, self).set_current_timestamp(t, index)
        val = self.current_value = self.data_channel.get_timestamp_value(t)

        if self.is_toggle_button:
            if self.button_toggled_down:
                if not val:
                    self._set_current_value(True)
                self.clear_other_group_channels()
        else:
            if self.button_pressed or self.key_pressed:
                if not val:
                    self._set_current_value(True)
                self.clear_other_group_channels()

        if self.eraser_pressed:
            if self.current_value:
                self._set_current_value(False)
            self.button_toggled_down = False

    def clear_other_group_channels(self):
        controller = self.channel_controller
        group = self.channel_group
        if group and group in controller.event_groups:
            for channel in controller.event_groups[group]:
                if channel is not self:
                    channel.reset_current_value()

    def button_state(self, press: bool):
        if self.is_toggle_button:
            if press:
                self.button_toggled_down = True
                new_val = not self.current_value
                self._set_current_value(new_val)
                if not new_val:
                    self.button_toggled_down = False
                else:
                    self.clear_other_group_channels()
        else:
            self._set_current_value(press)
            if press:
                self.clear_other_group_channels()

    def key_press(self, press: bool):
        if self.is_toggle_button:
            if press and not self.key_pressed:
                self.button_toggled_down = True
                new_val = not self.current_value
                self._set_current_value(new_val)
                if not new_val:
                    self.button_toggled_down = False
                else:
                    self.clear_other_group_channels()
        else:
            self._set_current_value(press)
            if press:
                self.clear_other_group_channels()
        self.key_pressed = press

    def _set_current_value(self, value):
        if value == self.current_value:
            return
        self.change_current_value(value)

    def reset_current_value(self):
        if self.current_value:
            self.change_current_value(False)
        self.button_toggled_down = False


class PosChannel(TemporalChannel):
    """Channel that has an (x, y) position for each time step.
    """

    data_channel: PosChannelData = None


class ZoneChannel(ChannelBase):
    """Channel that describes a zone, or area in the image.

    If the channel is created from config, we create the shape, otherwise,
    the channel and shape was created by painter, so we just get shape as a
    parameter.
    """

    data_channel: ZoneChannelData = None

    shape: PaintShape = ObjectProperty(None, allownone=True)

    def get_config_properties(self):
        return {'shape_config': self.shape.get_state()}

    def apply_config_properties(self, settings):
        if 'shape_config' in settings:
            painter = self.channel_controller.zone_painter
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

    def select_channel(self):
        if self.selected:
            return

        self.channel_controller.selected_channel = self
        self.selected = True

    def deselect_channel(self):
        if not self.selected:
            return

        if self.channel_controller.selected_channel is self:
            self.channel_controller.selected_channel = None
        self.selected = False
