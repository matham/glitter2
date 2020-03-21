from os.path import exists
import nixio as nix
import numpy as np
from typing import Dict, List, Optional, Tuple
import pandas as pd

from glitter2.storage.data_file import DataFile, EventChannelData, \
    PosChannelData, ZoneChannelData, DataChannelBase, TemporalDataChannelBase


def _sort_dict(d: dict) -> List[tuple]:
    return list(sorted(d.items(), key=lambda x: x[0]))


class FileDataAnalysis(object):

    filename: str = ''

    data_file: DataFile = None

    nix_file: nix.File = None

    metadata: Dict = {}

    timestamps: np.ndarray = None

    event_channels: List['EventAnalysisChannel'] = []

    pos_channels: List['PosAnalysisChannel'] = []

    zone_channels: List['ZoneAnalysisChannel'] = []

    event_channel_names: Dict[str, 'EventAnalysisChannel'] = {}

    pos_channel_names: Dict[str, 'PosAnalysisChannel'] = {}

    zone_channel_names: Dict[str, 'ZoneAnalysisChannel'] = {}

    missed_timestamps = False

    missing_timestamp_values = []

    def __init__(self, filename, **kwargs):
        super(FileDataAnalysis, self).__init__(**kwargs)
        self.nix_file = nix.File.open(filename, nix.FileMode.ReadOnly)
        self.data_file = DataFile(nix_file=self.nix_file)
        self.filename = filename

    def load_data(self):
        data_file = self.data_file
        data_file.open_file()

        self.metadata = metadata = data_file.get_video_metadata()
        metadata['saw_all_timestamps'] = data_file.saw_all_timestamps
        metadata['glitter2_version'] = data_file.glitter2_version
        metadata['ffpyplayer_version'] = data_file.ffpyplayer_version

        self.missed_timestamps = not data_file.saw_all_timestamps
        if self.missed_timestamps:
            data_arrays_order = data_file.ordered_timestamps_indices
            data = [data_file.timestamps_arrays[i] for i in data_arrays_order]
            missing = [float(item[-1]) for item in data[:-1]]
            if not data_file._saw_first_timestamp:
                missing.insert(0, float(data[0][0]))
            if not data_file._saw_last_timestamp:
                missing.append(float(data[-1][-1]))

            self.missing_timestamp_values = missing
        else:
            self.missing_timestamp_values = []

        data_arrays_order = []
        if len(data_file.timestamps_arrays) > 1:
            data_arrays_order = data_file.ordered_timestamps_indices
            data = [data_file.timestamps_arrays[i] for i in data_arrays_order]
            self.timestamps = np.concatenate(data)
        else:
            self.timestamps = np.array(data_file.timestamps)

        event_channels = self.event_channels = []
        event_channel_names = self.event_channel_names = {}
        for _, channel in _sort_dict(data_file.event_channels):
            analysis_channel = EventAnalysisChannel(
                data_channel=channel, analysis_file=self)

            event_channels.append(analysis_channel)
            analysis_channel.load_data(data_arrays_order=data_arrays_order)
            event_channel_names[analysis_channel.name] = analysis_channel

        pos_channels = self.pos_channels = []
        pos_channel_names = self.pos_channel_names = {}
        for _, channel in _sort_dict(data_file.pos_channels):
            analysis_channel = PosAnalysisChannel(
                data_channel=channel, analysis_file=self)

            pos_channels.append(analysis_channel)
            analysis_channel.load_data(data_arrays_order=data_arrays_order)
            pos_channel_names[analysis_channel.name] = analysis_channel

        zone_channels = self.zone_channels = []
        zone_channel_names = self.zone_channel_names = {}
        for _, channel in _sort_dict(data_file.zone_channels):
            analysis_channel = ZoneAnalysisChannel(
                data_channel=channel, analysis_file=self)

            zone_channels.append(analysis_channel)
            analysis_channel.load_data()
            zone_channel_names[analysis_channel.name] = analysis_channel

    def get_named_statistics(
            self, events: Dict[str, dict] = None, pos: Dict[str, dict] = None,
            zones: Dict[str, dict] = None) -> List:
        video_head = self.metadata['filename_head']
        video_tail = self.metadata['filename_tail']
        missed_timestamps = self.missed_timestamps

        results = []
        for stat_names, channels, sheet in [
                (events or {}, self.event_channels),
                (pos or {}, self.pos_channels),
                (zones or {}, self.zone_channels)]:
            if not stat_names:
                results.append(([], []))
                continue

            header = ['video path', 'video filename', 'missed timestamps',
                      'channel']
            header.extend(stat_names)

            rows = []
            for channel in channels:
                row = [video_head, video_tail, missed_timestamps, channel.name]
                row.extend(channel.compute_named_statistics(stat_names))
                rows.append(row)

            results.append((header, rows))
        return results

    @staticmethod
    def export_accumulated_named_statistics(filename: str, data: List):
        """Adds .xlsx to the name.

        :param filename:
        :param data:
        :return:
        """
        if not filename.endswith('.xlsx'):
            filename += '.xlsx'
        if exists(filename):
            raise ValueError('"{}" already exists'.format(filename))

        excel_writer = pd.ExcelWriter(filename, engine='xlsxwriter')

        event_header = None
        event_rows = []
        pos_header = None
        pos_rows = []
        zone_header = None
        zone_rows = []

        for (event_header, events), (pos_header, pos), \
                (zone_header, zones) in data:
            event_rows.extend(events)
            pos_rows.extend(pos)
            zone_rows.extend(zones)

        if event_header:
            df = pd.DataFrame(event_rows, columns=event_header)
            df.to_excel(excel_writer, sheet_name='event_channels', index=False)
        if pos_header:
            df = pd.DataFrame(pos_rows, columns=pos_header)
            df.to_excel(excel_writer, sheet_name='pos_channels', index=False)
        if zone_header:
            df = pd.DataFrame(zone_rows, columns=zone_header)
            df.to_excel(excel_writer, sheet_name='zone_channels', index=False)

        excel_writer.save()

    def export_raw_data_to_excel(self, filename):
        if exists(filename):
            raise ValueError('"{}" already exists'.format(filename))
        excel_writer = pd.ExcelWriter(filename, engine='xlsxwriter')

        if self.missed_timestamps:
            data = [
                'Not all video frames were watched - timestamps are missing']
            if self.missing_timestamp_values:
                data.append('timestamps around where frames are missing:')
                data.extend(self.missing_timestamp_values)

            df = pd.DataFrame(data)
            df.to_excel(
                excel_writer, sheet_name='missing_timestamps', index=False)

        file_metadata = _sort_dict(self.metadata)
        df = pd.DataFrame(file_metadata, columns=['Property', 'Value'])
        df.to_excel(excel_writer, sheet_name='file_metadata', index=False)

        metadata = []
        for channel in self.event_channels:
            metadata.append(('event_channel', channel.metadata['name']))
            metadata.extend(_sort_dict(channel.metadata))
        for channel in self.pos_channels:
            metadata.append(('pos_channel', channel.metadata['name']))
            metadata.extend(_sort_dict(channel.metadata))
        for channel in self.zone_channels:
            metadata.append(('zone_channel', channel.metadata['name']))
            # shape info is saved in the zone channels sheet
            d = dict(channel.metadata)
            d.pop('shape_config', None)
            metadata.extend(_sort_dict(d))
        df = pd.DataFrame(metadata, columns=['Property', 'Value'])
        df.to_excel(excel_writer, sheet_name='channels_metadata', index=False)

        df = pd.DataFrame(self.timestamps, columns=['timestamp'])
        df.to_excel(excel_writer, sheet_name='timestamps', index=False)

        columns_header = []
        columns = []
        for channel in self.event_channels:
            columns_header.append(channel.metadata['name'])
            columns.append(channel.data)
        df = pd.DataFrame(columns).T
        df.columns = columns_header
        df.to_excel(excel_writer, sheet_name='event_channels', index=False)

        columns_header = []
        columns = []
        for channel in self.pos_channels:
            columns_header.append(channel.metadata['name'] + ':x')
            columns_header.append(channel.metadata['name'] + ':y')
            columns.append(channel.data[:, 0])
            columns.append(channel.data[:, 1])
        df = pd.DataFrame(columns).T
        df.columns = columns_header
        df.to_excel(excel_writer, sheet_name='pos_channels', index=False)

        shape_config = []
        for channel in self.zone_channels:
            shape_config.append(('zone_channel', channel.metadata['name']))
            # only save shape info
            d = channel.metadata.get('shape_config', {})
            shape_config.extend(_sort_dict(d))
        df = pd.DataFrame(shape_config, columns=['Property', 'Value'])
        df.to_excel(excel_writer, sheet_name='zone_channels', index=False)

        excel_writer.save()

    def close(self):
        self.nix_file.close()


class AnalysisChannel(object):

    data_channel: DataChannelBase = None

    analysis_file: FileDataAnalysis = None

    metadata: Dict = {}

    name: str = ''

    def __init__(self, data_channel, analysis_file, **kwargs):
        super(AnalysisChannel, self).__init__(**kwargs)
        self.data_channel = data_channel
        self.analysis_file = analysis_file

    def load_data(self, *args, **kwargs):
        self.metadata = self.data_channel.read_channel_config()
        self.name = self.metadata['name']

    def compute_named_statistics(self, stat_options: Dict[str, dict]) -> List:
        res = []
        for stat, kwargs in stat_options.items():
            f_name = stat.split(':')[0]
            f = getattr(self, f'compute_{f_name}')
            res.append(f(**kwargs))

        return res


class TemporalAnalysisChannel(AnalysisChannel):

    data_channel: TemporalDataChannelBase = None

    data: np.ndarray = None

    def load_data(self, data_arrays_order):
        super(TemporalAnalysisChannel, self).load_data()

        data_channel = self.data_channel
        if len(data_channel.data_arrays) > 1:
            assert data_arrays_order
            data = [data_channel.data_arrays[i] for i in data_arrays_order]
            self.data = np.concatenate(data)
        else:
            self.data = np.array(data_channel.data_array)


class EventAnalysisChannel(TemporalAnalysisChannel):

    data_channel: EventChannelData = None

    _active_duration: Tuple[float, Tuple] = None

    _delay_to_first: Tuple[float, Tuple] = None

    _scored_duration: Tuple[float, Tuple] = None

    _event_count: Tuple[int, Tuple] = None

    _active_interval: Tuple[Tuple[np.ndarray, np.ndarray], Tuple] = None

    def get_active_intervals(
            self, start=None, end=None) -> Tuple[np.ndarray, np.ndarray]:
        interval = self._active_interval
        if interval is not None and interval[1] == (start, end):
            return interval[0]

        data = self.data
        timestamps = self.analysis_file.timestamps

        s = 0
        if start is not None:
            s = np.searchsorted(timestamps, start, side='left')
        e = len(timestamps)
        if end is not None:
            e = np.searchsorted(data, end, side='right')

        data = data[s:e]
        timestamps = timestamps[s:e]
        if len(data) <= 1:
            intervals = np.empty((0, 2))
            self._active_interval = (intervals, timestamps), (start, end)
            return intervals, timestamps

        diff = data[1:] - data[:-1]
        starts = timestamps[1:][diff == 1]
        ends = timestamps[1:][diff == -1]

        # de we need the first index as the start (if array starts with 1)
        n = len(starts)
        if data[0] == 1:
            n += 1
        intervals = np.empty((n, 2))

        if data[0] == 1:
            intervals[1:, 0] = starts
            intervals[0, 0] = timestamps[0]
        else:
            intervals[:, 0] = starts

        if data[-1] == 1:
            intervals[:-1, 1] = ends
            intervals[-1, 1] = timestamps[-1]
        else:
            intervals[:, 1] = ends

        self._active_interval = (intervals, timestamps), (start, end)
        return intervals, timestamps

    def compute_active_duration(self, start=None, end=None) -> float:
        duration = self._active_duration
        if duration is not None and duration[1] == (start, end):
            return duration[0]

        intervals, timestamps = self.get_active_intervals(start, end)
        val = np.sum(
            intervals[:, 1] - intervals[:, 0]) if len(intervals) else 0.
        self._active_duration = val, (start, end)
        return val

    def compute_delay_to_first(self, start=None, end=None) -> float:
        delay = self._delay_to_first
        if delay is not None and delay[1] == (start, end):
            return delay[0]

        intervals, timestamps = self.get_active_intervals(start, end)
        val = intervals[0, 0] if len(intervals) else -1.
        self._delay_to_first = val, (start, end)
        return val

    def compute_scored_duration(self, start=None, end=None) -> float:
        duration = self._scored_duration
        if duration is not None and duration[1] == (start, end):
            return duration[0]

        intervals, timestamps = self.get_active_intervals(start, end)
        val = timestamps[-1] - timestamps[0] if len(timestamps) else 0.
        self._scored_duration = val, (start, end)
        return val

    def compute_event_count(self, start=None, end=None) -> int:
        count = self._event_count
        if count is not None and count[1] == (start, end):
            return count[0]

        intervals, timestamps = self.get_active_intervals(start, end)
        self._event_count = intervals.shape[0], (start, end)
        return intervals.shape[0]


class PosAnalysisChannel(TemporalAnalysisChannel):

    data_channel: PosChannelData = None


class ZoneAnalysisChannel(AnalysisChannel):

    data_channel: ZoneChannelData = None
