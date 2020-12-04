import trio

from kivy.config import Config
Config.set('graphics', 'width', '1600')
Config.set('graphics', 'height', '900')
Config.set('modules', 'touchring', '')
for items in Config.items('input'):
    Config.remove_option('input', items[0])


from glitter2.main import Glitter2App
from kivy.tests.async_common import UnitKivyApp


__all__ = (
    'Glitter2TestApp', 'replace_text', 'touch_widget', 'select_spinner_value',
    'escape')


async def replace_text(app, text_widget, new_text):
    # activate it
    async for _ in app.do_touch_down_up(widget=text_widget):
        pass

    # select all
    ctrl_it = app.do_keyboard_key(key='lctrl', modifiers=['ctrl'])
    await ctrl_it.__anext__()  # down
    async for _ in app.do_keyboard_key(key='a', modifiers=['ctrl']):
        pass
    await ctrl_it.__anext__()  # up

    # replace text
    for key in ['delete'] + list(new_text) + ['enter']:
        async for _ in app.do_keyboard_key(key=key):
            pass

    await app.wait_clock_frames(2)


async def touch_widget(app, widget, pos=None, duration=.2):
    async for _ in app.do_touch_down_up(
            widget=widget, pos=pos, duration=duration):
        pass
    await app.wait_clock_frames(2)


async def select_spinner_value(func_app, func_name, spinner):
    from kivy.metrics import dp
    async for _ in func_app.do_touch_down_up(
            pos=spinner.to_window(spinner.x + dp(30), spinner.center_y)):
        pass
    await func_app.wait_clock_frames(2)

    label = func_app.resolve_widget().down(text=func_name)()
    await touch_widget(func_app, label)
    await func_app.wait_clock_frames(2)


async def escape(app):
    async for _ in app.do_keyboard_key(key='escape'):
        pass
    await app.wait_clock_frames(2)


async def exhaust(async_it):
    async for _ in async_it:
        pass


class Glitter2TestApp(Glitter2App, UnitKivyApp):

    def __init__(self, data_path, **kwargs):
        self._data_path = data_path
        super().__init__(**kwargs)

    async def async_sleep(self, dt):
        await trio.sleep(dt)

    def check_close(self):
        return True

    def handle_exception(self, msg, exc_info=None, level='error', *largs):
        super().handle_exception(msg, exc_info, level, *largs)

        if isinstance(exc_info, str):
            self.get_logger().error(msg)
            self.get_logger().error(exc_info)
        elif exc_info is not None:
            tp, value, tb = exc_info
            try:
                if value is None:
                    value = tp()
                if value.__traceback__ is not tb:
                    raise value.with_traceback(tb)
                raise value
            finally:
                value = None
                tb = None
        elif level in ('error', 'exception'):
            raise Exception(msg)
