
import nixio

from glitter2.analysis import FileDataAnalysis
from glitter2.storage.data_file import DataFile
from glitter2.player import GlitterPlayer
from glitter2.tests.coded_data import check_metadata, check_channel_metadata, \
    check_channel_data, channel_names, get_timestamps, get_zone_metadata, \
    get_event_data, get_pos_data


def test_create_set_data(sample_video_file):
    data_filename = str(sample_video_file.with_suffix('.h5'))

    nix_file = nixio.File.open(data_filename, nixio.FileMode.Overwrite)
    data_file = DataFile(nix_file=nix_file)
    data_file.init_new_file()

    # read all the frame timestamps and video metadata from the video file, this
    # may take some time as all the frames are read
    _, video_metadata = GlitterPlayer.get_file_data(
        str(sample_video_file), metadata_only=True)
    timestamps = get_timestamps()

    event = get_event_data(timestamps)
    pos = get_pos_data(timestamps)
    zone_metadata = get_zone_metadata()

    data_file.set_file_data(
        video_file_metadata=video_metadata, saw_all_timestamps=True,
        timestamps=[timestamps],
        event_channels=[({'name': channel_names[0]}, [event])],
        pos_channels=[({'name': channel_names[1]}, [pos])],
        zone_channels=[zone_metadata])

    nix_file.close()

    with FileDataAnalysis(filename=data_filename) as analysis:
        analysis.load_file_data()

        check_metadata(analysis, video_filename=str(sample_video_file.name))
        check_channel_data(analysis)


def test_create_data_live(sample_video_file):
    data_filename = str(sample_video_file.with_suffix('.h5'))

    nix_file = nixio.File.open(data_filename, nixio.FileMode.Overwrite)
    data_file = DataFile(nix_file=nix_file)
    data_file.init_new_file()

    # read all the frame timestamps and video metadata from the video file, this
    # may take some time as all the frames are read
    _, video_metadata = GlitterPlayer.get_file_data(
        str(sample_video_file), metadata_only=True)
    data_file.video_metadata_dict = video_metadata
    timestamps = get_timestamps()

    event = data_file.create_channel('event')
    event.channel_config_dict = {'name': channel_names[0]}
    event_data = get_event_data(timestamps)

    pos = data_file.create_channel('pos')
    pos.channel_config_dict = {'name': channel_names[1]}
    pos_data = get_pos_data(timestamps)

    zone = data_file.create_channel('zone')
    zone.channel_config_dict = get_zone_metadata()

    for i, t in enumerate(timestamps):
        data_file.notify_add_timestamp(t)
        if not i:
            data_file.notify_saw_first_timestamp()

        event.set_timestamp_value(t, event_data[i])
        pos.set_timestamp_value(t, pos_data[i])

    data_file.notify_saw_last_timestamp()
    nix_file.close()

    with FileDataAnalysis(filename=data_filename) as analysis:
        analysis.load_file_data()

        check_metadata(analysis, video_filename=str(sample_video_file.name))
        check_channel_data(analysis)
