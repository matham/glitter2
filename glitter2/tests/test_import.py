from glitter2.analysis import FileDataAnalysis
from glitter2.tests.coded_data import check_metadata, check_channel_data, \
    get_timestamps, get_pos_data, get_rounded_list, channel_names, \
    get_event_data


def test_import_csv(sample_csv_data_file):
    from glitter2.analysis.export import CSVImporter, SourceFile

    hf_file = sample_csv_data_file.parent.joinpath('video.h5')
    src = SourceFile(
        filename=sample_csv_data_file, source_root=sample_csv_data_file.parent)
    exporter = CSVImporter(output_files_root=str(sample_csv_data_file.parent))
    exporter.init_process()
    exporter.process_file(src)
    if src.exception is not None:
        e, exec_info = src.exception
        print(exec_info)
        raise Exception(e)
    exporter.finish_process()

    with FileDataAnalysis(filename=str(hf_file)) as analysis:
        analysis.load_file_data()

        check_metadata(analysis)
        check_channel_data(analysis, first_timestamp_repeated=True)


def test_import_clever_sys(sample_clever_sys_data_file):
    from glitter2.analysis.export import CleverSysImporter, SourceFile

    hf_file = sample_clever_sys_data_file.parent / 'output' / 'video.h5'
    src = SourceFile(
        filename=sample_clever_sys_data_file,
        source_root=sample_clever_sys_data_file.parent)
    exporter = CleverSysImporter(
        output_files_root=str(sample_clever_sys_data_file.parent / 'output'))
    exporter.init_process()
    exporter.process_file(src)
    if src.exception is not None:
        e, exec_info = src.exception
        print(exec_info)
        raise Exception(e)
    exporter.finish_process()

    with FileDataAnalysis(filename=str(hf_file)) as analysis:
        analysis.load_file_data()

        check_metadata(analysis)

        channels_metadata = analysis.channels_metadata
        assert channels_metadata['CenterArea']['name'] == 'CenterArea'
        assert channels_metadata['animal_center']['name'] == 'animal_center'
        assert channels_metadata['animal_nose']['name'] == 'animal_nose'

        assert list(analysis.event_channels_data.keys()) == []
        assert list(analysis.pos_channels_data.keys()) == [
            'animal_center', 'animal_nose']
        assert list(analysis.zone_channels_shapes.keys()) == ['CenterArea']

        # timestamps
        timestamps = get_rounded_list(analysis.timestamps)
        computed = get_timestamps(True)
        assert get_rounded_list(computed) == timestamps

        # pos channel
        pos = (
            [(x, 198 - y) for x, y in get_pos_data(computed)], 1)[3:-8]
        src_pos1 = (
            analysis.pos_channels_data['animal_center'], 1)[3:-8]
        src_pos2 = (
            analysis.pos_channels_data['animal_nose'], 1)[3:-8]
        assert get_rounded_list(pos, 1) == get_rounded_list(src_pos1, 1)
        assert get_rounded_list(pos, 1) == get_rounded_list(src_pos2, 1)

        shape = analysis.zone_channels_shapes['CenterArea']

        from kivy_garden.painter import PaintCircle
        assert isinstance(shape, PaintCircle)
        x, y = shape.center
        assert [round(x), round(y)] == [176.0, 99.0]
        assert shape.radius == 82.5


def test_import_legacy_h5(sample_legacy_data_file):
    from glitter2.analysis.export import LegacyGlitterImporter, SourceFile

    hf_file = sample_legacy_data_file.parent / 'output' / 'video.h5'
    src = SourceFile(
        filename=sample_legacy_data_file,
        source_root=sample_legacy_data_file.parent)
    exporter = LegacyGlitterImporter(
        output_files_root=str(sample_legacy_data_file.parent / 'output'))
    exporter.init_process()
    exporter.process_file(src)
    if src.exception is not None:
        e, exec_info = src.exception
        print(exec_info)
        raise Exception(e)
    exporter.finish_process()

    with FileDataAnalysis(filename=str(hf_file)) as analysis:
        analysis.load_file_data()

        check_metadata(analysis, restricted=True)

        channels_metadata = analysis.channels_metadata
        assert channels_metadata[channel_names[0]]['name'] == channel_names[0]
        assert channels_metadata[channel_names[1]]['name'] == channel_names[1]

        assert list(analysis.event_channels_data.keys()) == [channel_names[0]]
        assert list(analysis.pos_channels_data.keys()) == [channel_names[1]]
        assert list(analysis.zone_channels_shapes.keys()) == []

        # timestamps
        timestamps = get_rounded_list(analysis.timestamps)
        computed = get_timestamps(True)
        assert get_rounded_list(computed[1:-1]) == timestamps

        event = get_event_data(computed)[1:-1]
        assert event == analysis.event_channels_data[channel_names[0]].tolist()

        # pos channel
        pos = get_pos_data(computed)[1:-1]
        src_pos = get_rounded_list(
            analysis.pos_channels_data[channel_names[1]], 0)
        assert [[int(x), int(y)] for x, y in pos] == src_pos
