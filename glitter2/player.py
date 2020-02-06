import time
import os

from ffpyplayer.player import MediaPlayer

from kivy.event import EventDispatcher
from kivy.clock import Clock
from kivy.properties import BooleanProperty, NumericProperty

__all__ = ('GlitterPlayer', )


class GlitterPlayer(EventDispatcher):

    filename = ''

    ff_player = None

    reached_end = BooleanProperty(False)

    play_rate = NumericProperty(1)

    video_size = None

    duration = 0

    app = None

    _frame_trigger = None

    player_state = 'none'
    """Can be one of opening, seeking_paused, none, playing, finished, paused.
    """

    _last_frame_clock = 0

    _last_frame_pts = 0

    _last_frame = None

    def __int__(self, app, **kwargs):
        super(GlitterPlayer, self).__init__(**kwargs)
        self.app = app
        self._frame_trigger = Clock.create_trigger(
            self._frame_callback, timeout=0, interval=True)

    def _player_callback(self, selector, value):
        if selector == 'quit':
            def close(*args):
                pass
            Clock.schedule_once(close, 0)

    def open_file(self, filename):
        self.close_file()

        filename = os.path.abspath(filename)
        ff_opts = {'paused': False, 'an': True}
        self.ff_player = MediaPlayer(
            filename, callback=self._player_callback, ff_opts=ff_opts)
        self.player_state = 'opening'
        self.filename = filename
        self._frame_trigger()

    def close_file(self):
        self.player_state = 'none'
        self._frame_trigger.cancel()
        self.video_size = None
        self.duration = 0
        self._last_frame = None
        self._last_frame_clock = 0
        self._last_frame_pts = 0

        if self.ff_player is not None:
            self.ff_player.close_player()
            self.ff_player = None

    def _frame_callback(self, *largs):
        ffplayer = self.ff_player
        state = self.player_state

        if state == 'playing':
            frame, val = ffplayer.get_frame()

            assert val != 'paused'
            if val == 'eof':
                self.player_state = 'finished'
                self.reached_end = True
                if self._last_frame_clock:
                    # only if we hit eof after seeing a previous frame
                    self.app.notify_video_change('last_ts')
                return
            if frame is None:
                return

            first_frame = self._last_frame is None
            image, pts = frame

            self._last_frame_clock = time.perf_counter()
            self._last_frame = image
            self._last_frame_pts = pts

            self.app.add_video_frame(pts, image)
            if first_frame:
                self.app.notify_video_change('first_ts')
        elif state == 'opening':
            src_vid_size = ffplayer.get_metadata().get('src_vid_size')
            duration = ffplayer.get_metadata().get('duration')

            if duration and src_vid_size:
                self.video_size = src_vid_size
                self.duration = duration
                metadata = ffplayer.get_metadata()
                metadata['filename'] = self.filename
                self.app.notify_video_change('opened', metadata)
                self.player_state = 'playing'
        elif state == 'paused':
            pass
        elif state == 'seeking_paused':
            frame, val = ffplayer.get_frame()

            assert val != 'paused'
            if val == 'eof':
                self.player_state = 'finished'
                self.reached_end = True
                return
            if frame is None:
                return

            image, pts = frame
            self._last_frame = image
            self.app.add_video_frame(pts, image)
            ffplayer.set_pause(True)
            self.player_state = 'paused'
        elif state == 'finished':
            pass
        else:
            assert False

    def seek(self, t):
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
        self._last_frame_clock = 0

    def set_pause(self, pause):
        if pause and self.player_state != 'playing':
            return
        if not pause and self.player_state != 'paused':
            return
        if self._last_frame is None:  # can't pause until we read first frame
            return

        self._last_frame_clock = 0
        self.ff_player.set_pause(pause)
        self.player_state = 'paused' if pause else 'playing'
