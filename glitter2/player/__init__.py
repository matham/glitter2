"""Video Player
===============

Plays the video files that are scored by Glitter.
"""
from typing import Tuple, Optional, List, Dict
import time
import math
import os

from ffpyplayer.player import MediaPlayer
from ffpyplayer.pic import Image

from kivy.event import EventDispatcher
from kivy.clock import Clock
from kivy.properties import BooleanProperty, NumericProperty, StringProperty


from more_kivy_app.app import app_error

__all__ = ('GlitterPlayer', )


class GlitterPlayer(EventDispatcher):
    """Player that reads the video file and sends frames as they need to
    be displayed.
    """

    _config_props_ = ('seek_duration', )

    seek_duration = 10
    """How many seconds to seek from a right/left arrow button.
    """

    filename = StringProperty('')
    """Full path to the video file. Read only.
    """

    ff_player: Optional[MediaPlayer] = None
    """The video player, once file is opened.
    """

    reached_end = BooleanProperty(False)
    """True when the video file has finished playing the file and reached the
    end.
    """

    play_rate = NumericProperty(1)
    """The playing rate with which we play the video.
    """

    video_size: Optional[Tuple[int, int]] = None
    """The size of the video frames, set once the file is open. Read only.
    """

    duration: float = NumericProperty(0)
    """The duration of of the video, set once the file is open. Read only.
    """

    app = None
    """The Glitter app.
    """

    paused = BooleanProperty(True)
    """Whether we are currently paused. Read only.
    """

    _frame_trigger = None
    """Trigger to call to get the next frame. This is automatically called
    each kivy clock frame by the kivy clock.
    """

    player_state: str = StringProperty('none')
    """The current state of the player.

    Can be one of opening, seeking_paused, seeking, none, playing, finished,
    paused.
    """

    _last_frame_clock: float = 0
    """System time when we showed the last frame. Zero means show next frame
    immediately since there's no previous frame.
    """

    last_frame_pts: float = NumericProperty(0)
    """The timestamp (pts) in video time of the last shown frame.
    """

    _last_frame: Optional[Image] = None
    """The last frame shown.
    """

    _next_frame: Optional[Tuple[Image, float]] = None
    """We keep here the next frame until we show it at the right time.
    """

    _seeked_since_frame = None
    """This keeps track whether we have seeked since seeing the last frame.
    If we did, it's a timestamps of the seek, otherwise, it's None.
    """

    _seeking_skip_count = 0
    """Number of frames we skipped since a seek - we need to skip one frame.
    """

    def __init__(self, app, **kwargs):
        super(GlitterPlayer, self).__init__(**kwargs)
        self.app = app
        self._frame_trigger = Clock.create_trigger(
            self._frame_callback, timeout=0, interval=True)

    @app_error(threaded=True)
    def _player_callback(self, mode, value):
        """Called internally by ffpyplayer when an error occurs internally.
        """
        if mode.endswith('error'):
            raise Exception(
                'FFmpeg Player: internal error "{}", "{}"'.format(mode, value))

    def set_log_play_rate(self, val: float):
        """Sets the :attr:`play_rate` from ``val`` when it is given in 10 base
        log. The ``val`` is forced between -1 to 1 first.
        """
        val = max(min(val, 1), -1)
        if val == 1:
            self.play_rate = float('inf')
        elif val == -1:
            self.play_rate = float('-inf')
        else:
            self.play_rate = math.pow(10, val)

    def set_play_rate(self, val: float):
        """Sets the :attr:`play_rate` to ``val``. The ``val`` is forced
        between 0.1 to 10 first.
        """
        val = max(min(val, 10), .1)
        if val == 10:
            self.play_rate = float('inf')
        elif val == .1:
            self.play_rate = float('-inf')
        else:
            self.play_rate = val

    def get_slider_log_play_rate(self, rate: float) -> float:
        """Converts the given rate to 10 base log, forcing the value between
        -1 and 1.
        """
        if rate < .1:
            return -1
        if rate > 10:
            return 1
        return math.log10(rate)

    def get_play_rate_text(self, rate: float) -> str:
        """Converts the given play rate to a string, forcing the value between
        0.1 and 10.
        """
        if rate < .1:
            return '0.1'
        if rate > 10:
            return '10.0'
        return '{:0.2f}'.format(rate)

    def advance_frame_if_frame_by_frame(self):
        if self.play_rate != float('-inf'):
            return
        if self.player_state != 'playing':
            return
        self._last_frame_clock = 0

    @app_error
    def open_file(self, filename):
        """Opens and starts playing the given file.

        :param filename: The full path to the video file.
        """
        self.close_file()

        filename = os.path.abspath(filename)
        ff_opts = {'sync': 'video', 'an': True, 'sn': True, 'paused': True}
        self.ff_player = MediaPlayer(
            filename, callback=self._player_callback, ff_opts=ff_opts)
        self.player_state = 'opening'
        self.filename = filename
        self.paused = False
        self._frame_trigger()

    @app_error
    def close_file(self):
        """Closes and stops playing the current file, if any.
        """
        self._frame_trigger.cancel()
        self.player_state = 'none'
        self.video_size = None
        self.duration = 0
        self._last_frame = None
        self._last_frame_clock = 0
        self.last_frame_pts = 0
        self.reached_end = False
        self._next_frame = None
        self._seeked_since_frame = None
        self.filename = ''
        self.paused = True
        self.app.clear_video()

        if self.ff_player is not None:
            self.ff_player.close_player()
            self.ff_player = None

    def callback_playing(self):
        """Handles the player callback (:attr:`_frame_trigger`) when the player
        is in "playing" mode.
        """
        ffplayer = self.ff_player
        next_frame = self._next_frame

        # if there's a frame available, we need to show it at the right time
        if next_frame is not None:
            image, pts = next_frame
            t = time.perf_counter()
            ts = self._last_frame_clock
            rate = self.play_rate
            remaining_t = 0
            # if it's +inf, don't delay
            if ts and rate < 100:
                if rate < -100:  # if it's -inf, wait until user requests frame
                    return

                remaining_t = max(
                    0.,
                    (pts - self.last_frame_pts) / self.play_rate - (t - ts))

            if remaining_t < 0.005:
                self._last_frame_clock = t
                self._last_frame = image
                self.last_frame_pts = pts

                # there has been no seeking since this frame was read, because
                # the frame is cleared during a seek
                self._seeked_since_frame = None
                self.app.add_video_frame(pts, image)
                self._next_frame = None
            else:
                return

        frame, val = ffplayer.get_frame()

        assert val != 'paused'
        if val == 'eof':
            self.player_state = 'finished'
            self.reached_end = True

            # if we got eof directly after reading a frame, we can notify
            if self._seeked_since_frame is None:
                # only if we hit eof after seeing a previous frame
                self.app.notify_video_change('last_ts')
            return
        if frame is None:
            return

        self._next_frame = frame

    def callback_seeking(self, state):
        """Handles the player callback (:attr:`_frame_trigger`) when the player
        is in "seeking_paused" mode.
        """
        # during seeking_paused, we unpause while seeking and then immediately
        # pause again
        ffplayer = self.ff_player
        frame, val = ffplayer.get_frame()

        assert val != 'paused'
        assert self._last_frame is not None, \
            "we shouldn't have seeked before reading the first frame"
        if val == 'eof':
            self.player_state = 'finished'
            self.reached_end = True
            return
        if frame is None:
            return

        if not self._seeking_skip_count:
            self._seeking_skip_count += 1
            return

        # simply display this frame
        self._last_frame, self.last_frame_pts = frame
        self.app.add_video_frame(self.last_frame_pts, self._last_frame)
        self._seeked_since_frame = None  # reset as above

        # if we got a frame, we can break out
        if state == 'seeking_paused':
            ffplayer.set_pause(True)
            self.player_state = 'paused'
        else:
            self.player_state = 'playing'

    @classmethod
    def _get_video_metadata(cls, ffplayer, filename):
        """Returns the metadata from the given media player, adding any
        additional required metadata.
        """
        metadata = ffplayer.get_metadata()
        filename = os.path.abspath(os.path.expanduser(filename))
        head, tail = os.path.split(filename)
        metadata['filename_head'] = head
        metadata['filename_tail'] = tail
        metadata['file_size'] = os.stat(filename).st_size
        return metadata

    def callback_opening(self):
        """Handles the player callback (:attr:`_frame_trigger`) when the player
        is in "opening" mode.
        """
        ffplayer = self.ff_player
        if self.video_size is not None:
            # we already handled the metadata, now we're waiting on a frame
            frame, val = ffplayer.get_frame()

            assert val != 'paused'
            assert self._last_frame is None
            if val == 'eof':
                self.player_state = 'finished'
                self.reached_end = True
                return
            if frame is None:
                return

            image, pts = frame
            self._last_frame_clock = 0
            self._last_frame = image
            self.last_frame_pts = pts
            self._seeked_since_frame = None
            self.app.add_video_frame(pts, image)
            self.app.notify_video_change('first_ts')
            self._next_frame = None

            self.player_state = 'playing'
            self.set_pause(True)
            return

        src_vid_size = ffplayer.get_metadata().get('src_vid_size')
        duration = ffplayer.get_metadata().get('duration')
        src_fmt = ffplayer.get_metadata().get('src_pix_fmt')

        # only get out of opening when we have the metadata
        if duration and src_vid_size[0] and src_vid_size[1] and src_fmt:
            self.video_size = src_vid_size
            self.duration = duration

            metadata = self._get_video_metadata(ffplayer, self.filename)

            fmt = {
                'gray': 'gray', 'rgb24': 'rgb24', 'bgr24': 'rgb24',
                'rgba': 'rgba', 'bgra': 'rgba'}.get(src_fmt, 'yuv420p')
            ffplayer.set_output_pix_fmt(fmt)
            ffplayer.toggle_pause()

            self.app.notify_video_change('opened', metadata)

    @app_error
    def _frame_callback(self, *largs):
        """Called on every kivy clock frame to update the video.
        """
        try:
            state = self.player_state
            if state == 'playing':
                self.callback_playing()
            elif state == 'opening':
                self.callback_opening()
            elif state == 'paused':
                pass
            elif state.startswith('seeking'):
                self.callback_seeking(state)
            elif state == 'finished':
                pass
            else:
                assert False
        except Exception:
            self.close_file()
            raise

    @app_error
    def seek(self, t, relative=False):
        """Seeks the video to given timestamp.

        :param t: The timestamp in video time.
        :param relative: The timestamp in video time.
        """
        if self.player_state not in ('playing', 'finished', 'paused'):
            return
        if self._last_frame is None:  # can't seek until we read first frame
            return

        self.reached_end = False
        if self.player_state == 'paused':
            self.player_state = 'seeking_paused'
            self.ff_player.set_pause(False)
        else:
            self.player_state = 'seeking'

        self.ff_player.seek(t, relative=relative, accurate=not relative)
        self.app.notify_video_change('seek')
        # clear the frame and note that we seeked. The next frame will have to
        # be a newly read frame after this
        self._next_frame = None
        self._seeked_since_frame = t
        self._seeking_skip_count = 0

    @app_error
    def set_pause(self, pause):
        """Sets the video player to pause/unpause.

        :param pause: Whether to pause/unpause.
        """
        if pause and self.player_state != 'playing':
            return
        if not pause and self.player_state != 'paused':
            return
        if self._last_frame is None:  # can't pause until we read first frame
            return

        self.paused = pause
        self._last_frame_clock = 0
        self.ff_player.set_pause(pause)
        self.player_state = 'paused' if pause else 'playing'

    def reopen_file(self):
        """Closes and re-opens the video file.
        """
        filename = self.filename
        self.close_file()
        self.open_file(filename)

    def gui_play_button_press(self):
        """Plays or pauses the video in response to the user pressing the
        play button in the GUI.
        """
        if self.paused:
            # always unpause, but if reached end, also seek to start
            self.set_pause(False)
            if self.reached_end:
                self.seek(0)
        else:
            # not paused, so if reached end, seek to start, otherwise pause
            if self.reached_end:
                self.seek(0)
            else:
                self.set_pause(True)

    def player_on_key_down(self, window, keycode, text, modifiers):
        """Handles any key down presses from the GUI that controls the player.
        """
        item = keycode[1]

        if item == 'up':
            if 0.1 < self.play_rate < 10:
                rate = self.play_rate = min(
                    10., math.pow(10, math.log10(self.play_rate) + .05))
                if rate == 10:
                    self.play_rate = float('inf')
            elif self.play_rate <= 0.1:
                self.play_rate = 0.2
            return True
        elif item == 'down':
            if 0.1 < self.play_rate < 10:
                rate = self.play_rate = max(
                    0.1, math.pow(10, math.log10(self.play_rate) - .05))
                if rate == 0.1:
                    self.play_rate = float('-inf')
            elif self.play_rate >= 10:
                self.play_rate = 9
            return True

        elif item == 'right':
            if self.filename:
                if self.play_rate >= 0.1:
                    self.seek(min(
                        self.last_frame_pts + self.seek_duration,
                        self.duration))
                else:
                    if self.player_state == 'playing':
                        self._last_frame_clock = 0
            return True
        elif item == 'left':
            if self.filename:
                self.seek(max(self.last_frame_pts - self.seek_duration, 0))
            return True

        elif item == 'spacebar':
            if self.filename:
                self.set_pause(not self.paused)
            return True
        return False

    def player_on_key_up(self, window, keycode):
        """Handles any key up presses from the GUI that controls the player.
        """
        item = keycode[1]
        if item in ('up', 'down', 'right', 'left', 'spacebar'):
            return True
        return False

    @classmethod
    def get_file_data(
            cls, filename: str, metadata_only: bool = False
    ) -> Tuple[List[float], dict]:
        """Returns the timestamps and metadata of the video file.
        """
        filename = os.path.abspath(filename)
        ff_opts = {
            'sync': 'video', 'an': True, 'sn': True, 'paused': False, 'x': 4,
            'y': 4, 'out_fmt': 'gray'}
        ffplayer = MediaPlayer(filename, ff_opts=ff_opts)

        # get metadata
        while True:
            src_vid_size = ffplayer.get_metadata().get('src_vid_size')
            duration = ffplayer.get_metadata().get('duration')
            src_fmt = ffplayer.get_metadata().get('src_pix_fmt')

            # only get out of opening when we have the metadata
            if duration and src_vid_size[0] and src_vid_size[1] and src_fmt:
                metadata = cls._get_video_metadata(ffplayer, filename)
                break

        # read video frames
        timestamps = []

        if not metadata_only:
            while True:
                frame, val = ffplayer.get_frame()

                assert val != 'paused'
                if val == 'eof':
                    break
                if frame is None:
                    time.sleep(.1)
                    continue
                timestamps.append(frame[1])

        ffplayer.close_player()
        return timestamps, metadata
