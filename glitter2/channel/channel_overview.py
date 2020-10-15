from typing import List, Dict, Optional, Any
import numpy as np

from kivy.graphics.texture import Texture
from kivy.graphics import Rectangle, Color

from glitter2.storage.data_file import TemporalDataChannelBase

__all__ = ('ChannelStateViewerController', 'ChannelStateViewer')


class ChannelStateViewerController:

    timestamps_index: Dict[float, int] = {}

    max_duration = 0

    width: int = 0

    num_timestamps_per_pixel: list = []

    pixel_per_time: float = 0

    widget = None

    n_sep_pixels_per_channel: int = 1

    n_pixels_per_channel: int = 1

    channels: Dict[Any, 'ChannelStateViewer'] = {}

    _last_timestamp_and_index = None

    channel_temporal_back_selection_color = .45, .45, .45, 1

    def __init__(self, **kwargs):
        super(ChannelStateViewerController, self).__init__(**kwargs)
        self.timestamps_index = {}
        self.channels = {}

        from kivy.metrics import dp
        self.n_sep_pixels_per_channel = int(dp(3))
        self.n_pixels_per_channel = int(dp(5))

    def set_widget(self, widget):
        self.widget = widget
        self.compute_overview()

    def set_width(self, width):
        self.width = int(width)
        self.compute_overview()

    def set_max_duration(self, max_duration):
        self.max_duration = max_duration
        self.compute_overview()

    def reset_timestamps(self, timestamps):
        self._last_timestamp_and_index = None
        self.timestamps_index = {t: 0 for t in timestamps}
        self.compute_overview()

    def add_channel(
            self, channel, data_channel: TemporalDataChannelBase
    ) -> 'ChannelStateViewer':
        viewer = ChannelStateViewer(controller=self, data_channel=data_channel)
        self.channels[channel] = viewer

        self.update_channel_config(channel)

        last_ts = self._last_timestamp_and_index
        if last_ts is not None:
            viewer.set_current_timestamp(*last_ts)

        if self.pixel_per_time:
            timestamps = self.timestamps_index
            pixels = self.num_timestamps_per_pixel
            viewer.compute_modified_timestamps_count(
                self.width, timestamps, pixels)

        self.display_overview()
        return viewer

    def remove_channel(self, channel, redisplay=True):
        viewer = self.channels.pop(channel)
        viewer_id = id(viewer)
        viewer.clear_modified_timestamps_count(
            self.widget.canvas, f'overview_graphics_{viewer_id}')

        if redisplay:
            self.display_overview()

    def update_channel_config(self, channel):
        viewer = self.channels[channel]
        viewer.selected = channel.selected
        viewer.color = channel.color

    def set_current_timestamp(self, t):
        timestamps = self.timestamps_index
        pixels = self.num_timestamps_per_pixel
        w = len(pixels)
        is_new = False

        # get the pixel index in pixels array that corresponds to t (or None)
        if w:
            if t in timestamps:
                x = timestamps[t]
            else:
                pixel_per_time = self.pixel_per_time
                # we round down because pixel n corresponds to time parallel to
                # pixel [n, n + 1), since w is max pixel at max time.
                x = min(w - 1, max(0, int(t * pixel_per_time)))
                pixels[x] += 1
                timestamps[t] = x
                is_new = True
        else:
            x = None
            if t not in timestamps:
                timestamps[t] = 0
                is_new = True

        for viewer in self.channels.values():
            viewer.set_current_timestamp(t, x, is_new)

    def compute_overview(self):
        duration = self.max_duration
        w = self.width

        if w < 2 or duration <= 0:
            self.num_timestamps_per_pixel = []
            self.pixel_per_time = 0

            for viewer in self.channels.values():
                viewer_id = id(viewer)
                viewer.clear_modified_timestamps_count(
                    self.widget.canvas, f'overview_graphics_{viewer_id}')
            self.display_overview()

            return

        pixels = self.num_timestamps_per_pixel = [0, ] * w
        self.pixel_per_time = pixel_per_time = w / duration

        timestamps = self.timestamps_index
        for t in timestamps:
            x = min(w - 1, max(0, int(t * pixel_per_time)))
            pixels[x] += 1
            timestamps[t] = x

        for viewer in self.channels.values():
            viewer.clear_modified_timestamps_count(
                self.widget.canvas, f'overview_graphics_{id(viewer)}')

            viewer.compute_modified_timestamps_count(w, timestamps, pixels)
        self.display_overview()

    def display_overview(self):
        if self.widget is None:
            return

        if not self.num_timestamps_per_pixel:
            self.widget.height = 0
            return

        channels = self.channels

        if not channels:
            self.widget.height = 0
            return

        canvas = self.widget.canvas
        pixel_sep = self.n_sep_pixels_per_channel
        pixel_h = self.n_pixels_per_channel
        n = len(channels)
        w = self.width
        self.widget.height = n * (pixel_sep + pixel_h) + pixel_sep

        # each channel is a line of data of height h surrounded above and
        # below by whitespace of height sep
        for i, viewer in enumerate(reversed(list(channels.values()))):
            # bottom of the whitespace below the channel
            sep_bottom = i * (pixel_sep + pixel_h)
            data_bottom = sep_bottom + pixel_sep
            data_top = data_bottom + pixel_h

            viewer_id = id(viewer)
            viewer.create_modified_canvas_items(
                canvas, f'overview_graphics_{viewer_id}', 0, w, sep_bottom,
                data_bottom, data_top, pixel_sep, pixel_h)


class ChannelStateViewer:

    data_channel: TemporalDataChannelBase = None

    controller: ChannelStateViewerController = None

    selected: bool = False

    color: List[int] = None

    num_timestamps_modified_per_pixel = []

    texture: Optional[Texture] = None

    selection_color_instruction: Optional[Color] = None

    selection_rect: Optional[Rectangle] = None

    texture_rect: Optional[Rectangle] = None

    modified_count_buffer: Optional[np.ndarray] = None

    current_timestamp_array_index: Optional[int] = None

    current_timestamp: float = None

    def __init__(self, controller, data_channel, **kwargs):
        super().__init__(**kwargs)
        self.controller = controller
        self.data_channel = data_channel
        self.num_timestamps_modified_per_pixel = []

    def compute_modified_timestamps_count(
            self, n, overview_timestamps_index, num_timestamps_per_pixel):
        assert n >= 2
        if self.current_timestamp is not None:
            self.current_timestamp_array_index = overview_timestamps_index[
                self.current_timestamp]

        pixels = self.num_timestamps_modified_per_pixel = [0, ] * n
        timestamp_ends = self.data_channel.data_file.timestamp_intervals_end
        buff = self.modified_count_buffer = np.zeros((n, 3), dtype=np.uint8)

        pixel_per_time = self.controller.pixel_per_time
        index_ends = [
            min(n - 1, max(0, int(t * pixel_per_time)))
            for t in timestamp_ends
        ]

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

            # if there's a end timestamp (seek start) in this pixel, even if
            # there's no further timestamps, don't color pixels. We don't have
            # to worry about a end timestamp later, because by def if there' a
            # end, num_timestamps_per_pixel will be truthy
            end_timestamp = i in index_ends
            i += 1
            # fill in until the next non-zero pixel-timestamps
            while i < n and not num_timestamps_per_pixel[i]:
                assert not pixels[i]
                if not end_timestamp:
                    buff[i, :] = color

                i += 1

            # now, find the next non-zero pixel to be colored
            while i < n and not pixels[i]:
                i += 1

    def clear_modified_timestamps_count(self, canvas, canvas_name):
        if self.texture_rect is not None:
            # kivy doesn't remove textures with a group!!?
            self.texture_rect.texture = None
            canvas.remove(self.texture_rect)

        canvas.remove_group(canvas_name)
        self.num_timestamps_modified_per_pixel = []
        self.texture = None
        self.modified_count_buffer = None
        self.selection_color_instruction = None
        self.selection_rect = None
        self.texture_rect = None

    def _paint_modified_count_texture(self, *largs):
        if self.texture is None:
            return

        buff2 = np.repeat(
            self.modified_count_buffer[np.newaxis, ...],
            self.controller.n_pixels_per_channel, axis=0)
        self.texture.blit_buffer(
            buff2.ravel(order='C'), colorfmt='rgb', bufferfmt='ubyte')

    def create_modified_canvas_items(
            self, canvas, canvas_name, x, width, sep_bottom, data_bottom,
            data_top, sep_height, data_height):
        """Called after compute_modified_timestamps_count.
        """
        controller = self.controller
        # only recreate texture if size changed
        texture = self.texture
        data_size = width, data_height
        if texture is None or tuple(texture.size) != data_size:
            texture = self.texture = Texture.create(
                size=data_size, colorfmt='rgb',
                callback=self._paint_modified_count_texture)
            if self.texture_rect is not None:
                self.texture_rect.texture = texture

        buff2 = np.repeat(
            self.modified_count_buffer[np.newaxis, ...],
            controller.n_pixels_per_channel, axis=0)
        texture.blit_buffer(
            buff2.ravel(order='C'), colorfmt='rgb', bufferfmt='ubyte')

        # for these instructions we can simply re-adjust the pos/size
        data_pos = x, data_bottom
        sep_size = width, 2 * sep_height + data_height
        sep_pos = x, sep_bottom

        if self.selection_color_instruction is None:
            with canvas:
                color = controller.channel_temporal_back_selection_color \
                    if self.selected else (0, 0, 0, 0)
                self.selection_color_instruction = Color(
                    *color, name=canvas_name)
                self.selection_rect = Rectangle(
                    pos=sep_pos, size=sep_size, name=canvas_name)
                Color(1, 1, 1, 1, name=canvas_name)
                rect = self.texture_rect = Rectangle(
                    pos=data_pos, size=data_size, name=canvas_name)
                rect.texture = texture
        else:
            self.selection_rect.pos = sep_pos
            self.texture_rect.pos = data_pos

    def set_current_timestamp(
            self, t: float, index: Optional[int], is_new: bool):
        # if we see a new timestamp, then there may have been some empty pixels
        # between the last timestamp and the new one, so fill in the color
        if is_new:
            last_t = self.current_timestamp
            last_i = self.current_timestamp_array_index
            if last_i is not None:
                self._update_display_texture(last_t, last_i, index)

        self.current_timestamp = t
        self.current_timestamp_array_index = index

    def change_current_value(self, changed):
        t = self.current_timestamp

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
        if i is None:
            return changed

        self.num_timestamps_modified_per_pixel[i] += val
        self._update_display_texture(t, i)
        return changed

    def _update_display_texture(self, t, i, next_index=None):
        texture = self.texture
        if texture is None:  # no display available
            return

        num_timestamps_per_pixel = self.controller.num_timestamps_per_pixel
        pixels = self.num_timestamps_modified_per_pixel
        buff = self.modified_count_buffer

        n = len(pixels)
        assert num_timestamps_per_pixel[i], "current ts should make # positive"
        assert 0 <= pixels[i] <= num_timestamps_per_pixel[i]

        # set current color
        if pixels[i] == num_timestamps_per_pixel[i]:
            color = self.color
        elif not pixels[i]:
            color = [0, 0, 0]
        else:
            color = [int(c * .4) for c in self.color]
        buff[i, :] = color

        # only paint pixels after us, if there are further time stamps and
        # there's blank pixels between us and the next timestamp. If the next
        # index is known to be the same as current, there's nothing to do
        if next_index != i \
                and not self.data_channel.data_file.is_end_timestamp(t):
            i += 1
            # fill in until the next non-zero pixel-timestamps
            while i < n and not num_timestamps_per_pixel[i]:
                assert not pixels[i]
                buff[i, :] = color
                i += 1

        buff2 = np.repeat(
            buff[np.newaxis, ...],
            self.controller.n_pixels_per_channel, axis=0)
        texture.blit_buffer(
            buff2.ravel(order='C'), colorfmt='rgb', bufferfmt='ubyte')
        return

    def set_selection(self, selection):
        self.selected = selection

        if self.selection_color_instruction is None:
            return

        if selection:
            self.selection_color_instruction.rgba = \
                self.controller.channel_temporal_back_selection_color
        else:
            self.selection_color_instruction.rgba = 0, 0, 0, 0

    def reset_data_to_default(self):
        # now change the display
        i = self.current_timestamp_array_index
        texture = self.texture
        if i is None or texture is None:  # no display available
            return

        pixels = self.num_timestamps_modified_per_pixel
        n = len(pixels)
        self.num_timestamps_modified_per_pixel = [0, ] * n

        buff = self.modified_count_buffer
        buff[:] = 0

        buff2 = np.repeat(
            buff[np.newaxis, ...],
            self.controller.n_pixels_per_channel, axis=0)
        texture.blit_buffer(
            buff2.ravel(order='C'), colorfmt='rgb', bufferfmt='ubyte')
