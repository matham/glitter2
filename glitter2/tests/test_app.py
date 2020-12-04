from typing import List, Set
from pathlib import Path

from kivy.tests.async_common import AsyncUnitTestTouch

from glitter2.analysis import FileDataAnalysis
from glitter2.tests.app import touch_widget, Glitter2TestApp
from glitter2.tests.coded_data import check_metadata, check_channel_metadata, \
    check_channel_data, get_timestamps, get_rounded_list, get_event_data, \
    get_pos_data, get_zone_metadata, channel_names


def get_contents(filename: Path, ignore=('.yaml', )) -> Set[str]:
    return {
        f.name for f in filename.parent.iterdir() if f.suffix not in ignore}


async def wait_for_next_frame(glitter_app: Glitter2TestApp, last_frame):
    while glitter_app.player._next_frame is last_frame:
        if glitter_app.player.reached_end:
            return None, None
        await glitter_app.async_sleep(.05)

    frame = glitter_app.player._next_frame
    pts = glitter_app.player.last_frame_pts
    return frame, pts


async def add_circle(glitter_app: Glitter2TestApp):
    zone_metadata = get_zone_metadata()

    show_zones = glitter_app.resolve_widget().down(test_name='show_zones')()
    await touch_widget(glitter_app, show_zones)
    edit_zones = glitter_app.resolve_widget().down(test_name='edit_zones')()
    await touch_widget(glitter_app, edit_zones)
    paint_circle = glitter_app.resolve_widget().down(
        test_name='paint_circle')()
    await touch_widget(glitter_app, paint_circle)

    center = zone_metadata['shape_config']['center']
    radius = zone_metadata['shape_config']['radius']

    pos_painter = glitter_app.resolve_widget().down(test_name='pos_painter')()
    await touch_widget(glitter_app, pos_painter, pos=center, duration=0)

    zone = glitter_app.channel_controller.zone_channels[0]
    zone.name = channel_names[2]
    zone.shape.radius = radius
    await glitter_app.wait_clock_frames(2)

    await touch_widget(glitter_app, edit_zones)


async def test_code_data_in_gui(
        glitter_app: Glitter2TestApp, sample_video_file):
    last_frame = None
    data_file = sample_video_file.with_suffix('.h5')
    assert get_contents(sample_video_file) == {sample_video_file.name}
    glitter_app.storage_controller.ui_open_file(str(sample_video_file))

    backup = Path(glitter_app.storage_controller.backup_filename).name
    assert get_contents(sample_video_file) == {
        sample_video_file.name, data_file.name, backup}

    while glitter_app.player.player_state == 'opening':
        await glitter_app.async_sleep(.05)

    await add_circle(glitter_app)

    await glitter_app.wait_clock_frames(2)
    slider = glitter_app.resolve_widget().down(test_name='rate_slider')()
    slider.value = -1
    await glitter_app.wait_clock_frames(2)

    play = glitter_app.resolve_widget().down(test_name='play_button')()
    await touch_widget(glitter_app, play)

    event_channel = glitter_app.create_channel('event')
    await glitter_app.wait_clock_frames(2)
    pos_channel = glitter_app.create_channel('pos')
    await glitter_app.wait_clock_frames(2)
    event_channel.name = channel_names[0]
    pos_channel.name = channel_names[1]
    await glitter_app.wait_clock_frames(2)

    timestamps = get_timestamps()

    event = get_event_data(timestamps)[::-1]
    event_button = glitter_app.resolve_widget().down(
        test_name='event_state_button')()
    event_center = event_button.to_window(*event_button.center)

    pos_painter = glitter_app.resolve_widget().down(test_name='pos_painter')()

    pos = get_pos_data(timestamps)[::-1]
    pos_button = glitter_app.resolve_widget().down(
        test_name='pos_selection_button')()
    await touch_widget(glitter_app, pos_button)

    player_times = []
    touch = None
    while True:
        last_frame, pts = await wait_for_next_frame(glitter_app, last_frame)
        if touch is not None:
            touch.touch_up()
            touch = None
        if pts is None:
            break

        if event.pop():
            touch = AsyncUnitTestTouch(*event_center)
            touch.touch_down()

        await touch_widget(
            glitter_app, pos_painter, pos=pos.pop(), duration=.01)

        player_times.append(pts)

    assert get_rounded_list(timestamps) == get_rounded_list(player_times)

    assert glitter_app.storage_controller.data_file.saw_all_timestamps

    assert glitter_app.storage_controller.has_unsaved
    save = glitter_app.resolve_widget().down(test_name='save_button')()
    await touch_widget(glitter_app, save)
    assert not glitter_app.storage_controller.has_unsaved

    with FileDataAnalysis(filename=str(data_file)) as analysis:
        analysis.load_file_data()

        check_metadata(analysis, video_filename=str(sample_video_file.name))
        check_channel_data(analysis)
