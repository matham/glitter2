import pandas as pd
import pytest

from glitter2.tests.coded_data import channel_names, get_rounded_list, \
    get_timestamps, get_event_data, get_pos_data, get_zone_metadata


def test_export_coded_data_stats(coded_data_file):
    from glitter2.analysis.export import SummeryStatsExporter, SourceFile
    from glitter2.analysis import AnalysisSpec, EventAnalysisChannel, \
        PosAnalysisChannel, ZoneAnalysisChannel

    in_spiral = 'in spiral'
    in_spiral_event = 'in spiral and event'
    spec = AnalysisSpec()
    spec.add_new_channel_computation(
        channel_names[1], in_spiral,
        PosAnalysisChannel.compute_pos_in_any_zone,
        zone_channels=[channel_names[2]]
    )
    spec.add_new_channel_computation(
        channel_names[0], in_spiral_event,
        EventAnalysisChannel.compute_combine_events_and,
        event_channels=[in_spiral]
    )

    event_channels = [channel_names[0], in_spiral, in_spiral_event]
    spec.add_computation(
        event_channels, EventAnalysisChannel.compute_active_duration,
        compute_key='a')
    spec.add_computation(
        event_channels, EventAnalysisChannel.compute_event_count,
        compute_key='b')
    spec.add_computation(
        event_channels, EventAnalysisChannel.compute_scored_duration,
        compute_key='c')

    spec.add_computation(
        [channel_names[1]], PosAnalysisChannel.compute_mean_speed,
        compute_key='d')
    spec.add_computation(
        [channel_names[1]], PosAnalysisChannel.compute_mean_center_distance,
        compute_key='e', zone_channel=channel_names[2])

    spec.add_computation(
        [channel_names[2]], ZoneAnalysisChannel.compute_centroid,
        compute_key='f')

    excel_file = coded_data_file.with_suffix('.xlsx')
    src = SourceFile(
        filename=coded_data_file, source_root=coded_data_file.parent)
    exporter = SummeryStatsExporter(spec=spec, export_filename=str(excel_file))
    exporter.init_process()
    exporter.process_file(src)
    if src.exception is not None:
        e, exec_info = src.exception
        print(exec_info)
        raise Exception(e)
    exporter.finish_process()

    df = pd.read_excel(excel_file, sheet_name='statistics')

    header = [
        'data file', 'video path', 'video filename', 'missed timestamps',
        'channel_type', 'channel', 'measure', 'measure_key', 'value']
    assert df.columns.to_list() == header

    data_file = set(df[header[0]].to_list())
    assert len(data_file) == 1
    assert list(data_file)[0].endswith(coded_data_file.with_suffix('.h5').name)

    assert len(set(df[header[1]].to_list())) == 1

    video_file = set(df[header[2]].to_list())
    assert video_file == {'video.mp4'}

    missed = set(df[header[3]].to_list())
    assert len(missed) == 1
    assert list(missed)[0] is False

    data = {}
    for _, row in df.iterrows():
        key = row[header[4]], row[header[5]], row[header[6]], row[header[7]]
        assert key not in data

        data[key] = row[header[8]]

    expected = {
        ('event', 'An event', 'active_duration', 'a'): 4.8,
        ('event', 'An event', 'event_count', 'b'): 12,
        ('event', 'An event', 'scored_duration', 'c'): 9.92,
        ('event', 'in spiral', 'active_duration', 'a'): 9.92,
        ('event', 'in spiral', 'event_count', 'b'): 1,
        ('event', 'in spiral', 'scored_duration', 'c'): 9.92,
        ('event', 'in spiral and event', 'active_duration', 'a'): 4.8,
        ('event', 'in spiral and event', 'event_count', 'b'): 12,
        ('event', 'in spiral and event', 'scored_duration', 'c'): 9.92,
        ('pos', 'A spiral', 'mean_speed', 'd'): 207.,
        ('pos', 'A spiral', 'mean_center_distance', 'e'): 32.868,
    }

    for key, value in expected.items():
        observed = data.pop(key)
        assert round(observed) == round(value)

    centroid = data.pop(('zone', 'A circle', 'centroid', 'f'))
    assert centroid == '(176.0, 99.0)'

    assert not data


def check_file_metadata(df):
    assert df.columns.to_list() == ['Property', 'Value']
    metadata = {key: value for _, (key, value) in df.iterrows()}
    assert metadata['ffpyplayer_version']
    assert metadata['glitter2_version']
    assert metadata['pixels_per_meter'] == 0
    assert metadata['saw_all_timestamps'] is True

    assert eval(metadata['src_pix_fmt'])
    assert metadata['file_size']
    assert metadata['filename_head']
    assert eval(metadata['src_vid_size']) == [352, 198]
    assert metadata['duration'] == 10.0
    assert eval(metadata['frame_rate']) == [25, 1]
    assert metadata['filename_tail'] == 'video.mp4'


def check_channels_metadata(df):
    assert df.columns.to_list() == ['Property', 'Value']
    channels_metadata = [(key, value) for _, (key, value) in df.iterrows()]

    start = 0
    for key in [('event_channel', 'An event'), ('name', 'An event'),
                ('pos_channel', 'A spiral'), ('name', 'A spiral'),
                ('zone_channel', 'A circle'), ('name', 'A circle')]:
        start = channels_metadata.index(key, start) + 1


def check_zones(df):
    assert df.columns.to_list() == ['Property', 'Value']
    zones = [(key, value) for _, (key, value) in df.iterrows()]

    start = 0
    for key in [('zone_channel', 'A circle'), ('center', '[176.0, 99.0]'),
                ('cls', 'PaintCircle'), ('radius', 82.5)]:
        start = zones.index(key, start) + 1


@pytest.mark.parametrize('dump_zone_collider', [False, True])
def test_export_coded_data_raw(coded_data_file, dump_zone_collider):
    from glitter2.analysis.export import RawDataExporter, SourceFile

    excel_file = coded_data_file.with_suffix('.xlsx')
    src = SourceFile(
        filename=coded_data_file, source_root=coded_data_file.parent)
    exporter = RawDataExporter(
        dump_zone_collider=dump_zone_collider,
        data_export_root=str(coded_data_file.parent))
    exporter.init_process()
    exporter.process_file(src)
    if src.exception is not None:
        e, exec_info = src.exception
        print(exec_info)
        raise Exception(e)
    exporter.finish_process()

    df_file_metadata = pd.read_excel(excel_file, sheet_name='file_metadata')
    check_file_metadata(df_file_metadata)

    df_channels_metadata = pd.read_excel(
        excel_file, sheet_name='channels_metadata')
    check_channels_metadata(df_channels_metadata)

    timestamps = get_timestamps(first_timestamp_repeated=True)
    df_timestamps = pd.read_excel(excel_file, sheet_name='timestamps')
    assert df_timestamps.columns.to_list() == ['timestamp']
    assert get_rounded_list(df_timestamps['timestamp']) == get_rounded_list(
        timestamps)

    df_events = pd.read_excel(excel_file, sheet_name='event_channels')
    assert df_events.columns.to_list() == [channel_names[0]]
    assert df_events[channel_names[0]].to_list() == get_event_data(timestamps)

    pos = get_pos_data(timestamps)
    x_data = get_rounded_list([x for x, y in pos], 3)
    y_data = get_rounded_list([y for x, y in pos], 3)
    x_name = f'{channel_names[1]}:x'
    y_name = f'{channel_names[1]}:y'
    zone_name = f'{channel_names[1]}:--:{channel_names[2]}'
    df_pos = pd.read_excel(excel_file, sheet_name='pos_channels')

    if dump_zone_collider:
        assert df_pos.columns.to_list() == [x_name, y_name, zone_name]
        assert df_pos[zone_name].to_list() == [True, ] * len(pos)
    else:
        assert df_pos.columns.to_list() == [x_name, y_name]
    assert get_rounded_list(df_pos[x_name].to_list(), 3) == x_data
    assert get_rounded_list(df_pos[y_name].to_list(), 3) == y_data

    df_zones = pd.read_excel(excel_file, sheet_name='zone_channels')
    check_zones(df_zones)
