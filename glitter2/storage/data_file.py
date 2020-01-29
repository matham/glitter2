import numpy as np
from typing import List, Dict, Optional
import nixio as nix

from base_kivy_app.utils import yaml_dumps, yaml_loads

__all__ = ('DataFile', 'read_nix_prop')


def read_nix_prop(prop):
    try:
        return prop.values[0].value
    except AttributeError:
        return prop.values[0]


def _unsaved_callback():
    pass


class DataFile(object):

    unsaved_callback = None

    nix_file: nix.File = None

    global_config: nix.Section = None

    timestamps: nix.DataArray = None
    """The first timestamps data array. If there's only one, this is used.
    """

    timestamps_arrays: Dict[int, nix.DataArray] = {}
    """Any additional data arrays created for the timestamps when seeking is
    stored here. The key is the data array number (0 is for
    :attr:`timestamps`) and the value is the data array.
    """

    timestamp_data_map: Dict[float, int] = {}
    """For each timestamps in the video, it maps to the key in
    :attr:`timestamps_arrays` whose value is the data array storing this
    timestamp.
    """

    event_channels: List['EventChannelData'] = []

    pos_channels: List['PosChannelData'] = []

    zone_channels: List['ZoneChannelData'] = []

    saw_all_timestamps = False

    _saw_first_timestamp = False

    _saw_last_timestamp = False

    _last_timestamps_n: Optional[int] = None
    """When it's none it means there's nothing to pad in channels.
    """

    def __init__(self, nix_file, unsaved_callback=_unsaved_callback):
        self.nix_file = nix_file
        self.unsaved_callback = unsaved_callback
        self.event_channels = []
        self.pos_channels = []
        self.zone_channels = []
        self.timestamps_arrays = {}
        self.timestamp_data_map = {}

    def init_new_file(self):
        f = self.nix_file

        sec = f.create_section('app_config', 'configuration')
        sec['channel_count'] = yaml_dumps(0)

        sec = f.create_section('data_config', 'configuration')
        sec['saw_all_timestamps'] = yaml_dumps(False)
        sec['saw_first_timestamp'] = yaml_dumps(False)
        sec['saw_last_timestamp'] = yaml_dumps(False)
        sec['timestamps_arrays_counter'] = yaml_dumps(1)
        sec.create_section('video_metadata', 'metadata')

        block = self.nix_file.create_block('timestamps', 'timestamps')
        timestamps = block.create_data_array(
            'timestamps', 'timestamps', dtype=np.float64, data=[])
        timestamps.metadata = self.nix_file.create_section(
            'timestamps_metadata', 'metadata')

        self.open_file()

    def open_file(self):
        self.global_config = self.nix_file.sections['app_config']
        self.saw_all_timestamps = yaml_loads(
            self.nix_file.sections['data_config']['saw_all_timestamps'])
        self._saw_first_timestamp = yaml_loads(
            self.nix_file.sections['data_config']['saw_first_timestamp'])
        self._saw_last_timestamp = yaml_loads(
            self.nix_file.sections['data_config']['saw_last_timestamp'])

        timestamps_block = self.nix_file.blocks['timestamps']
        timestamps = self.timestamps = timestamps_block.data_arrays[0]

        timestamps_arrays = self.timestamps_arrays
        timestamps_arrays[0] = timestamps
        for i in range(1, len(timestamps_block.data_arrays)):
            data_array = timestamps_block.data_arrays[i]
            n = int(data_array.name.split('_')[-1])
            timestamps_arrays[n] = data_array

        data_map = self.timestamp_data_map
        for i, timestamps in timestamps_arrays.items():
            for val in timestamps:
                data_map[val] = i

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

            channel = cls(name=block.name, num=n, block=block)
            channel.read_data_arrays()
            items.append(channel)

    def upgrade_file(self):
        pass

    @property
    def has_content(self):
        return bool(len(self.timestamps))

    @staticmethod
    def get_video_metadata(filename):
        f = nix.File.open(filename, nix.FileMode.ReadOnly)

        try:
            config = f.sections['data_config'].sections['video_metadata']
            data = {}
            for prop in config.props:
                data[prop.name] = yaml_loads(read_nix_prop(prop))

            return data
        finally:
            f.close()

    def write_config(self, data):
        self.unsaved_callback()
        config = self.global_config
        for k, v in data.items():
            config[k] = yaml_dumps(v)

        import glitter2
        import ffpyplayer
        config['ceed_version'] = yaml_dumps(glitter2.__version__)
        config['ffpyplayer_version'] = yaml_dumps(ffpyplayer.__version__)

    def read_config(self):
        """Reads all the config data, including the channel config
        and returns it as a dict.
        """
        config = self.nix_file.sections['app_config']
        data = {}
        for prop in config.props:
            data[prop.name] = yaml_loads(read_nix_prop(prop))

        return data

    def increment_channel_count(self):
        """Gets the channel ID for the next channel to be created and
        increments the internal channel counter

        :return: The channel ID number to use for the next channel to be
            created.
        """
        config = self.global_config
        count = yaml_loads(read_nix_prop(config.props['channel_count']))
        config['channel_count'] = yaml_dumps(count + 1)
        return count

    def increment_timestamps_arrays_counter(self):
        config = self.nix_file.sections['data_config']
        count = yaml_loads(config['timestamps_arrays_counter'])
        config['timestamps_arrays_counter'] = yaml_dumps(count + 1)
        return count

    def create_channel(self, channel_type):
        if channel_type == 'event':
            cls = EventChannelData
        elif channel_type == 'pos':
            cls = PosChannelData
        elif channel_type == 'zone':
            cls = ZoneChannelData
        else:
            raise ValueError(
                'Did not understand channel type "{}"'.format(channel_type))

        n = self.increment_channel_count()
        name = '{}_channel_{}'.format(channel_type, n)
        block = self.nix_file.create_block(name, 'channel')
        metadata = self.nix_file.create_section(name + '_metadata', 'metadata')
        block.metadata = metadata

        channel = cls(name=name, num=n, block=block)
        channel.create_default_array()
        return channel

    def notify_interrupt_timestamps(self):
        if self.saw_all_timestamps:
            return

        if self._last_timestamps_n is None:
            return
        self.pad_all_channels_to_num_frames(self._last_timestamps_n)
        self._last_timestamps_n = None

    def notify_saw_first_timestamp(self):
        if self.saw_all_timestamps:
            return

        self._saw_first_timestamp = True
        self.nix_file.sections['data_config']['saw_first_timestamp'] = \
            yaml_dumps(True)

        if self._saw_last_timestamp and len(self.timestamps_arrays) == 1:
            self.saw_all_timestamps = True
            self.nix_file.sections['data_config']['saw_all_timestamps'] = \
                yaml_dumps(True)

    def notify_saw_last_timestamp(self):
        if self.saw_all_timestamps:
            return

        self._saw_last_timestamp = True
        self.nix_file.sections['data_config']['saw_last_timestamp'] = \
            yaml_dumps(True)

        if self._last_timestamps_n is not None:
            self.pad_all_channels_to_num_frames(self._last_timestamps_n)
            self._last_timestamps_n = None

        if self._saw_first_timestamp and len(self.timestamps_arrays) == 1:
            self.saw_all_timestamps = True
            self.nix_file.sections['data_config']['saw_all_timestamps'] = \
                yaml_dumps(True)

    def add_timestamp(self, t: float) -> int:
        """We assume that this is called frame by frame with no skipping unless
        :meth:`notify_interrupt_timestamps` was called.

        :param t:
        :return:
        """
        if self.saw_all_timestamps:
            return 0

        last_timestamps_n = self._last_timestamps_n
        timestamps_map = self.timestamp_data_map

        # we have seen this time stamp before
        if t in timestamps_map:
            n = timestamps_map[t]
            # if the last/current timestamps were in different arrays, merge
            if n != last_timestamps_n and last_timestamps_n is not None:
                self.pad_all_channels_to_num_frames(last_timestamps_n)

                arr_num1, arr_num2 = self.merge_timestamp_arrays(
                    last_timestamps_n, n)
                self.merge_arrays_for_all_channels(arr_num1, arr_num2)

                self._last_timestamps_n = arr_num1
            else:
                self._last_timestamps_n = n
            return n

        # we have NOT seen this time stamp before. Do we have an array to add
        if last_timestamps_n is None:
            if not self.has_content:
                last_timestamps_n = self._last_timestamps_n = 0
            else:
                n = self.increment_timestamps_arrays_counter()
                last_timestamps_n = self._last_timestamps_n = n

                block = self.nix_file.blocks['timestamps']
                self.timestamps_arrays[n] = block.create_data_array(
                    'timestamps_{}'.format(n), 'timestamps', dtype=np.float64,
                    data=[])
                self.create_data_array_for_all_channels(n)

        timestamps_map[t] = last_timestamps_n
        data_array = self.timestamps_arrays[last_timestamps_n]
        data_array.append(t)
        return last_timestamps_n

    def merge_timestamp_arrays(self, arr_num1: int, arr_num2: int):
        timestamps_arrays = self.timestamps_arrays
        timestamp_data_map = self.timestamp_data_map
        arr1 = timestamps_arrays[arr_num1]
        arr2 = timestamps_arrays[arr_num2]

        if arr2.name == 'timestamps':
            # currently the first timestamps array must start at the first ts
            raise NotImplementedError

        arr1.append(arr2)
        for t in arr2:
            timestamp_data_map[t] = arr_num1
        del arr2[:]
        del timestamps_arrays[arr_num2]

        return arr_num1, arr_num2

    def pad_all_channels_to_num_frames(self, array_num):
        size = len(self.timestamps_arrays[array_num])
        if not size:
            return

        for chan in self.event_channels:
            chan.pad_channel_to_num_frames(array_num, size)
        for chan in self.pos_channels:
            chan.pad_channel_to_num_frames(array_num, size)

    def merge_arrays_for_all_channels(self, arr_num1: int, arr_num2: int):
        for chan in self.event_channels:
            chan.merge_arrays(arr_num1, arr_num2)
        for chan in self.pos_channels:
            chan.merge_arrays(arr_num1, arr_num2)

    def create_data_array_for_all_channels(self, arr_num: int):
        for chan in self.event_channels:
            chan.create_data_array(arr_num)
        for chan in self.pos_channels:
            chan.create_data_array(arr_num)


class DataChannelBase(object):

    metadata: nix.Section = None

    name: str = ''

    num: int = 0

    block: nix.Block = None

    data_array: nix.DataArray = None

    data_arrays: Dict[int, nix.DataArray] = {}

    default_data_value = None

    def __init__(self, name, num, block, **kwargs):
        super(DataChannelBase, self).__init__(**kwargs)
        self.name = name
        self.num = num
        self.block = block
        self.data_arrays = {}
        self.metadata = block.metadata

    def create_default_array(self, n=0):
        self.data_array = data_array = self.create_data_array()
        data_array.metadata = self.metadata
        self.data_arrays[n] = data_array
        return data_array

    def create_data_array(self, n=None):
        raise NotImplementedError

    def read_data_arrays(self):
        block = self.block
        data_arrays = self.data_arrays

        data_array = self.data_array = block.data_arrays[0]
        data_arrays[0] = data_array

        for i in range(1, len(block.data_arrays)):
            item = block.data_arrays[i]
            n = int(item.name.split('_')[-1])
            data_arrays[n] = item

    def merge_arrays(self, arr_num1: int, arr_num2: int):
        data_arrays = self.data_arrays
        arr1 = data_arrays[arr_num1]
        arr2 = data_arrays[arr_num2]
        assert arr2 is not self.data_array

        arr1.append(arr2)
        del arr2[:]
        del data_arrays[arr_num2]

    def pad_channel_to_num_frames(self, array_num, size):
        arr = self.data_arrays[array_num]
        n = len(arr)
        diff = size - n
        assert diff >= 0

        if not diff:
            return

        arr.append(self.default_data_value.repeat(diff, axis=0))


class EventChannelData(DataChannelBase):

    default_data_value = np.array([-1], dtype=np.int8)

    def create_data_array(self, n=None):
        name = self.name if n is None else '{}_group_{}'.format(self.name, n)
        return self.block.create_data_array(
            name, 'event', dtype=np.int8, data=[])


class PosChannelData(DataChannelBase):

    default_data_value = np.array([[-1, -1]], dtype=np.float64)

    def create_data_array(self, n=None):
        name = self.name if n is None else '{}_group_{}'.format(self.name, n)
        return self.block.create_data_array(
            name, 'pos', dtype=np.float64, data=np.empty((0, 2)))


class ZoneChannelData(DataChannelBase):

    default_data_value = np.array([[-1, -1]], dtype=np.float64)

    def create_data_array(self, n=None):
        name = self.name if n is None else '{}_group_{}'.format(self.name, n)
        return self.block.create_data_array(
            name, 'pos', dtype=np.float64, data=np.empty((0, 2)))
