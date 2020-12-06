import numpy as np
import math

from glitter2.analysis import FileDataAnalysis

__all__ = (
    'channel_names', 'get_timestamps', 'get_event_data', 'get_pos_data',
    'get_zone_metadata',
    'check_metadata', 'check_channel_metadata', 'check_channel_data',
    'get_rounded_list')

channel_names = ('An event', 'A spiral', 'A circle')


def get_rounded_list(data, decimals=2):
    return np.asarray(data).round(decimals=decimals).tolist()


def get_timestamps(first_timestamp_repeated=False):
    if first_timestamp_repeated:
        timestamps = np.arange(250) * .04 + .04
        timestamps[0] = timestamps[1]
    else:
        timestamps = (np.arange(250) * .04 + .04)[1:]
    return timestamps


def get_event_data(timestamps):
    event = []
    for i in range(len(timestamps)):
        event.append((i // 10) % 2)
    return event


def get_pos_data(timestamps):
    pos = []

    width, height = 352, 198
    angle = 20 * math.pi / len(timestamps)
    extent = 1 / 3 * min(width, height)

    center_x = width / 2
    center_y = height / 2

    for i in range(len(timestamps)):
        current_angle = i * angle
        pos.append((
            center_x + i / len(timestamps) * extent * math.cos(current_angle),
            center_y + i / len(timestamps) * extent * math.sin(current_angle)
        ))

    return pos


def get_zone_metadata():
    from kivy_garden.painter import PaintCircle
    width, height = 352, 198
    center_x = width / 2
    center_y = height / 2

    circle = PaintCircle.create_shape(
        [center_x, center_y], 5 / 12 * min(width, height))
    zone_metadata = {'name': 'A circle', 'shape_config': circle.get_state()}
    return zone_metadata


def check_metadata(
        analysis: FileDataAnalysis, pixels_per_meter=0,
        video_filename='video.mp4', restricted=False):
    assert analysis.metadata['ffpyplayer_version']
    assert analysis.metadata['glitter2_version']
    assert analysis.metadata['pixels_per_meter'] == pixels_per_meter
    assert analysis.metadata['saw_all_timestamps']

    if not restricted:
        assert analysis.video_metadata['src_pix_fmt']
        assert analysis.video_metadata['file_size']
        assert analysis.video_metadata['frame_rate'] == [25, 1]
    assert analysis.video_metadata['filename_head']
    assert analysis.video_metadata['src_vid_size'] == [352, 198]
    assert analysis.video_metadata['duration'] == 10.0
    assert analysis.video_metadata['filename_tail'] == video_filename


def check_channel_metadata(analysis: FileDataAnalysis):
    assert set(analysis.channels_metadata.keys()) == set(channel_names)
    channels_metadata = analysis.channels_metadata

    for name in channel_names:
        assert channels_metadata[name]['name'] == name
    for i, data in enumerate((
            analysis.event_channels_data, analysis.pos_channels_data,
            analysis.zone_channels_shapes)):
        assert data == {channel_names[i]: None}


def check_channel_data(
        analysis: FileDataAnalysis, first_timestamp_repeated=False):
    assert set(analysis.channels_metadata.keys()) == set(channel_names)
    channels_metadata = analysis.channels_metadata

    for name in channel_names:
        assert channels_metadata[name]['name'] == name

    for i, data in enumerate((
            analysis.event_channels_data, analysis.pos_channels_data,
            analysis.zone_channels_shapes)):
        assert list(data.keys()) == [channel_names[i]]

    # timestamps
    timestamps = get_rounded_list(analysis.timestamps)
    computed = get_rounded_list(get_timestamps(first_timestamp_repeated))
    assert computed == timestamps

    # event channel
    event = get_event_data(timestamps)
    assert event == analysis.event_channels_data[channel_names[0]].tolist()

    # pos channel
    pos = get_pos_data(timestamps)
    src_pos = get_rounded_list(analysis.pos_channels_data[channel_names[1]], 1)
    assert get_rounded_list(pos, 1) == src_pos

    shape = analysis.zone_channels_shapes[channel_names[2]]

    from kivy_garden.painter import PaintCircle
    assert isinstance(shape, PaintCircle)
    x, y = shape.center
    assert [round(x), round(y)] == [176.0, 99.0]
    assert shape.radius == 82.5
