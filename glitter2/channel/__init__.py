from kivy.properties import NumericProperty
from kivy.event import EventDispatcher

__all__ = ('ChannelController', 'ChannelBase', 'EventChannel', 'PosChannel',
           'ZoneChannel')


class ChannelController(EventDispatcher):
    pass


class ChannelBase(EventDispatcher):
    pass


class EventChannel(ChannelBase):
    pass


class PosChannel(ChannelBase):
    pass


class ZoneChannel(ChannelBase):
    pass
