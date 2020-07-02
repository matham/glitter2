"""Channels
===========
API for a channel controller as well as the channel types that the user can
create. E.g. an event channel, a position based channel, etc.
"""
from typing import Iterable, List, Dict, Iterator, Optional, Any, Union
from itertools import cycle, chain
import numpy as np
from collections import defaultdict

from kivy.properties import NumericProperty, ObjectProperty, StringProperty, \
    BooleanProperty, ListProperty, DictProperty
from kivy.event import EventDispatcher
from kivy.graphics.texture import Texture
from kivy.graphics import Rectangle, Color, Line, Point

from kivy_garden.painter import PaintShape, PaintCanvasBehaviorBase, \
    PaintCircle, PaintEllipse, PaintPolygon
from kivy_garden.collider import Collide2DPoly, CollideEllipse

from tree_config import get_config_prop_names
from base_kivy_app.config import read_config_from_object, apply_config

from glitter2.storage.data_file import DataChannelBase, EventChannelData, \
    TemporalDataChannelBase, PosChannelData, ZoneChannelData
from glitter2.utils import fix_name as fix_name_original

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
    (0.7372549019607844, 0.7411764705882353, 0.13333333333333333),
    (0.09019607843137255, 0.7450980392156863, 0.8117647058823529)
)


def fix_name(name, *names):
    name = fix_name_original(name, *names)
    return name.replace(';', '').replace(':', '')


class ChannelController(EventDispatcher):
    """Manages all the channels shown to the user.
    """

    _config_props_ = (
        'n_sep_pixels_per_channel', 'n_pixels_per_channel',
        'pos_channels_time_tail')

    color_theme: Iterator = None

    channels: Dict[str, 'ChannelBase'] = {}

    event_channels: List['EventChannel'] = []

    pos_channels: List['PosChannel'] = []

    zone_channels: List['ZoneChannel'] = []

    pos_channels_time_tail: float = 2

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

    channels_keys: Dict[str, Union['EventChannel', 'PosChannel']] = {}

    channel_temporal_back_selection_color = .45, .45, .45, 1

    selected_channel: Optional['ChannelBase'] = None

    delete_key_pressed = False

    touch_pos = None

    event_groups: Dict[str, List['EventChannel']] = {}

    show_zone_drawing = BooleanProperty(True)

    def __init__(self, app, **kwargs):
        super(ChannelController, self).__init__(**kwargs)
        self.color_theme = cycle(_color_theme_tab10)
        self.event_channels = []
        self.pos_channels = []
        self.zone_channels = []
        self.overview_timestamps_index = {}
        self.app = app
        self.channels_keys = {}
        self.channels = {}

        from kivy.metrics import dp
        self.n_sep_pixels_per_channel = int(dp(3))
        self.n_pixels_per_channel = int(dp(5))

        self.fbind('max_duration', self._compute_overview)
        self.fbind('overview_width', self._compute_overview)
        self.fbind('show_zone_drawing', self._set_zone_channels_drawing)

    def _set_zone_channels_drawing(self, *args):
        show = self.show_zone_drawing
        for channel in self.zone_channels:
            if show:
                channel.shape.show_shape_in_canvas()
            else:
                channel.shape.hide_shape_in_canvas()
            channel.manage_zone_highlighted_display()

        for channel in self.pos_channels:
            channel.find_highlighted_shape()

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

        if not config or 'color' not in config or 'color_gl' not in config:
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

            channel.fbind('keyboard_key', self._track_key)
            self._track_key()
            if channel_type == 'event':
                channel.fbind('channel_group', self._track_event_group)
                self._track_event_group()
        else:
            if self.show_zone_drawing:
                channel.shape.show_shape_in_canvas()
            else:
                channel.shape.hide_shape_in_canvas()

        if self.app is not None:
            self.app.create_channel_widget(channel)
        return channel

    def delete_channel(self, channel: 'ChannelBase', _recompute=True):
        if isinstance(channel, EventChannel):
            self.event_channels.remove(channel)
            channel.funbind('keyboard_key', self._track_key)
            channel.funbind('channel_group', self._track_event_group)
            channel.clear_modified_timestamps_count()
            self._track_event_group()
            self._track_key()
        elif isinstance(channel, PosChannel):
            channel.funbind('keyboard_key', self._track_key)
            self._track_key()
            channel.clear_zone_highlighted()
            channel.clear_pos_graphics()
            self.pos_channels.remove(channel)
        elif isinstance(channel, ZoneChannel):
            channel.clear_zone_area_instructions()
            # clear and refs to the zone from pos channels
            for pos_channel in channel.pos_channels_highlighted:
                pos_channel.clear_zone_highlighted()
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

    def _track_key(self, *args):
        self.channels_keys = {
            c.keyboard_key: c
            for c in chain(self.event_channels, self.pos_channels)
            if c.keyboard_key
        }

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

    def pos_painter_touch_down(self, pos):
        self.touch_pos = pos
        channel = self.selected_channel
        if channel is not None and isinstance(channel, PosChannel):
            channel.change_current_value(pos)

    def pos_painter_touch_move(self, pos):
        self.touch_pos = pos
        channel = self.selected_channel
        if channel is not None and isinstance(channel, PosChannel):
            channel.change_current_value(pos)

    def pos_painter_touch_up(self, pos):
        self.touch_pos = None
        channel = self.selected_channel
        if channel is not None and isinstance(channel, PosChannel):
            channel.change_current_value(pos)


class ChannelBase(EventDispatcher):
    """Base class for all the channels.
    """

    _config_props_ = ('color', 'color_gl', 'name', 'locked', 'hidden')

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
        for prop in get_config_prop_names(self):
            self.fbind(prop, f)

    def select_channel(self):
        raise NotImplementedError

    def deselect_channel(self):
        raise NotImplementedError


class TemporalChannel(ChannelBase):
    """Channels the have a time component.
    """

    overview_num_timestamps_modified_per_pixel = []

    modified_count_texture: Optional[Texture] = None

    selection_color_instruction: Optional[Color] = None

    selection_rect: Optional[Rectangle] = None

    texture_rect: Optional[Rectangle] = None

    modified_count_buffer: Optional[np.ndarray] = None

    data_channel: TemporalDataChannelBase = None

    current_timestamp: float = None

    current_timestamp_array_index: Optional[int] = None

    current_value = None

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

    def compare_value_change(self, old, new):
        raise NotImplementedError

    def change_current_value(self, value):
        changed = self.compare_value_change(self.current_value, value)
        # first set the value
        self.current_value = value
        t = self.current_timestamp
        self.data_channel.set_timestamp_value(t, value)

        if changed is None:
            # it hasn't changed with respect to the default value (i.e. it may
            # already have been non-default and it was now changed again)
            return changed
        elif changed:
            # it's changed from the default
            val = 1
        else:
            # it is now the default
            val = -1

        # now change the display
        i = self.current_timestamp_array_index
        texture = self.modified_count_texture
        if i is None or texture is None:  # no display available
            return changed

        num_timestamps_per_pixel = \
            self.channel_controller.overview_num_timestamps_per_pixel
        pixels = self.overview_num_timestamps_modified_per_pixel
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

        buff2 = np.repeat(
            buff[np.newaxis, ...],
            self.channel_controller.n_pixels_per_channel, axis=0)
        texture.blit_buffer(
            buff2.ravel(order='C'), colorfmt='rgb', bufferfmt='ubyte')
        return changed

    def select_channel(self):
        if self.selected:
            return False
        self.channel_controller.selected_channel = self
        if self.selection_color_instruction is not None:
            self.selection_color_instruction.rgba = \
                self.channel_controller.channel_temporal_back_selection_color
        self.selected = True
        return True

    def deselect_channel(self):
        if not self.selected:
            return False
        if self.channel_controller.selected_channel is self:
            self.channel_controller.selected_channel = None
        if self.selection_color_instruction is not None:
            self.selection_color_instruction.rgba = 0, 0, 0, 0
        self.selected = False
        return True

    def reset_current_value(self):
        raise NotImplementedError

    def reset_data_to_default(self):
        self.data_channel.reset_data_to_default()
        self.current_value = self.data_channel.get_timestamp_value(
            self.current_timestamp)

        # now change the display
        i = self.current_timestamp_array_index
        texture = self.modified_count_texture
        if i is None or texture is None:  # no display available
            return

        pixels = self.overview_num_timestamps_modified_per_pixel
        n = len(pixels)
        self.overview_num_timestamps_modified_per_pixel = [0, ] * n

        buff = self.modified_count_buffer
        buff[:] = 0

        buff2 = np.repeat(
            buff[np.newaxis, ...],
            self.channel_controller.n_pixels_per_channel, axis=0)
        texture.blit_buffer(
            buff2.ravel(order='C'), colorfmt='rgb', bufferfmt='ubyte')


class EventChannel(TemporalChannel):
    """Channel that can be set to either True or False for each time step.
    """

    _config_props_ = ('keyboard_key', 'channel_group', 'is_toggle_button')

    keyboard_key: str = StringProperty('')

    channel_group: str = StringProperty('')

    is_toggle_button: bool = BooleanProperty(False)

    button_toggled_down: bool = False

    data_channel: EventChannelData = None

    button_pressed = False

    key_pressed = False

    current_value = ObjectProperty(False)

    def set_current_timestamp(self, t: float, index: Optional[int]):
        super().set_current_timestamp(t, index)
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
        if value == self.current_value:  # optimization
            return
        self.change_current_value(value)

    def reset_current_value(self):
        self.change_current_value(False)
        self.button_toggled_down = False

    def compare_value_change(self, old, new):
        if old == new:
            return None
        return new

    def reset_data_to_default(self):
        super(EventChannel, self).reset_data_to_default()
        self.button_toggled_down = False


class PosChannel(TemporalChannel):
    """Channel that has an (x, y) position for each time step.
    """
    _config_props_ = ('keyboard_key', )

    keyboard_key: str = StringProperty('')

    data_channel: PosChannelData = None

    display_line = BooleanProperty(False)

    current_value = ObjectProperty((-1, -1))

    zone_highlighted: Optional['ZoneChannel'] = None

    _tail_line_graphics: Optional[Line] = None

    _tail_line_end_graphics: Optional[Line] = None

    _current_point_graphics: Optional[Point] = None

    _current_point_back_graphics: Optional[Line] = None

    def __init__(self, **kwargs):
        super(PosChannel, self).__init__(**kwargs)
        self.fbind('display_line', self._display_line_graphics)
        self.fbind('display_line', self.update_current_point_graphics)
        self.fbind('display_line', self.find_highlighted_shape)

    def track_config_props_changes(self):
        super(PosChannel, self).track_config_props_changes()

        name = f'pos_graphics_point_{id(self)}'
        canvas = self.channel_controller.zone_painter.canvas
        r, g, b = self.color_gl

        canvas.add(Color(1 - r, 1 - g, 1 - b, 1, group=name))
        line = self._current_point_back_graphics = Line(width=2, group=name)
        canvas.add(line)

        canvas.add(Color(r, g, b, 1, group=name))
        point = self._current_point_graphics = Point(pointsize=4, group=name)
        canvas.add(point)

    def _display_line_graphics(self, *args):
        if self.display_line:
            name = f'pos_graphics_line_{id(self)}'
            canvas = self.channel_controller.zone_painter.canvas

            canvas.add(Color(*self.color_gl, 1, group=name))
            line = self._tail_line_graphics = Line(width=2, group=name)
            canvas.add(line)
            line = self._tail_line_end_graphics = Line(width=2, group=name)
            canvas.add(line)

            self.update_line_graphics()
        else:
            self._tail_line_graphics = None
            self.channel_controller.zone_painter.canvas.remove_group(
                f'pos_graphics_line_{id(self)}')

    def clear_pos_graphics(self):
        self._current_point_graphics = self._tail_line_graphics = None
        self._tail_line_end_graphics = None
        self._current_point_back_graphics = None
        canvas = self.channel_controller.zone_painter.canvas
        canvas.remove_group(f'pos_graphics_point_{id(self)}')
        canvas.remove_group(f'pos_graphics_line_{id(self)}')

    def set_current_timestamp(self, t: float, index: Optional[int]):
        super().set_current_timestamp(t, index)
        self.current_value = self.data_channel.get_timestamp_value(t)

        if self.selected:
            touch_pos = self.channel_controller.touch_pos
            if touch_pos is not None:
                self.change_current_value(touch_pos)
                self.update_line_graphics()
                return

        # need to call manually because change_current_value was not called
        self.find_highlighted_shape()
        self.update_current_point_graphics()
        self.update_line_graphics()

    def update_line_graphics(self):
        line = self._tail_line_graphics
        if line is None:
            return
        line_end = self._tail_line_end_graphics

        t = self.current_timestamp
        timestamps, data, i = self.data_channel.get_previous_timestamp_data(t)
        if timestamps is None:
            line_end.points = line.points = []
            return

        times = np.array(timestamps[:i + 1])
        s = np.searchsorted(
            times, t - self.channel_controller.pos_channels_time_tail)

        points = np.array(data[s:i + 1, :])
        if not points.shape[0]:
            line_end.points = line.points = []
            return

        k = points.shape[0] - np.argmax(np.flip(points[:, 0]) == -1) - 1
        if points[k, 0] == -1:
            # we found a -1
            points = points[k + 1:, :]
        if not points.shape[0]:
            line_end.points = line.points = []
            return

        points = line.points = np.reshape(points, 2 * points.shape[0]).tolist()

        x, y = self.current_value
        if x == -1:
            line_end.points = []
        else:
            line_end.points = [points[-2], points[-1], x, y]

    def update_current_point_graphics(self, *args):
        p = self._current_point_graphics
        circle = self._current_point_back_graphics
        x, y = self.current_value
        line_end = self._tail_line_end_graphics

        if x == -1 or not self.selected and not self.display_line:
            p.points = circle.points = []
            if line_end is not None:
                line_end.points = []
        else:
            p.points = [x, y]
            circle.circle = x, y, 8
            if line_end is not None:
                points = line_end.points
                if points:
                    line_end.points = [points[0], points[1], x, y]

    def find_highlighted_shape(self, *args):
        highlighted_zone = self.zone_highlighted
        if self.channel_controller.show_zone_drawing and (
                self.display_line or self.selected):
            # we display the zones and this channel
            x, y = self.current_value
            # is it for sure in no zone?
            if x != -1:
                for zone in reversed(self.channel_controller.zone_channels):
                    if zone.collider.collide_point(x, y):
                        # found the zone, does is it unchanged?
                        if zone is highlighted_zone:
                            return

                        if highlighted_zone is not None:
                            del highlighted_zone.pos_channels_highlighted[self]
                        zone.pos_channels_highlighted[self] = None
                        self.zone_highlighted = zone
                        return

        # display was turned off or none was found
        if highlighted_zone is not None:
            del highlighted_zone.pos_channels_highlighted[self]
            self.zone_highlighted = None

    def reset_current_value(self):
        self.change_current_value((-1, -1))

    def select_channel(self):
        if super(PosChannel, self).select_channel():
            touch_pos = self.channel_controller.touch_pos
            if touch_pos is not None:
                self.change_current_value(touch_pos)
            self.update_current_point_graphics()
            self.find_highlighted_shape()
            return True
        return False

    def deselect_channel(self):
        if super(PosChannel, self).deselect_channel():
            self.update_current_point_graphics()
            self.find_highlighted_shape()
            return True
        return False

    def change_current_value(self, value):
        val = super(PosChannel, self).change_current_value(value)

        self.find_highlighted_shape()
        self.update_current_point_graphics()
        return val

    def clear_zone_highlighted(self):
        zone = self.zone_highlighted
        if zone is not None:
            del zone.pos_channels_highlighted[self]
            self.zone_highlighted = None

    def compare_value_change(self, old, new):
        old_x = old[0]
        new_x = new[0]
        if old_x == -1 and new_x == -1 or old_x != -1 and new_x != -1:
            return None
        return new_x != -1

    def reset_data_to_default(self):
        super(PosChannel, self).reset_data_to_default()
        self.find_highlighted_shape()
        self.update_current_point_graphics()
        self.update_line_graphics()


class ZoneChannel(ChannelBase):
    """Channel that describes a zone, or area in the image.

    If the channel is created from config, we create the shape, otherwise,
    the channel and shape was created by painter, so we just get shape as a
    parameter.
    """

    _config_props_ = ('shape_config', )

    data_channel: ZoneChannelData = None

    shape: PaintShape = ObjectProperty(None, allownone=True)

    shape_highlighted: bool = BooleanProperty(False)

    pos_channels_highlighted: Dict['PosChannel', Any] = DictProperty({})

    _collider = None

    _zone_area_color_instruction: Color = None

    def __init__(self, **kwargs):
        super(ZoneChannel, self).__init__(**kwargs)
        self.fbind('shape_highlighted', self.manage_zone_highlighted_display)
        self.fbind('pos_channels_highlighted', self._update_shape_highlighted)

    def _update_shape_highlighted(self, *args):
        self.shape_highlighted = bool(self.pos_channels_highlighted)

    def get_config_property(self, name):
        if name == 'shape_config':
            return self.shape.get_state()
        return getattr(self, name)

    def apply_config_property(self, name, value):
        if name == 'shape_config':
            painter = self.channel_controller.zone_painter
            self.shape = shape = painter.create_shape_from_state(
                value, add=False)
            shape.channel = self
            painter.add_shape(shape)
        else:
            setattr(self, name, value)

    def track_config_props_changes(self):
        super(ZoneChannel, self).track_config_props_changes()
        f = self.channel_controller.app.trigger_config_updated
        assert self.shape is not None
        self.shape.fbind('on_update', f)
        self.shape.fbind('on_update', self._update_shape)

    def _update_shape(self, *args):
        self._collider = None
        self.clear_zone_area_instructions()
        self.manage_zone_highlighted_display()

    def manage_zone_highlighted_display(self, *args):
        if self.channel_controller.show_zone_drawing and (
                self.selected or self.shape_highlighted):
            self.zone_area_color_instruction.a = .2
        else:
            # optimization if it's not already visible
            if self._zone_area_color_instruction is not None:
                self.zone_area_color_instruction.a = 0

    def select_channel(self):
        if self.selected:
            return

        self.channel_controller.selected_channel = self
        self.selected = True
        self.channel_controller.zone_painter.select_shape(self.shape)
        self.manage_zone_highlighted_display()

    def deselect_channel(self):
        if not self.selected:
            return

        if self.channel_controller.selected_channel is self:
            self.channel_controller.selected_channel = None
        self.selected = False
        self.channel_controller.zone_painter.deselect_shape(self.shape)
        self.manage_zone_highlighted_display()

    @property
    def collider(self):
        collider = self._collider
        if collider is not None:
            return collider

        shape = self.shape
        if isinstance(shape, PaintPolygon):
            collider = Collide2DPoly(points=shape.points, cache=True)
        elif isinstance(shape, PaintCircle):
            x, y = shape.center
            r = shape.radius
            collider = CollideEllipse(x=x, y=y, rx=r, ry=r)
        elif isinstance(shape, PaintEllipse):
            x, y = shape.center
            rx, ry = shape.radius_x, shape.radius_y
            collider = CollideEllipse(
                x=x, y=y, rx=rx, ry=ry, angle=shape.angle)
        else:
            assert False

        self._collider = collider
        return collider

    @property
    def zone_area_color_instruction(self):
        color = self._zone_area_color_instruction
        if color is not None:
            return color

        name = f'zone_area_{id(self)}'
        canvas = self.channel_controller.zone_painter.canvas
        color = self._zone_area_color_instruction = Color(
            .1, .1, .1, 0, group=name)
        canvas.add(color)
        self.shape.add_area_graphics_to_canvas(name, canvas)
        return color

    def clear_zone_area_instructions(self):
        if self._zone_area_color_instruction is None:
            return

        self._zone_area_color_instruction = None
        self.channel_controller.zone_painter.canvas.remove_group(
            f'zone_area_{id(self)}')
