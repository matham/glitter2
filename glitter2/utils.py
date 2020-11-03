"""Utilities
============

Used across glitter2.
"""

import re
from itertools import chain

from kivy.animation import Animation
from kivy.properties import NumericProperty, BooleanProperty
from kivy.factory import Factory
from kivy.clock import Clock

__all__ = ('fix_name', 'LoadingAnim')

_name_pat = re.compile('^(.+)-([0-9]+)$')


def fix_name(name, *names, ignore_case=True):
    '''Fixes the name so that it is unique among the names in ``names``.

    :Params:

        `name`: str
            A name of something
        `*names`: iterables of strings
            Positional argument, where each is a iterable of strings among
            which we ensure that the returned name is unique.

    :returns:

        A string that is unique among all the ``names``, but is similar to
        ``name``. We append a integer to make it unique.

    E.g.::

        >>> fix_name('troll', ['toll', 'foll'], ['bole', 'cole'])
        'troll'
        >>> fix_name('troll', ['troll', 'toll', 'foll'], ['bole', 'cole'])
        'troll-2'
        >>> fix_name('troll', ['troll-2', 'toll', 'foll'], ['bole', 'cole'])
        'troll'
        >>> fix_name('troll', ['troll', 'troll-2', 'toll', 'foll'], \
['bole', 'cole'])
        'troll-3'
    '''
    normalized_name = name.lower()
    if ignore_case:
        normalized_names = list(chain(
            *(map(str.lower, name_list) for name_list in names)))
    else:
        normalized_names = list(chain(*names))

    if normalized_name not in normalized_names:
        return name

    m = re.match(_name_pat, name)
    i = 2
    if m is not None:
        name, i = m.groups()
        i = int(i)

    new_name = '{}-{}'.format(name, i)
    normalized_new_name = new_name.lower()
    while normalized_new_name in normalized_names:
        i += 1
        new_name = '{}-{}'.format(name, i)
        normalized_new_name = new_name.lower()

    return new_name


class LoadingAnim(object):

    anim_active = BooleanProperty(False)

    angle = NumericProperty(0)

    _anim = None

    _anim_trigger = None

    def __init__(self, **kwargs):
        super(LoadingAnim, self).__init__(**kwargs)
        self.fbind('anim_active', self._anim_active)
        self._anim_trigger = Clock.create_trigger(self._handle_anim_done)

    def _handle_anim_done(self, *largs):
        if self.anim_active:
            self.angle = 0
            self._anim.start(self)

    def _anim_active(self, *largs):
        if self.anim_active:
            if self._anim is None:
                self._anim = Animation(angle=360, duration=1)
                self._anim.fbind('on_complete', self._anim_trigger)

            self.angle = 0
            self._anim.start(self)
        else:
            self._anim.cancel(self)
            self.angle = 0
            self._anim_trigger.cancel()


Factory.register(classname='LoadingAnim', cls=LoadingAnim)
