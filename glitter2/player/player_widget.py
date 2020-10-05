"""Video Player widgets
=======================

Widgets used by the video player.
"""
from os.path import join, dirname

from kivy.lang import Builder
from kivy.uix.slider import Slider

__all__ = ('SeekSlider', )


class SeekSlider(Slider):
    """widget that controls the speed of video playback."""

    __events__ = ('on_release', )

    def on_touch_up(self, touch):
        if super(SeekSlider, self).on_touch_up(touch):
            self.dispatch('on_release')
            return True
        return False

    def on_release(self, *args):
        pass


Builder.load_file(join(dirname(__file__), 'player_style.kv'))
