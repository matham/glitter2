"""Video Player widgets
=======================

Widgets used by the video player.
"""
from os.path import join, dirname
import math

from kivy.lang import Builder
from kivy.metrics import dp
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

    def get_sub_divisions(self, div_width) -> 1:
        sub_div = int(dp(div_width) / dp(15))
        if sub_div >= 10:
            return 10
        if sub_div >= 5:
            return 5
        if sub_div >= 2:
            return 2
        if sub_div >= 1:
            return 1
        return 0

    def compute_ticks_spacing(self, graph, width, duration) -> int:
        if duration <= 1:
            graph.x_ticks_minor = self.get_sub_divisions(width)
            return 1

        max_divs = max(1, int(dp(width) / dp(50)))
        if max_divs == 1:
            spacing = math.ceil(duration)
            graph.x_ticks_minor = self.get_sub_divisions(width)
            return spacing

        # duration is at least 1 and spacing is increasing from 1,
        # so num_divs ceil will be at least 1. max_divs is at least 1, so
        # num_divs will decrease to 1 and stop there
        spacing = 1
        num_divs = math.ceil(duration / spacing)
        while num_divs > max_divs:
            spacing *= 10
            num_divs = math.ceil(duration / spacing)

        graph.x_ticks_minor = self.get_sub_divisions(width / num_divs)
        if spacing > duration:
            spacing = math.floor(duration)
        return spacing


Builder.load_file(join(dirname(__file__), 'player_style.kv'))
