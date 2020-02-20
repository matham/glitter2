"""Video Player
===============

Plays the video files that are scored by Glitter.
"""
from os.path import join, dirname
from typing import Tuple, Optional
import time
import math
import os

from ffpyplayer.player import MediaPlayer
from ffpyplayer.pic import Image

from kivy.event import EventDispatcher
from kivy.clock import Clock
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.lang import Builder

from base_kivy_app.app import app_error

__all__ = ('GlitterPlayer', )


class GlitterPlayer(EventDispatcher):
    """Player that reads from the video file and sends frames as they need to
    be displayed.
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

    play_rate = 1
    """The playing rate with which we play the video.
    """

    video_size: Optional[Tuple[int, int]] = None
    """The size of the video frames, set once the file is open. Read only.
    """

    duration: float = 0
    """The duration of of the video, set once the file is open. Read only.
    """

    app = None
    """The Glitter app.
    """

    paused = BooleanProperty(True)

    _frame_trigger = None
    """Trigger to call to get the next frame. This is automatically called
    each kivy clock frame by the kivy clock.
    """

    player_state: str = 'none'
    """The current state of the player.

    Can be one of opening, seeking_paused, none, playing, finished, paused.
    """

    _last_frame_clock: float = 0
    """System time when we showed the last frame. Zero means show next frame
    immediately since there's no previous frame.
    """

    _last_frame_pts: float = 0
    """The timestamp (pts) in video time of the last shown frame.
    """

    _last_frame: Optional[Image] = None
    """The last frame shown.
    """

    _next_frame: Optional[Tuple[Image, float]] = None
    """We keep here the next frame until we show it at the right time.
    """

    _seeked_since_frame = False
    """This keeps track whether we have seeked since seeing the last frame.
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

    def set_play_rate(self, val: float, is_log=True):
        if is_log:
            max_val = 1
            min_val = -1
        else:
            max_val = 10
            min_val = -10

        val = max(min(val, max_val), min_val)
        if val == max_val:
            self.play_rate = float('inf')
            return '10', 1
        elif val == min_val:
            self.play_rate = float('-inf')
            return '-10', -1
        else:
            if is_log:
                val = math.pow(10, val)
            self.play_rate = val
            return '{:0.2f}'.format(val), math.log10(val)

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
        self._last_frame_pts = 0
        self.reached_end = False
        self._next_frame = None
        self._seeked_since_frame = False
        self.filename = ''
        self.paused = True

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
                    (pts - self._last_frame_pts) / self.play_rate - (t - ts))

            if remaining_t < 0.005:
                self._last_frame_clock = t
                self._last_frame = image
                self._last_frame_pts = pts

                # there has been no seeking since this frame was read, because
                # the frame is cleared during a seek
                self._seeked_since_frame = False
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
            if not self._seeked_since_frame:
                # only if we hit eof after seeing a previous frame
                self.app.notify_video_change('last_ts')
            return
        if frame is None:
            return

        self._next_frame = frame

    def callback_seeking_paused(self):
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

        # simply display this frame
        self._last_frame, self._last_frame_pts = frame
        self.app.add_video_frame(self._last_frame_pts, self._last_frame)
        self._seeked_since_frame = False  # reset as above

        # if we got a frame, we can pause again
        ffplayer.set_pause(True)
        self.player_state = 'paused'

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
            self._last_frame_pts = pts
            self._seeked_since_frame = False
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

            metadata = ffplayer.get_metadata()
            filename = os.path.abspath(os.path.expanduser(self.filename))
            head, tail = os.path.split(filename)
            metadata['filename_head'] = head
            metadata['filename_tail'] = tail
            metadata['file_size'] = os.stat(filename).st_size

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
            elif state == 'seeking_paused':
                self.callback_seeking_paused()
            elif state == 'finished':
                pass
            else:
                assert False
        except Exception:
            self.close_file()
            raise

    @app_error
    def seek(self, t):
        """Seeks the video to given timestamp.

        :param t: The timestamp in video time.
        """
        if self.player_state not in ('playing', 'finished', 'paused'):
            return
        if self._last_frame is None:  # can't seek until we read first frame
            return

        self.reached_end = False
        if self.player_state == 'paused':
            self.player_state = 'seeking_paused'
            self.ff_player.set_pause(False)
        elif self.player_state == 'finished':
            self.player_state = 'playing'

        self.ff_player.seek(t, relative=False, accurate=True)
        self.app.notify_video_change('seek')
        # clear the frame and note that we seeked. The next frame will have to
        # be a newly read frame after this
        self._next_frame = None
        self._seeked_since_frame = True

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


Builder.load_file(join(dirname(__file__), 'player_style.kv'))
