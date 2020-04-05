"""Data file
============

Data channel methods, unless specified should not be called directly.
"""

import numpy as np
from typing import List, Dict, Optional, Tuple, Callable
import nixio as nix
from nixio.exceptions.exceptions import InvalidFile

from base_kivy_app.utils import yaml_dumps, yaml_loads

__all__ = (
    'DataFile', 'DataChannelBase', 'TemporalDataChannelBase',
    'EventChannelData', 'PosChannelData', 'ZoneChannelData', 'read_nix_prop')


def read_nix_prop(prop):
    try:
        return prop.values[0].value
    except AttributeError:
        return prop.values[0]


def _unsaved_callback():
    pass


class DataFile(object):

    unsaved_callback: Callable = None

    nix_file: nix.File = None

    global_config: nix.Section = None

    video_metadata_config: nix.Section = None

    timestamps: nix.DataArray = None
    """The first timestamps data array. If there's only one, this is used.
    It's created when :meth:`init_new_file` is called.
    """

    timestamps_arrays: Dict[int, nix.DataArray] = {}
    """Any additional data arrays created for the timestamps when seeking is
    stored here. The key is the data array number (0 is for
    :attr:`timestamps`) and the value is the data array.
    """

    timestamp_data_map: Dict[float, Tuple[int, int]] = {}
    """For each timestamps in the video, it maps to the key in
    :attr:`timestamps_arrays` whose value is the data array storing this
    timestamp.
    """

    event_channels: Dict[int, 'EventChannelData'] = {}

    pos_channels: Dict[int, 'PosChannelData'] = {}

    zone_channels: Dict[int, 'ZoneChannelData'] = {}

    saw_all_timestamps = False

    _saw_first_timestamp = False

    _saw_last_timestamp = False

    _last_timestamps_n: Optional[int] = None
    """When it's none it means there's nothing to pad in channels.
    """

    glitter2_version: str = ''

    ffpyplayer_version: str = ''

    pixels_per_meter: float = 0.

    def __init__(self, nix_file: nix.File, unsaved_callback=_unsaved_callback):
        self.nix_file = nix_file
        self.unsaved_callback = unsaved_callback
        self.event_channels = {}
        self.pos_channels = {}
        self.zone_channels = {}
        self.timestamps_arrays = {}
        self.timestamp_data_map = {}

    def init_new_file(self):
        import glitter2
        import ffpyplayer
        f = self.nix_file

        self.unsaved_callback()

        sec = f.create_section('app_config', 'configuration')
        sec['channel_count'] = yaml_dumps(0)

        sec = f.create_section('data_config', 'configuration')
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
        self.global_config = self.nix_file.sections['app_config']

        data_config = self.nix_file.sections['data_config']
        self.video_metadata_config = data_config.sections['video_metadata']

        self.saw_all_timestamps = yaml_loads(data_config['saw_all_timestamps'])
        self._saw_first_timestamp = yaml_loads(
            data_config['saw_first_timestamp'])
        self._saw_last_timestamp = yaml_loads(
            data_config['saw_last_timestamp'])
        self.glitter2_version = yaml_loads(data_config['glitter2_version'])
        self.ffpyplayer_version = yaml_loads(data_config['ffpyplayer_version'])
        self.pixels_per_meter = yaml_loads(data_config['pixels_per_meter'])

        self.read_timestamps_from_file()
        self.create_channels_from_file()

    def read_timestamps_from_file(self):
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
            for t_index, val in enumerate(timestamps):
                data_map[val] = i, t_index

    def set_file_data(
            self, file_metadata: Dict, saw_all_timestamps: bool,
            timestamps: List[np.ndarray],
            event_channels: List[Tuple[dict, List[np.ndarray]]],
            pos_channels: List[Tuple[dict, List[np.ndarray]]],
            zone_channels: List[dict]):
        self.set_video_metadata(file_metadata)
        if saw_all_timestamps:
            self.mark_saw_all_timestamps()

        timestamps_arrays = self.timestamps_arrays
        idx_map = {}
        for idx, array in enumerate(timestamps):
            if not idx:
                timestamps_arrays[0].append(array)
                idx_map[idx] = 0
            else:
                idx_map[idx] = i = self.create_timestamps_channels_array()
                timestamps_arrays[i].append(array)

        for event_type, channels in [
                ('event', event_channels), ('pos', pos_channels)]:
            for metadata, arrays in channels:
                channel = self.create_channel(event_type)
                channel.write_channel_config(metadata)
                for idx, array in enumerate(arrays):
                    nix_array = channel.data_arrays[idx_map[idx]]
                    nix_array[:] = array

        for metadata in zone_channels:
            channel = self.create_channel('zone')
            channel.write_channel_config(metadata)

    def create_channels_from_file(self):
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
        """Called before :meth:`open_file`.
        """
        self.unsaved_callback()

        sec = self.nix_file.sections['data_config']
        if 'pixels_per_meter' not in sec:
            sec['pixels_per_meter'] = yaml_dumps(0.)

    @property
    def has_content(self):
        return bool(len(self.timestamps))

    @property
    def ordered_timestamps_indices(self):
        arrays = self.timestamps_arrays
        return list(sorted(arrays, key=lambda i: arrays[i][0]))

    @staticmethod
    def get_file_glitter2_version(filename):
        # if the file or data is invalid, return None
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
    def get_file_video_metadata(filename):
        f = nix.File.open(filename, nix.FileMode.ReadOnly)

        try:
            config = f.sections['data_config'].sections['video_metadata']
            data = {}
            for prop in config.props:
                data[prop.name] = yaml_loads(read_nix_prop(prop))

            return data
        finally:
            f.close()

    def get_video_metadata(self) -> dict:
        config = self.video_metadata_config
        data = {}
        for prop in config.props:
            data[prop.name] = yaml_loads(read_nix_prop(prop))

        return data

    def set_default_video_metadata(self, metadata: dict):
        self.unsaved_callback()
        config = self.video_metadata_config
        for k, v in metadata.items():
            if k not in config:
                config[k] = yaml_dumps(v)

    def set_video_metadata(self, metadata: dict):
        self.unsaved_callback()
        config = self.video_metadata_config
        for k, v in metadata.items():
            config[k] = yaml_dumps(v)

    def set_pixels_per_meter(self, value):
        self.nix_file.sections['data_config']['pixels_per_meter'] = \
            yaml_dumps(value)
        self.pixels_per_meter = value

    def write_app_config(self, data):
        self.unsaved_callback()
        config = self.global_config
        for k, v in data.items():
            config[k] = yaml_dumps(v)

    def read_app_config(self):
        """Reads the app config data and returns it as a dict. It does not
        include the channel config data.
        """
        config = self.nix_file.sections['app_config']
        data = {}
        for prop in config.props:
            data[prop.name] = yaml_loads(read_nix_prop(prop))
        return data

    def write_channels_config(
            self, event_channels: Dict[int, dict] = None,
            pos_channels: Dict[int, dict] = None,
            zone_channels: Dict[int, dict] = None):
        self.unsaved_callback()
        if event_channels:
            event_channels_ = self.event_channels
            for i, data in event_channels.items():
                event_channels_[i].write_channel_config(data)

        if pos_channels:
            pos_channels_ = self.pos_channels
            for i, data in pos_channels.items():
                pos_channels_[i].write_channel_config(data)

        if zone_channels:
            zone_channels_ = self.zone_channels
            for i, data in zone_channels.items():
                zone_channels_[i].write_channel_config(data)

    def read_channels_config(self):
        event_channels = {
            i: chan.read_channel_config()
            for (i, chan) in self.event_channels.items()
        }
        pos_channels = {
            i: chan.read_channel_config()
            for (i, chan) in self.pos_channels.items()
        }
        zone_channels = {
            i: chan.read_channel_config()
            for (i, chan) in self.zone_channels.items()
        }
        return event_channels, pos_channels, zone_channels

    def increment_channel_count(self):
        """Gets the channel ID for the next channel to be created and
        increments the internal channel counter

        :return: The channel ID number to use for the next channel to be
            created.
        """
        self.unsaved_callback()
        config = self.global_config
        count = yaml_loads(read_nix_prop(config.props['channel_count']))
        config['channel_count'] = yaml_dumps(count + 1)
        return count

    def increment_timestamps_arrays_counter(self):
        self.unsaved_callback()
        config = self.nix_file.sections['data_config']
        count = yaml_loads(config['timestamps_arrays_counter'])
        config['timestamps_arrays_counter'] = yaml_dumps(count + 1)
        return count

    def create_channel(self, channel_type):
        if channel_type == 'event':
            cls = EventChannelData
            items = self.event_channels
        elif channel_type == 'pos':
            cls = PosChannelData
            items = self.pos_channels
        elif channel_type == 'zone':
            cls = ZoneChannelData
            items = self.zone_channels
        else:
            raise ValueError(
                'Did not understand channel type "{}"'.format(channel_type))

        self.unsaved_callback()
        n = self.increment_channel_count()
        name = '{}_channel_{}'.format(channel_type, n)
        block = self.nix_file.create_block(name, 'channel')
        metadata = self.nix_file.create_section(name + '_metadata', 'metadata')
        block.metadata = metadata

        channel = cls(name=name, num=n, block=block, data_file=self)
        items[n] = channel
        channel.create_initial_data()
        return channel

    def mark_saw_all_timestamps(self):
        self.saw_all_timestamps = True
        self.nix_file.sections['data_config']['saw_all_timestamps'] = \
            yaml_dumps(True)

    def notify_interrupt_timestamps(self):
        if self.saw_all_timestamps:
            return

        self.pad_all_channels_to_num_frames()

    def notify_saw_first_timestamp(self):
        if self.saw_all_timestamps:
            return

        self._saw_first_timestamp = True
        self.unsaved_callback()
        self.nix_file.sections['data_config']['saw_first_timestamp'] = \
            yaml_dumps(True)

        if self._saw_last_timestamp and len(self.timestamps_arrays) == 1:
            self.mark_saw_all_timestamps()

    def notify_saw_last_timestamp(self):
        if self.saw_all_timestamps:
            return

        self._saw_last_timestamp = True
        self.unsaved_callback()
        self.nix_file.sections['data_config']['saw_last_timestamp'] = \
            yaml_dumps(True)

        self.pad_all_channels_to_num_frames()

        if self._saw_first_timestamp and len(self.timestamps_arrays) == 1:
            self.mark_saw_all_timestamps()

    def merge_timestamp_channels_arrays(self, arr_num1: int, arr_num2: int):
        timestamps_arrays = self.timestamps_arrays
        timestamp_data_map = self.timestamp_data_map
        arr1 = timestamps_arrays[arr_num1]
        arr2 = timestamps_arrays[arr_num2]

        if arr2.name == 'timestamps':
            # currently the first timestamps array must start at the first ts
            raise NotImplementedError

        self.unsaved_callback()
        self.pad_all_channels_to_num_frames(arr_num1)

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

    def create_timestamps_channels_array(self) -> int:
        self.unsaved_callback()
        n = self.increment_timestamps_arrays_counter()

        block = self.nix_file.blocks['timestamps']
        self.timestamps_arrays[n] = block.create_data_array(
            'timestamps_{}'.format(n), 'timestamps', dtype=np.float64,
            data=[])

        for chan in self.event_channels.values():
            chan.create_data_array(n)
        for chan in self.pos_channels.values():
            chan.create_data_array(n)
        return n

    def pad_channel_to_num_frames(self, channel: 'TemporalDataChannelBase'):
        array_num = self._last_timestamps_n
        if array_num is None:
            return

        size = len(self.timestamps_arrays[array_num])
        if not size:
            return

        channel.pad_channel_to_num_frames(array_num, size)

    def pad_all_channels_to_num_frames(self, array_num=None):
        if array_num is None:
            array_num = self._last_timestamps_n
            if array_num is None:
                return
            self._last_timestamps_n = None

        size = len(self.timestamps_arrays[array_num])
        if not size:
            return

        self.unsaved_callback()
        for chan in self.event_channels.values():
            chan.pad_channel_to_num_frames(array_num, size)
        for chan in self.pos_channels.values():
            chan.pad_channel_to_num_frames(array_num, size)

    def add_timestamp(self, t: float) -> int:
        """We assume that this is called frame by frame with no skipping unless
        :meth:`notify_interrupt_timestamps` was called.

        :param t:
        :return:
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
            if n != last_timestamps_n and last_timestamps_n is not None:
                n = self.merge_timestamp_channels_arrays(last_timestamps_n, n)
                if self._saw_last_timestamp and self._saw_first_timestamp and \
                        len(self.timestamps_arrays) == 1:
                    self.mark_saw_all_timestamps()
            self._last_timestamps_n = n
            return n

        # we have NOT seen this time stamp before. Do we have an array to add
        if last_timestamps_n is None:
            if not self.has_content:
                n = 0
            else:
                n = self.create_timestamps_channels_array()
            last_timestamps_n = self._last_timestamps_n = n

        data_array = self.timestamps_arrays[last_timestamps_n]
        timestamps_map[t] = last_timestamps_n, len(data_array)
        data_array.append(t)
        return last_timestamps_n

    def get_channel_from_id(self, i):
        if i in self.event_channels:
            return self.event_channels[i]
        elif i in self.pos_channels:
            return self.pos_channels[i]
        elif i in self.zone_channels:
            return self.zone_channels[i]
        else:
            raise ValueError(i)

    def delete_channel(self, i):
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


class DataChannelBase(object):

    data_file: DataFile = None

    metadata: nix.Section = None

    name: str = ''

    num: int = 0

    block: nix.Block = None

    def __init__(self, name, num, block, data_file, **kwargs):
        super(DataChannelBase, self).__init__(**kwargs)
        self.name = name
        self.num = num
        self.block = block
        self.data_arrays = {}
        self.metadata = block.metadata
        self.data_file = data_file

    def create_initial_data(self):
        raise NotImplementedError

    def read_initial_data(self):
        raise NotImplementedError

    def write_channel_config(self, data: dict):
        self.data_file.unsaved_callback()
        config = self.metadata
        for k, v in data.items():
            config[k] = yaml_dumps(v)

    def read_channel_config(self):
        config = self.metadata
        data = {}
        for prop in config.props:
            data[prop.name] = yaml_loads(read_nix_prop(prop))
        return data


class TemporalDataChannelBase(DataChannelBase):

    data_array: nix.DataArray = None

    data_arrays: Dict[int, nix.DataArray] = {}

    default_data_value = None

    def create_initial_data(self):
        self.data_file.unsaved_callback()

        timestamps = self.data_file.timestamps_arrays
        for i, timestamps_arr in timestamps.items():
            self.create_data_array(i, count=len(timestamps_arr))

        self.data_array = data_array = self.data_arrays[0]
        data_array.metadata = self.metadata

    def create_data_array(self, n=0, count=None):
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
        data_arrays = self.data_arrays
        arr1 = data_arrays[arr_num1]
        arr2 = data_arrays[arr_num2]
        assert arr2 is not self.data_array

        self.data_file.unsaved_callback()
        arr1.append(arr2)
        del self.block.data_arrays[arr2.name]
        del data_arrays[arr_num2]

    def pad_channel_to_num_frames(self, array_num, size):
        arr = self.data_arrays[array_num]
        n = len(arr)
        diff = size - n
        assert diff >= 0

        if not diff:
            return

        self.data_file.unsaved_callback()
        arr.append(self.default_data_value.repeat(diff, axis=0))

    def get_timestamps_modified_state(self) -> Dict[float, bool]:
        raise NotImplementedError

    def set_timestamp_value(self, t, value):
        raise NotImplementedError

    def get_timestamp_value(self, t):
        raise NotImplementedError

    def reset_data_to_default(self):
        for arr in self.data_arrays.values():
            arr[:] = self.default_data_value


class EventChannelData(TemporalDataChannelBase):

    default_data_value = np.array([0], dtype=np.uint8)

    def create_data_array(self, n=0, count=None):
        self.data_file.unsaved_callback()
        name = self.name if not n else '{}_group_{}'.format(self.name, n)

        if not count:
            self.data_arrays[n] = self.block.create_data_array(
                name, 'event', dtype=np.uint8, data=[])
        else:
            self.data_arrays[n] = self.block.create_data_array(
                name, 'event', dtype=np.uint8,
                data=self.default_data_value.repeat(count, axis=0))

    def get_timestamps_modified_state(self):
        self.data_file.pad_channel_to_num_frames(self)
        data_arrays = self.data_arrays
        timestamp_arrays = self.data_file.timestamps_arrays

        results = {}
        for i in data_arrays:
            data_array = np.array(data_arrays[i]) != 0
            timestamp_array = np.array(timestamp_arrays[i])
            for j in range(len(timestamp_array)):
                results[timestamp_array[j]] = data_array[j]

        return results

    def set_timestamp_value(self, t, value):
        self.data_file.pad_channel_to_num_frames(self)
        data_file = self.data_file
        data_file.unsaved_callback()
        n, i = data_file.timestamp_data_map[t]
        self.data_arrays[n][i] = value

    def get_timestamp_value(self, t):
        n, i = self.data_file.timestamp_data_map[t]
        if len(self.data_arrays[n]) <= i:
            return False
        return bool(self.data_arrays[n][i])


class PosChannelData(TemporalDataChannelBase):

    default_data_value = np.array([[-1, -1]], dtype=np.float64)

    def create_data_array(self, n=0, count=None):
        self.data_file.unsaved_callback()
        name = self.name if not n else '{}_group_{}'.format(self.name, n)

        if not count:
            self.data_arrays[n] = self.block.create_data_array(
                name, 'pos', dtype=np.float64, data=np.empty((0, 2)))
        else:
            self.data_arrays[n] = self.block.create_data_array(
                name, 'pos', dtype=np.float64,
                data=self.default_data_value.repeat(count, axis=0))

    def get_timestamps_modified_state(self):
        self.data_file.pad_channel_to_num_frames(self)
        data_arrays = self.data_arrays
        timestamp_arrays = self.data_file.timestamps_arrays

        results = {}
        for i in data_arrays:
            data_array = np.array(data_arrays[i])[:, 0] != -1
            timestamp_array = np.array(timestamp_arrays[i])
            for j in range(len(timestamp_array)):
                results[timestamp_array[j]] = data_array[j]

        return results

    def set_timestamp_value(self, t, value):
        self.data_file.pad_channel_to_num_frames(self)
        data_file = self.data_file
        data_file.unsaved_callback()
        n, i = data_file.timestamp_data_map[t]
        self.data_arrays[n][i, :] = value

    def get_timestamp_value(self, t):
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

    def create_initial_data(self):
        pass

    def read_initial_data(self):
        pass
