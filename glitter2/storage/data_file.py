"""Data file
============

Data channel methods, unless specified should not be called directly.
"""

import numpy as np
from typing import List, Dict, Optional, Tuple, Callable, Set, Union, Any, Type
import nixio as nix
from nixio.exceptions.exceptions import InvalidFile
from bisect import bisect_left

from more_kivy_app.utils import yaml_dumps, yaml_loads

__all__ = (
    'DataFile', 'DataChannelBase', 'TemporalDataChannelBase',
    'EventChannelData', 'PosChannelData', 'ZoneChannelData', 'read_nix_prop')


def read_nix_prop(prop):
    """Returns a nox property value across different nix versions.

    :param prop: the nix Property.
    :return: The value stored in the property.
    """
    try:
        return prop.values[0].value
    except AttributeError:
        return prop.values[0]


def _unsaved_callback():
    pass


class DataFile(object):
    """Data file interface to the NixIO file that stores the video file
    annotated data.

    Data for the timestamps and all channels are similarly stored in a
    list of arrays. See :attr:`timestamps_arrays` for details.

    Once a file is opened with :meth:`open_file`, the ``notify_xxx`` form a
    state machine and must be called as appropriate.

    Specifically, the first timestamp added from the video file with
    :meth:`notify_add_timestamp` must be the very first frame's timestamp and
    it must be followed by a call to :meth:`notify_saw_first_timestamp`.

    Then each frame must be read sequentially with no skipping. If a frame is
    skipped at any time, e.g. by seeking, before we add the new timestamp
    with :meth:`notify_add_timestamp`, you must call
    :meth:`notify_interrupt_timestamps` to indicate the seek.

    Whenever we read the last timestamp (even if we skipped some intermediate
    timestamps, e.g. due to a seek) :meth:`notify_saw_last_timestamp` must
    called after adding that timestamp with :meth:`notify_add_timestamp`.

    If we have seen the first and last timestamp and each consecutive pair of
    timestamps were seen with no :meth:`notify_interrupt_timestamps` between
    them, that's when we consider having seen all frames and
    :attr:`saw_all_timestamps` is automatically set to the True and
    :attr:`timestamps` becomes the singular timestamps array.
    """

    unsaved_callback: Callable = None
    """Callback that is called whenever the data file changes.
    """

    nix_file: nix.File = None
    """NixIO data file.
    """

    app_config_section: nix.Section = None
    """Stores the overall application configuration that was used with
    this video file.
    """

    video_metadata_section: nix.Section = None
    """Stores the metadata of the video file.
    """

    timestamps: nix.DataArray = None
    """The first timestamps data array containing the very first timestamps of
    the video file, created when the data file is created.
    See :attr:`timestamps_arrays`.

    If there's only one array in :attr:`timestamps_arrays`
    (e.g. after we saw all the timestamps of the video file), this is referring
    to it.
    """

    timestamps_arrays: Dict[int, nix.DataArray] = {}
    """Map of disjointed timestamps arrays representing known closed
    intervals of the video file.

    Consider how data is coded. We play frame after frame and the user
    annotates each frame. And as we see each timestamps in a
    strictly-increasing order, we could just have a list of timestamps and
    corresponding state that is continuously increasing by one element as we
    see a new frame.

    Unfortunately, a user may skip some frames by seeking ahead, thereby
    breaking continuity, because now we have missing timestamps in the middle
    and we don't know what they are. Therefore we have a list, or mapping of
    timestamps arrays, each timestamp array represents a known interval of
    timestamps during which we didn't seek and we have every timestamp in that
    interval.

    The keys of :attr:`timestamps_arrays` are not meaningful, except for
    key ``0`` which is the same array as :attr:`timestamps` and is the array
    with the first timestamps of the video.

    To get keys of the timestamp arrays ordered temporally, use
    :attr:`timestamp_intervals_ordered_keys`.
    """

    timestamp_intervals_start: List[float] = []
    """List of :attr:`timestamps_arrays` start interval timestamps sorted by
    value.
    """

    timestamp_intervals_end: List[float] = []
    """List of :attr:`timestamps_arrays` end interval timestamps sorted by
    value.
    """

    timestamp_intervals_ordered_keys: List[int] = []
    """The keys of the timestamp arrays form :attr:`timestamps_arrays`
    sorted temporally such that the first timestamp in each array
    corresponding to the key is strictly increasing.
    """

    timestamp_data_map: Dict[float, Tuple[int, int]] = {}
    """Maps timestamps to their ``(key, index)`` in :attr:`timestamps_arrays`.

    For each known timestamp, it maps the timestamp to ``(key, index)``,
    where `key`` is the key in :attr:`timestamps_arrays` and ``index`` is the
    index in that array. Such that ``k, i = timestamp_data_map[t];
    timestamps_arrays[k][i] == t``.
    """

    event_channels: Dict[int, 'EventChannelData'] = {}
    """Map of all the :class:`EventChannelData` instances.

    Maps a globally unique ID, associated with the channel to the
    :class:`EventChannelData` instance.
    """

    pos_channels: Dict[int, 'PosChannelData'] = {}
    """Map of all the :class:`PosChannelData` instances.

    Maps a globally unique ID, associated with the channel to the
    :class:`PosChannelData` instance.
    """

    zone_channels: Dict[int, 'ZoneChannelData'] = {}
    """Map of all the :class:`ZoneChannelData` instances.

    Maps a globally unique ID, associated with the channel to the
    :class:`ZoneChannelData` instance.
    """

    saw_all_timestamps = False
    """Whether we have seen all the timestamps of the video.

    If we haven't, it's possible there are holes in the video and
    :attr:`timestamps_arrays` may have more than one array.
    """

    _saw_first_timestamp = False
    """If we have seen the first timestamp in the video (but it could be we
    skipped some timestamps in the middle).
    """

    _saw_last_timestamp = False
    """If we have seen the last timestamp in the video (but it could be we
    skipped some timestamps in the middle).
    """

    _last_timestamps_n: Optional[int] = None
    """The key in :attr:`timestamps_arrays` of the array containing the last
    added timestamp, if any.

    If we haven't seen a timestamp yet it's None.
    """

    _last_timestamps_ordered_index: Optional[int] = None
    """Similar to :attr:`_last_timestamps_n`, except it's the index in
    :attr:`timestamp_intervals_ordered_keys` of the last timestamp, if any.
    """

    glitter2_version: str = ''
    """The glitter version used to create the file originally. Read only.
    """

    ffpyplayer_version: str = ''
    """The ffpyplayer version used to create the file originally. Read only.
    """

    pixels_per_meter: float = 0.
    """The pixels per meter of the video, if known. Read only.
    """

    _channel_type_names: Dict[str, Type['ChannelType']] = {}
    """Map from channel type to channel class. Used by e.g.
    :meth:`create_channel`.
    """

    def __init__(self, nix_file: nix.File, unsaved_callback=_unsaved_callback):
        self.nix_file = nix_file
        self.unsaved_callback = unsaved_callback
        self.event_channels = {}
        self.pos_channels = {}
        self.zone_channels = {}
        self.timestamps_arrays = {}
        self.timestamp_data_map = {}
        self.timestamp_intervals_start = []
        self.timestamp_intervals_end = []
        self.timestamp_intervals_ordered_keys = []

        self._channel_type_names = {
            'event': EventChannelData,
            'pos': PosChannelData,
            'zone': ZoneChannelData,
        }

    def init_new_file(self):
        """Initializes a newly created empty NixIO file with all the required
        data structures.

        Typically it's used e.g.::

            nix_file = nixio.File.open(filename, nixio.FileMode.Overwrite)
            data_file = DataFile(nix_file=nix_file)
            data_file.init_new_file()

        .. note::

            This method automatically class :meth:`open_file`.
        """
        import glitter2
        import ffpyplayer
        f = self.nix_file

        self.unsaved_callback()

        f.create_section('app_config', 'configuration')

        sec = f.create_section('data_config', 'configuration')
        sec['channel_count'] = yaml_dumps(0)
        sec['glitter2_version'] = yaml_dumps(glitter2.__version__)
        sec['ffpyplayer_version'] = yaml_dumps(ffpyplayer.__version__)
        sec['pixels_per_meter'] = yaml_dumps(0.)

        sec['saw_all_timestamps'] = yaml_dumps(False)
        sec['saw_first_timestamp'] = yaml_dumps(False)
        sec['saw_last_timestamp'] = yaml_dumps(False)
        # we start at one because zero is the timestamps created below
        sec['timestamps_arrays_counter'] = yaml_dumps(1)

        sec.create_section('video_metadata', 'metadata')

        block = self.nix_file.create_block('timestamps', 'timestamps')
        timestamps = block.create_data_array(
            'timestamps', 'timestamps', dtype=np.float64, data=[])
        timestamps.metadata = self.nix_file.create_section(
            'timestamps_metadata', 'metadata')

        self.open_file()

    def open_file(self):
        """Loads the data from the file and initializes the instance. Can
        be called multiple times.

        Use after updating the file or opening an existing file. E.g.::

            nix_file = nixio.File.open(filename, nixio.FileMode.ReadWrite)
            data_file = DataFile(nix_file=nix_file)
            data_file.upgrade_file()
            data_file.open_file()
        """
        self.app_config_section = self.nix_file.sections['app_config']

        data_config = self.nix_file.sections['data_config']
        self.video_metadata_section = data_config.sections['video_metadata']

        self.saw_all_timestamps = yaml_loads(data_config['saw_all_timestamps'])
        self._saw_first_timestamp = yaml_loads(
            data_config['saw_first_timestamp'])
        self._saw_last_timestamp = yaml_loads(
            data_config['saw_last_timestamp'])
        self.glitter2_version = yaml_loads(data_config['glitter2_version'])
        self.ffpyplayer_version = yaml_loads(data_config['ffpyplayer_version'])
        self.pixels_per_meter = yaml_loads(data_config['pixels_per_meter'])

        self._read_timestamps_from_file()
        self._create_channels_from_file()

        self._last_timestamps_n = None
        self._last_timestamps_ordered_index = None

        self.unsaved_callback()

    def _read_timestamps_from_file(self):
        """Reads the timestamps arrays into the properties.
        """
        timestamps_block = self.nix_file.blocks['timestamps']
        timestamps = self.timestamps = timestamps_block.data_arrays[0]

        timestamps_arrays = self.timestamps_arrays = {}
        timestamps_arrays[0] = timestamps
        for i in range(1, len(timestamps_block.data_arrays)):
            data_array = timestamps_block.data_arrays[i]
            n = int(data_array.name.split('_')[-1])
            timestamps_arrays[n] = data_array

        data_map = self.timestamp_data_map = {}
        for i, timestamps in timestamps_arrays.items():
            for t_index, val in enumerate(timestamps):
                data_map[val] = i, t_index

        self._populate_timestamp_intervals()

    def _populate_timestamp_intervals(self):
        """Computes the timestamp interval start/end points and order.
        """
        timestamps = self.timestamps_arrays
        items = sorted(
            ((key, arr) for key, arr in timestamps.items()
             if len(arr)), key=lambda item: item[1][0]
        )
        keys = self.timestamp_intervals_ordered_keys = [
            key for key, arr in items]
        self.timestamp_intervals_start = [timestamps[i][0] for i in keys]
        self.timestamp_intervals_end = [timestamps[i][-1] for i in keys]

    def set_file_data(
            self, video_file_metadata: Dict, saw_all_timestamps: bool,
            timestamps: List[Union[np.ndarray, List[float]]],
            event_channels: List[Tuple[
                dict, List[Union[np.ndarray, List[bool]]]]],
            pos_channels: List[Tuple[
                dict, List[Union[np.ndarray, List[Tuple[float, float]]]]]],
            zone_channels: List[dict]):
        """Sets the data of the file at once.

        The video metadata and timestamps can be read most easily using
        :meth:`~glitter2.player.GlitterPlayer.get_file_data`.

        For the channels, the metadata dict should contain a ``name`` keyword
        whose value is a globally unique name for the channel, unique across
        all the channels.

        For zone_channels, the metadata should also contain a ``shape_config``
        keyword whose value is a dict with the shape metadata as given by
        :meth:`~kivy_garden.painter.PaintShape.get_state`. To create a shape,
        use :meth:`~kivy_garden.painter.PaintShape.create_shape`. E.g.::

            point = PaintCircle.create_shape([0, 0])
            circle = PaintCircle.create_shape([0, 0], 5)
            ellipse = PaintEllipse.create_shape([0, 0], 5, 10, 3.14)
            polygon = PaintPolygon.create_shape(
                [0, 0, 300, 0, 300, 800, 0, 800], [0, 0])
            polygon_metadata = polygon.get_state()

        E.g. to create a new NixIO file with the timestamps of a video file::

            # create file
            nix_file = nixio.File.open(filename, nixio.FileMode.ReadWrite)
            data_file = DataFile(nix_file=nix_file)
            data_file.init_new_file()
            # read timestamps
            timestamps, metadata = GlitterPlayer.get_file_data(video_file)
            # set just the timestamps
            data_file.set_file_data(
                video_file_metadata=metadata, saw_all_timestamps=True,
                timestamps=[timestamps], event_channels=[], pos_channels=[],
                zone_channels=[])
            # re-load data
            data_file.open_file()
        """
        self.video_metadata_dict = video_file_metadata
        if saw_all_timestamps:
            self._mark_saw_all_timestamps()

        timestamps_arrays = self.timestamps_arrays
        idx_map = {}
        for idx, array in enumerate(timestamps):
            array = np.asarray(array)
            if not idx:
                timestamps_arrays[0].append(array)
                idx_map[idx] = 0
            else:
                idx_map[idx] = i = self._create_timestamps_channels_array()
                timestamps_arrays[i].append(array)

        for event_type, channels in [
                ('event', event_channels), ('pos', pos_channels)]:
            for metadata, arrays in channels:
                channel = self.create_channel(event_type)
                channel.channel_config_dict = metadata
                for idx, array in enumerate(arrays):
                    nix_array = channel.data_arrays[idx_map[idx]]
                    nix_array[:] = np.asarray(array)

        for metadata in zone_channels:
            channel = self.create_channel('zone')
            channel.channel_config_dict = metadata

        self.unsaved_callback()

    def _create_channels_from_file(self):
        """Reads the channels from the nix file into the instance.
        """
        for block in self.nix_file.blocks:
            if block.name == 'timestamps':
                continue

            cls_type, channel_name, n = block.name.split('_')
            assert channel_name == 'channel'
            n = int(n)

            if cls_type == 'event':
                cls = EventChannelData
                items = self.event_channels
            elif cls_type == 'pos':
                cls = PosChannelData
                items = self.pos_channels
            elif cls_type == 'zone':
                cls = ZoneChannelData
                items = self.zone_channels
            else:
                raise ValueError(cls_type)

            channel = cls(name=block.name, num=n, block=block, data_file=self)
            channel.read_initial_data()
            items[n] = channel

    def upgrade_file(self):
        """Upgrades file to add any missing data structures that may have
        been added in newer versions of glitter, since the file was created.

        :meth:`open_file` should be called after this.
        """
        self.unsaved_callback()

        sec = self.nix_file.sections['data_config']
        if 'pixels_per_meter' not in sec:
            sec['pixels_per_meter'] = yaml_dumps(0.)

        if 'channel_count' not in sec:
            # it got moved from app_config to data_config
            count = yaml_loads(
                read_nix_prop(
                    self.nix_file.sections['app_config'].props['channel_count']
                )
            )
            sec['channel_count'] = yaml_dumps(count)

    @property
    def has_content(self):
        """Returns whether any video timestamps has yet been added to the file.
        """
        return bool(len(self.timestamps))

    @staticmethod
    def get_file_glitter2_version(filename) -> Optional[str]:
        """Gets the glitter version used to create the nixio file.

        If the file or data is invalid, returns None.
        """
        try:
            f = nix.File.open(filename, nix.FileMode.ReadOnly)

            # but always close file
            try:
                data_config = f.sections['data_config']
                return yaml_loads(data_config['glitter2_version'])
            finally:
                f.close()
        except (InvalidFile, OSError, KeyError):
            return None

    @staticmethod
    def get_file_video_metadata(filename) -> dict:
        """Returns the video metadata dictionary of the nixio file.
        """
        f = nix.File.open(filename, nix.FileMode.ReadOnly)

        try:
            config = f.sections['data_config'].sections['video_metadata']
            data = {}
            for prop in config.props:
                data[prop.name] = yaml_loads(read_nix_prop(prop))

            return data
        finally:
            f.close()

    @property
    def video_metadata_dict(self) -> dict:
        """Reads/writes the video metadata from the **current** NixIO file
        into/from a dict.

        This is the metadata from
        :meth:`~glitter2.player.GlitterPlayer.get_file_data`.

        .. warning::

            This property reads/writes to the file when accessed.
        """
        config = self.video_metadata_section
        data = {}
        for prop in config.props:
            data[prop.name] = yaml_loads(read_nix_prop(prop))

        return data

    @video_metadata_dict.setter
    def video_metadata_dict(self, metadata: dict):
        self.unsaved_callback()
        config = self.video_metadata_section
        for k, v in metadata.items():
            config[k] = yaml_dumps(v)

    def set_default_video_metadata(self, metadata: dict):
        """Sets the video file metadata, but only for the metadata that has
        not yet been set.
        """
        self.unsaved_callback()
        config = self.video_metadata_section
        for k, v in metadata.items():
            if k not in config:
                config[k] = yaml_dumps(v)

    def set_pixels_per_meter(self, value: float):
        """Sets the pixels per meter of the video file.
        """
        self.nix_file.sections['data_config']['pixels_per_meter'] = \
            yaml_dumps(value)
        self.pixels_per_meter = value
        self.unsaved_callback()

    @property
    def app_config_dict(self) -> dict:
        """Reads/writes the app config data into/from a dict.

        It does not include the channel config data, just the application
        config. The app config can be generated most simply from
        :meth:`~glitter2.main.Glitter2App.get_app_config_data`.

        .. warning::

            This property reads/writes to the file when accessed.
        """
        data = {}
        for prop in self.app_config_section.props:
            data[prop.name] = yaml_loads(read_nix_prop(prop))
        return data

    @app_config_dict.setter
    def app_config_dict(self, data: dict):
        """Writes the application configuration into the file.
        """
        self.unsaved_callback()
        config = self.app_config_section
        for k, v in data.items():
            config[k] = yaml_dumps(v)

    def write_channels_config(
            self, event_channels: Dict[int, dict] = None,
            pos_channels: Dict[int, dict] = None,
            zone_channels: Dict[int, dict] = None):
        """Updates the metadata to the provided values for each channel.

        ``xxx_channels`` is a dictionary whose keys are the channel's unique ID
        as e.g. in :attr:`event_channels` and whose values is a dict with
        the channel's new metadata.
        """
        self.unsaved_callback()
        if event_channels:
            event_channels_ = self.event_channels
            for i, data in event_channels.items():
                event_channels_[i].channel_config_dict = data

        if pos_channels:
            pos_channels_ = self.pos_channels
            for i, data in pos_channels.items():
                pos_channels_[i].channel_config_dict = data

        if zone_channels:
            zone_channels_ = self.zone_channels
            for i, data in zone_channels.items():
                zone_channels_[i].channel_config_dict = data

    def read_channels_config(
            self) -> Tuple[Dict[int, dict], Dict[int, dict], Dict[int, dict]]:
        """Returns a tuple of the event, pos, and zone channel metadata.

        Each item is a dictionary whose keys are the channel's unique ID
        as e.g. in :attr:`event_channels` and whose values is a dict with
        the channel's metadata.
        """
        event_channels = {
            i: chan.channel_config_dict
            for (i, chan) in self.event_channels.items()
        }
        pos_channels = {
            i: chan.channel_config_dict
            for (i, chan) in self.pos_channels.items()
        }
        zone_channels = {
            i: chan.channel_config_dict
            for (i, chan) in self.zone_channels.items()
        }
        return event_channels, pos_channels, zone_channels

    def _increment_channel_count(self) -> int:
        """Gets the channel ID for the next channel to be created and
        increments the internal channel counter

        :return: The channel ID number to use for the next channel to be
            created.
        """
        self.unsaved_callback()
        config = self.nix_file.sections['data_config']
        count = yaml_loads(read_nix_prop(config.props['channel_count']))
        config['channel_count'] = yaml_dumps(count + 1)
        return count

    def _increment_timestamps_arrays_counter(self) -> int:
        """Gets the number to associate with the next timestamps/data array to
        be created.
        """
        self.unsaved_callback()
        config = self.nix_file.sections['data_config']
        count = yaml_loads(config['timestamps_arrays_counter'])
        config['timestamps_arrays_counter'] = yaml_dumps(count + 1)
        return count

    def create_channel(self, channel_type: str) -> 'ChannelType':
        """Creates a channel of the given type.

        Can be one of ``'event'``, ``'pos'``, or ``'zone'``.
        """
        if channel_type not in self._channel_type_names:
            raise ValueError(
                'Did not understand channel type "{}"'.format(channel_type))

        cls = self._channel_type_names[channel_type]
        items = getattr(self, f'{channel_type}_channels')

        self.unsaved_callback()
        n = self._increment_channel_count()
        name = '{}_channel_{}'.format(channel_type, n)
        block = self.nix_file.create_block(name, 'channel')
        metadata = self.nix_file.create_section(name + '_metadata', 'metadata')
        block.metadata = metadata

        channel = cls(name=name, num=n, block=block, data_file=self)
        items[n] = channel
        channel.create_initial_data()
        return channel

    def duplicate_channel(self, channel: 'ChannelType') -> 'ChannelType':
        """Creates a new channel with the same type and with the same data and
        metadata as the given channel and returns the new channel.

        The ``name`` key's value in each channel's metadata should be unique
        across all channels, so the name value should be changed afterwards.
        E.g.::

            new_channel = data_file.duplicate_channel(channel)
            metadata = new_channel.channel_config_dict
            metadata['name'] = 'new name'
            new_channel.channel_config_dict = metadata
        """
        types = {cls: name for name, cls in self._channel_type_names.items()}
        cls = channel.__class__
        if cls not in types:
            raise ValueError(f'Unknown class {cls} for channel {channel}')

        new_channel = self.create_channel(types[cls])
        new_channel.channel_config_dict = channel.channel_config_dict
        channel.copy_data(new_channel)
        return new_channel

    def _mark_saw_all_timestamps(self):
        """Marks the file that we saw all the frames and timestamps of the
        video.
        """
        self.unsaved_callback()

        self.saw_all_timestamps = True
        self._saw_first_timestamp = True
        self._saw_last_timestamp = True

        self.nix_file.sections['data_config']['saw_all_timestamps'] = \
            yaml_dumps(True)
        self.nix_file.sections['data_config']['saw_first_timestamp'] = \
            yaml_dumps(True)
        self.nix_file.sections['data_config']['saw_last_timestamp'] = \
            yaml_dumps(True)

    def notify_interrupt_timestamps(self):
        """Must be called whenever the video is seeked and the next timestamp
        to :meth:`notify_add_timestamp` may not follow the last timestamp.
        """
        if self.saw_all_timestamps:
            return

        self.pad_all_channels_to_num_frames_interval()
        # indicate that we seeked
        self._last_timestamps_n = None
        self._last_timestamps_ordered_index = None

    def notify_saw_first_timestamp(self):
        """Must be called after we saw and added the timestamp of the first
        frame of the video file. By first we mean literally the first frame of
        the video file.
        """
        if self.saw_all_timestamps:
            return

        self._saw_first_timestamp = True
        self.unsaved_callback()
        self.nix_file.sections['data_config']['saw_first_timestamp'] = \
            yaml_dumps(True)

        if self._saw_last_timestamp and len(self.timestamps_arrays) == 1:
            self._mark_saw_all_timestamps()

    def notify_saw_last_timestamp(self):
        """Must be called after we saw and added the timestamp of the last
        frame of the video file.
        """
        if self.saw_all_timestamps:
            return

        self._saw_last_timestamp = True
        self.unsaved_callback()
        self.nix_file.sections['data_config']['saw_last_timestamp'] = \
            yaml_dumps(True)

        self.pad_all_channels_to_num_frames_interval()

        if self._saw_first_timestamp and len(self.timestamps_arrays) == 1:
            self._mark_saw_all_timestamps()

    def _merge_timestamp_channels_arrays(
            self, arr_num1: int, arr_num2: int) -> int:
        """Merges the timestamps arrays of the two time intervals, as well
        as the corresponding data arrays for all the channels.

        Returns the ID of the data array that contains the merged data.
        """
        timestamps_arrays = self.timestamps_arrays
        timestamp_data_map = self.timestamp_data_map
        arr1 = timestamps_arrays[arr_num1]
        arr2 = timestamps_arrays[arr_num2]

        if arr2.name == 'timestamps':
            # currently the first timestamps array must start at the first ts
            # so we cannot append that array to any other array
            raise NotImplementedError

        self.unsaved_callback()
        self.pad_all_channels_to_num_frames_interval(arr_num1)

        start_index = len(arr1)
        arr1.append(arr2)
        for i, t in enumerate(arr2, start_index):
            timestamp_data_map[t] = arr_num1, i
        del self.nix_file.blocks['timestamps'].data_arrays[arr2.name]
        del timestamps_arrays[arr_num2]

        for chan in self.event_channels.values():
            chan.merge_arrays(arr_num1, arr_num2)
        for chan in self.pos_channels.values():
            chan.merge_arrays(arr_num1, arr_num2)

        return arr_num1

    def _create_timestamps_channels_array(self) -> int:
        """Creates a new timestamp array for a new interval and creates the
        corresponding data arrays for all the channels.

        Returns the key of the newly created array in
        :attr:`timestamps_arrays`.
        """
        self.unsaved_callback()
        n = self._increment_timestamps_arrays_counter()

        block = self.nix_file.blocks['timestamps']
        self.timestamps_arrays[n] = block.create_data_array(
            'timestamps_{}'.format(n), 'timestamps', dtype=np.float64,
            data=[])

        for chan in self.event_channels.values():
            chan.create_data_array(n)
        for chan in self.pos_channels.values():
            chan.create_data_array(n)
        return n

    def pad_channel_to_num_frames_interval(
            self, channel: 'TemporalDataChannelBase'):
        """Pads the channel data arrays to the current number of timestamps.

        When adding timestamps, we don't increase all the channels data arrays
        with each new timestamp, but only do it when the channel data is
        updated or when the file is saved etc. This increases the data
        arrays size to the timestamps size.
        """
        array_num = self._last_timestamps_n
        if array_num is None:
            return

        size = len(self.timestamps_arrays[array_num])
        if not size:
            return

        channel.pad_channel_to_num_frames(array_num, size)

    def pad_all_channels_to_num_frames_interval(self, array_num=None):
        """Similar to :meth:`pad_channel_to_num_frames_interval`, but for all
        the channels.

        If ``array_num`` is specified, we pad that array, other wise we use
        :attr:`_last_timestamps_n` if it's not None.
        """
        if array_num is None:
            array_num = self._last_timestamps_n
            if array_num is None:
                return

        size = len(self.timestamps_arrays[array_num])
        if not size:
            return

        self.unsaved_callback()
        for chan in self.event_channels.values():
            chan.pad_channel_to_num_frames(array_num, size)
        for chan in self.pos_channels.values():
            chan.pad_channel_to_num_frames(array_num, size)

    def notify_add_timestamp(self, t: float) -> int:
        """Adds the next timestamp to the file.

        We assume that this is called frame by frame with no skipping unless
        :meth:`notify_interrupt_timestamps` was called.

        Also, the timestamps ``t`` must be either outside any existing
        timestamp interval, in which case the timestamp must have been unseen
        before. Or, if it is within an existing interval, the timestamps must
        have been seen before. In both cases, the timestamp must be larger or
        equal than the first timestamp.

        :param t: the next timestamp.
        :return: The key in :attr:`timestamps_arrays` containing the timestamp.
        """
        if self.saw_all_timestamps:
            return 0

        self.unsaved_callback()
        last_timestamps_n = self._last_timestamps_n
        timestamps_map = self.timestamp_data_map

        # we have seen this time stamp before
        if t in timestamps_map:
            n, index = timestamps_map[t]
            # if the last/current timestamps were in different arrays, merge
            if n != last_timestamps_n:
                # only merge if this is not the first timestamp and
                # we didn't jump by seeking to new timestamp
                if last_timestamps_n is not None:
                    n = self._merge_timestamp_channels_arrays(
                        last_timestamps_n, n)

                    # have we finally seen all timestamps?
                    if self._saw_last_timestamp and self._saw_first_timestamp \
                            and len(self.timestamps_arrays) == 1:
                        self._mark_saw_all_timestamps()

                    self._populate_timestamp_intervals()

                self._last_timestamps_ordered_index = \
                    self.timestamp_intervals_ordered_keys.index(n)
                self._last_timestamps_n = n
            return n

        # we have NOT seen this time stamp before. Do we have an array to add
        jumped_array = False
        if last_timestamps_n is None:
            jumped_array = True

            if not self.has_content:
                n = 0
            else:
                n = self._create_timestamps_channels_array()

            last_timestamps_n = self._last_timestamps_n = n

        data_array = self.timestamps_arrays[last_timestamps_n]
        timestamps_map[t] = last_timestamps_n, len(data_array)
        data_array.append(t)

        if jumped_array:
            # we added a new interval so recompute the intervals order
            self._populate_timestamp_intervals()
            self._last_timestamps_ordered_index = \
                self.timestamp_intervals_ordered_keys.index(last_timestamps_n)
        else:
            # update the current interval end point
            self.timestamp_intervals_end[
                self._last_timestamps_ordered_index] = t

        return last_timestamps_n

    def get_channel_from_id(self, i: int) -> 'DataChannelBase':
        """Given the unique channel ID as it's stored in
        :attr:`event_channels`, :attr:`pos_channels`, or :attr:`zone_channels`
        it returns the corresponding channel.

        The channel ID is stored in :attr:`DataChannelBase.num`.
        """
        if i in self.event_channels:
            return self.event_channels[i]
        elif i in self.pos_channels:
            return self.pos_channels[i]
        elif i in self.zone_channels:
            return self.zone_channels[i]
        else:
            raise ValueError(i)

    def delete_channel(self, i: int):
        """Deletes the channel corresponding to the ID as stored in
        :attr:`event_channels`, :attr:`pos_channels`, or :attr:`zone_channels`.

        The channel ID is stored in :attr:`DataChannelBase.num`.
        """
        if i in self.event_channels:
            channel = self.event_channels.pop(i)
        elif i in self.pos_channels:
            channel = self.pos_channels.pop(i)
        elif i in self.zone_channels:
            channel = self.zone_channels.pop(i)
        else:
            raise ValueError(i)

        self.unsaved_callback()
        del self.nix_file.blocks[channel.name]
        del self.nix_file.sections[channel.name + '_metadata']

    def is_end_timestamp(self, t: float) -> bool:
        """Returns whether the timestamp is the last timestamp of a interval.
        """
        n, i = self.timestamp_data_map[t]
        arr = self.timestamps_arrays[n]

        if i < len(arr) - 1:
            return False
        return True

    def condition_timestamp(self, t: float) -> Optional[float]:
        """If timestamp ``t`` is within a interval of seen timestamps in
        :attr:`timestamps_arrays`, it returns the closest seen timestamp to
        ``t``. Otherwise it returns None indicating the timestamp is outside
        of any timestamps interval.

        When reading timestamps from the video file, different systems may
        read slightly different timestamps. Conditioning the timestamp before
        use ensures identical behavior when re-opening files on different
        systems.
        """
        # we have seen this exact timestamp
        if t in self.timestamp_data_map:
            return t

        # new timestamp
        start = self.timestamp_intervals_start
        end = self.timestamp_intervals_end
        keys = self.timestamp_intervals_ordered_keys

        # if we have not seen any frames yet, this timestamp is always valid
        if not keys:
            return t

        i = bisect_left(end, t)

        if i == len(keys):
            # t is larger than the largest known timestamp
            if self._saw_last_timestamp:
                # if we already saw the end, it cannot be larger
                return float(end[-1])
            assert not self.saw_all_timestamps

            # t should increase the last interval
            return None

        # timestamp is less than or equal to time at endpoint of interval i
        if t < start[i]:
            # time is before the start of the ith interval. We know it's larger
            # than the end of previous interval if any
            if not i:
                # t is before the start of the video!?
                assert self._saw_first_timestamp
                return float(start[i])

            assert not self.saw_all_timestamps
            # t is between two intervals
            return None

        # t is in the ith interval, find the closest value
        timestamps = self.timestamps_arrays[keys[i]]
        k = bisect_left(timestamps, t)

        # it cannot be zero. It clearly cannot be less than timestamps[0] as
        # that would make it outside the interval. It cannot be exactly
        # timestamps[0] as we would have seen it already
        assert k

        if timestamps[k] - t <= t - timestamps[k - 1]:
            # it's closer to k
            return float(timestamps[k])
        return float(timestamps[k - 1])


class DataChannelBase(object):
    """Base class for data channels stored in a :class:`DataFile`.
    """

    data_file: DataFile = None
    """The :class:`DataFile` this channel belongs to.
    """

    metadata: nix.Section = None
    """The metadata section that stores the channel metadata.
    """

    name: str = ''
    """The name of the channel in the file. This is not the user facing name,
    but rather the internal NixIO name of the :attr:`block` containing the
    channel.
    """

    num: int = 0
    """The unique number used to identify the channel as stored in
    :attr:`DataFile.event_channels`, :attr:`DataFile.pos_channels`, or
    :attr:`DataFile.zone_channels`.
    """

    block: nix.Block = None
    """The block containing the channel data.
    """

    def __init__(
            self, name: str, num: int, block: nix.Block, data_file: DataFile,
            **kwargs):
        super(DataChannelBase, self).__init__(**kwargs)
        self.name = name
        self.num = num
        self.block = block
        self.metadata = block.metadata
        self.data_file = data_file

    def create_initial_data(self):
        """Creates whatever initial data structures are needed for storing the
        channel data.
        """
        raise NotImplementedError

    def read_initial_data(self):
        """Reads the channel data previously written to the file.
        """
        raise NotImplementedError

    @property
    def channel_config_dict(self) -> dict:
        """Reads/writes the channel metadata from the **current** NixIO file
        into/from a dict.

        .. warning::

            This property reads/writes to the file when accessed.

        See :meth:`DataFile.set_file_data` for the metadata requirements
        if setting manually outside the GUI.
        """
        config = self.metadata
        data = {}
        for prop in config.props:
            data[prop.name] = yaml_loads(read_nix_prop(prop))
        return data

    @channel_config_dict.setter
    def channel_config_dict(self, data: dict):
        self.data_file.unsaved_callback()
        config = self.metadata
        for k, v in data.items():
            config[k] = yaml_dumps(v)

    def copy_data(self, channel: 'ChannelType'):
        """Copies this channel's data, if any, into the given channel.
        """
        pass


class TemporalDataChannelBase(DataChannelBase):
    """Base class for data channels that have some kind of temporal dimension.
    """

    data_array: nix.DataArray = None
    """The data array storing the channel data, corresponding to
    :attr:`DataFile.timestamps`. If :attr:`data_arrays` has only one
    array, e.g. after seeing all frames, this is it.

    See :attr:`data_arrays`.
    """

    data_arrays: Dict[int, nix.DataArray] = {}
    """The channel data for the disjointed frame intervals.

    This corresponds exactly to :attr:`DatFile.timestamps_arrays` with the
    arrays of the same keys containing the data for the corresponding
    intervals.
    """

    default_data_value = None
    """The per-channel type default data used before the user modifies
    the data. E.g. for an event channel it may default to False.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.data_arrays = {}

    def create_initial_data(self):
        self.data_file.unsaved_callback()

        timestamps = self.data_file.timestamps_arrays
        for i, timestamps_arr in timestamps.items():
            self.create_data_array(i, count=len(timestamps_arr))

        self.data_array = data_array = self.data_arrays[0]
        data_array.metadata = self.metadata

    def create_data_array(self, n: int = 0, count: Optional[int] = None):
        """Creates a data array when a new timestamps interval is created.

        :param n: The :attr:`data_arrays` key to use for the array. This
            corresponds to the interval's :attr:`DatFile.timestamps_arrays`
            key.
        :param count: The size of the array to create, or empty if it's None.
        """
        raise NotImplementedError

    def read_initial_data(self):
        block = self.block
        data_arrays = self.data_arrays

        data_array = self.data_array = block.data_arrays[0]
        data_arrays[0] = data_array

        for i in range(1, len(block.data_arrays)):
            item = block.data_arrays[i]
            n = int(item.name.split('_')[-1])
            data_arrays[n] = item

    def merge_arrays(self, arr_num1: int, arr_num2: int):
        """Merges the data arrays into a single array.

        The same as :attr:`DatFile._merge_timestamp_channels_arrays`, but for
        data arrays.
        """
        data_arrays = self.data_arrays
        arr1 = data_arrays[arr_num1]
        arr2 = data_arrays[arr_num2]
        assert arr2 is not self.data_array

        self.data_file.unsaved_callback()
        arr1.append(arr2)
        del self.block.data_arrays[arr2.name]
        del data_arrays[arr_num2]

    def pad_channel_to_num_frames(self, array_num: int, size: int):
        """Pads the channel data arrays to the given size, if it's smaller.

        See :attr:`DataFile.pad_channel_to_num_frames_interval`.
        """
        arr = self.data_arrays[array_num]
        n = len(arr)
        diff = size - n
        assert diff >= 0

        if not diff:
            return

        self.data_file.unsaved_callback()
        arr.append(self.default_data_value.repeat(diff, axis=0))

    def get_timestamps_modified_state(self) -> Dict[float, bool]:
        """Returns a dict whose keys are timestamps and values indicate whether
        the data for the timestamp has been changed from the
        :attr:`default_data_value` (True means it's not the default).
        """
        raise NotImplementedError

    def set_timestamp_value(self, t: float, value: Any):
        """Changes the value of the data array for the given timestamp ``t``
        to ``value``.
        """
        raise NotImplementedError

    def set_channel_data(
            self, data: Union[list, np.ndarray],
            mask: Optional[np.ndarray] = None):
        """Changes the values of the data array (optionally masked).

        Must have :attr:`saw_all_timestamps` before this can be used.

        Number of items in data must be the same as the number of true
        elements in mask, if provided.
        """
        self.data_file.pad_channel_to_num_frames_interval(self)
        if not self.data_file.saw_all_timestamps:
            raise TypeError(
                'Cannot set the data at once when missing timestamps')

        self.data_file.unsaved_callback()
        if mask is None:
            self.data_array[:] = data
        else:
            # workaround for https://github.com/h5py/h5py/issues/1750
            self.data_array[mask.nonzero()[0]] = data

    def get_timestamp_value(self, t: float) -> Any:
        """Returns the value of the data array for the given timestamp ``t``.
        """
        raise NotImplementedError

    def reset_data_to_default(self):
        """Resets all the data array values to the :attr:`default_data_value`.
        """
        for arr in self.data_arrays.values():
            arr[:] = self.default_data_value

    def copy_data(self, channel: 'ChannelType'):
        src_data_arrays = self.data_arrays
        for key, target_arr in channel.data_arrays.items():
            target_arr[:] = src_data_arrays[key]


class EventChannelData(TemporalDataChannelBase):
    """Channel that stores event data.

    For each timestamp we store a bool representing whether the event occurred
    at this timestamp.

    Metadata: The only required metadata is the name key (unique across all
    channels).
    """

    default_data_value = np.array([0], dtype=np.uint8)
    """The default value used before the user modifies the data.

    It is False (0) for the event channel.
    """

    def create_data_array(self, n: int = 0, count: Optional[int] = None):
        self.data_file.unsaved_callback()
        name = self.name if not n else '{}_group_{}'.format(self.name, n)

        if not count:
            self.data_arrays[n] = self.block.create_data_array(
                name, 'event', dtype=np.uint8, data=[])
        else:
            self.data_arrays[n] = self.block.create_data_array(
                name, 'event', dtype=np.uint8,
                data=self.default_data_value.repeat(count, axis=0))

    def get_timestamps_modified_state(self) -> Dict[float, bool]:
        self.data_file.pad_channel_to_num_frames_interval(self)
        data_arrays = self.data_arrays
        timestamp_arrays = self.data_file.timestamps_arrays

        results = {}
        for i in data_arrays:
            data_array = np.array(data_arrays[i]) != 0
            timestamp_array = np.array(timestamp_arrays[i])
            for j in range(len(timestamp_array)):
                results[timestamp_array[j]] = data_array[j]

        return results

    def set_timestamp_value(self, t: float, value: bool):
        """Changes the value of the data array for the given timestamp ``t``
        to ``value``.
        """
        self.data_file.pad_channel_to_num_frames_interval(self)
        data_file = self.data_file
        data_file.unsaved_callback()
        n, i = data_file.timestamp_data_map[t]
        self.data_arrays[n][i] = value

    def get_timestamp_value(self, t: float) -> bool:
        """Returns the value of the data array for the given timestamp ``t``.
        """
        n, i = self.data_file.timestamp_data_map[t]
        if len(self.data_arrays[n]) <= i:
            return False
        return bool(self.data_arrays[n][i])


class PosChannelData(TemporalDataChannelBase):
    """Channel that stores position data.

    For each timestamp we store a tuple of the ``(x, y)`` position at this
    timestamp.

    Metadata: The only required metadata is the name key (unique across all
    channels).
    """

    default_data_value = np.array([[-1, -1]], dtype=np.float64)
    """The default value used before the user modifies the data.

    It is a tuple of ``(-1, -1)`` corresponding to x and y for the position
    channel.
    """

    def create_data_array(self, n: int = 0, count: Optional[int] = None):
        self.data_file.unsaved_callback()
        name = self.name if not n else '{}_group_{}'.format(self.name, n)

        if not count:
            self.data_arrays[n] = self.block.create_data_array(
                name, 'pos', dtype=np.float64, data=np.empty((0, 2)))
        else:
            self.data_arrays[n] = self.block.create_data_array(
                name, 'pos', dtype=np.float64,
                data=self.default_data_value.repeat(count, axis=0))

    def get_timestamps_modified_state(self) -> Dict[float, bool]:
        self.data_file.pad_channel_to_num_frames_interval(self)
        data_arrays = self.data_arrays
        timestamp_arrays = self.data_file.timestamps_arrays

        results = {}
        for i in data_arrays:
            data_array = np.array(data_arrays[i])[:, 0] != -1
            timestamp_array = np.array(timestamp_arrays[i])
            for j in range(len(timestamp_array)):
                results[timestamp_array[j]] = data_array[j]

        return results

    def set_timestamp_value(
            self, t: float, value: Union[Tuple[float, float], np.ndarray]):
        """Changes the value of the data array for the given timestamp ``t``
        to ``value``.
        """
        self.data_file.pad_channel_to_num_frames_interval(self)
        data_file = self.data_file
        data_file.unsaved_callback()
        n, i = data_file.timestamp_data_map[t]
        self.data_arrays[n][i, :] = value

    def get_timestamp_value(self, t: float) -> Tuple[float, float]:
        """Returns the value of the data array for the given timestamp ``t``.
        """
        n, i = self.data_file.timestamp_data_map[t]
        if len(self.data_arrays[n]) <= i:
            return -1, -1
        x, y = self.data_arrays[n][i, :]
        return float(x), float(y)

    def get_previous_timestamp_data(self, t):
        n, i = self.data_file.timestamp_data_map[t]
        if len(self.data_arrays[n]) < i:
            return None, None, None

        return self.data_file.timestamps_arrays[n], self.data_arrays[n], i - 1


class ZoneChannelData(DataChannelBase):
    """Channel that stores a static zone.

    Unlike the event and position channels, this contains no data and only
    metadata. The metadata stores the shape of the drawn zone as e.g.
    a circle, a polygon, an ellipse, etc.

    Metadata: The required metadata is the name key (unique across all
    channels) and the shape_config key data. The shape data is the state of a
    :class:`~kivy_garden.painter.PaintShape` using
    :meth:`~kivy_garden.painter.PaintShape.get_state`.
    """

    def create_initial_data(self):
        pass

    def read_initial_data(self):
        pass


ChannelType = Union[
    DataChannelBase, TemporalDataChannelBase, EventChannelData, PosChannelData,
    ZoneChannelData]
