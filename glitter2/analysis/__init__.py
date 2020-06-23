from os.path import exists
import nixio as nix
import numpy as np
import numpy.linalg
from typing import Dict, List, Optional, Tuple
import pandas as pd

from kivy_garden.collider import Collide2DPoly, CollideEllipse

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
        metadata['pixels_per_meter'] = data_file.pixels_per_meter

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
        # export_accumulated_named_statistics provides the header
        video_head = self.metadata['filename_head']
        video_tail = self.metadata['filename_tail']
        filename = self.filename
        missed_timestamps = self.missed_timestamps
        rows = []

        for stat_names, channels in [
                (events or {}, self.event_channels),
                (pos or {}, self.pos_channels),
                (zones or {}, self.zone_channels)]:
            if not stat_names:
                continue

            for channel in channels:
                row_ = [
                    filename, video_head, video_tail, missed_timestamps,
                    channel.__class__.__name__[:-15], channel.name]

                stats = channel.compute_named_statistics(stat_names)
                for stat, stat_name in zip(stats, stat_names):
                    measure, *key = stat_name.split(':')
                    row = row_[:]
                    row.extend((measure, key[0] if key else '', stat))
                    rows.append(row)

        return rows

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

        header = [
            'data file', 'video path', 'video filename', 'missed timestamps',
            'channel_type', 'channel', 'measure', 'measure_key', 'value']
        df = pd.DataFrame(data, columns=header)
        df.to_excel(excel_writer, sheet_name='data', index=False)

        excel_writer.save()

    def export_raw_data_to_excel(self, filename, dump_zone_collider=False):
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
            name = channel.metadata['name']
            data = channel.data

            columns_header.append(f'{name}:x')
            columns_header.append(f'{name}:y')
            columns.append(data[:, 0])
            columns.append(data[:, 1])

            if dump_zone_collider:
                for zone in self.zone_channels:
                    valid_points = data[:, 0] != -1
                    zone_name = zone.metadata['name']
                    columns_header.append(f'{name}:{zone_name}')

                    collider = zone.collider
                    valid_points[valid_points] = collider.collide_points(
                        data[valid_points, :].tolist())
                    columns.append(valid_points)

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

    @staticmethod
    def _get_active_intervals(
            data: np.ndarray, timestamps: np.ndarray,
            start: float = None, end: float = None) -> Dict[str, np.ndarray]:
        s = 0
        if start is not None:
            s = np.searchsorted(timestamps, start, side='left')
        e = timestamps.shape[0]
        if end is not None:
            e = np.searchsorted(data, end, side='right')

        data = data[s:e]
        timestamps = timestamps[s:e]
        if data.shape[0] <= 1:
            intervals = np.empty((0, 2))
            indices = np.arange(0)
            return {'intervals': intervals, 'timestamps': timestamps,
                    'mask': data, 'indices': indices, 'start': s, 'end': e}

        arange = np.arange(data.shape[0])
        signed_data = data.astype(np.int8)
        diff = signed_data[1:] - signed_data[:-1]

        pos_diff = diff == 1
        starts = timestamps[1:][pos_diff]
        starts_indices = arange[1:][pos_diff]

        neg_diff = diff == -1
        ends = timestamps[1:][neg_diff]
        ends_indices = arange[1:][neg_diff]

        # de we need the first index as the start (if array starts with 1)
        # # of intervals is same as number of start positions
        n = starts.shape[0]
        if data[0] == 1:
            n += 1
        intervals = np.empty((n, 2))
        indices = np.empty((n, 2), dtype=arange.dtype)

        # interval starts at zero
        if data[0] == 1:
            intervals[1:, 0] = starts
            intervals[0, 0] = timestamps[0]

            indices[1:, 0] = starts_indices
            indices[0, 0] = 0
        else:
            intervals[:, 0] = starts
            indices[:, 0] = starts_indices

        if data[-1] == 1:
            intervals[:-1, 1] = ends
            intervals[-1, 1] = timestamps[-1]

            indices[:-1, 1] = ends_indices
            indices[-1, 1] = arange[-1]
        else:
            intervals[:, 1] = ends
            indices[:, 1] = ends_indices

        return {'intervals': intervals, 'timestamps': timestamps,
                'mask': data, 'indices': indices, 'start': s, 'end': e}

    @staticmethod
    def _compute_active_duration(intervals: np.ndarray) -> float:
        return np.sum(
            intervals[:, 1] - intervals[:, 0]) if intervals.shape[0] else 0.

    @staticmethod
    def _compute_delay_to_first(intervals: np.ndarray) -> float:
        return intervals[0, 0] if intervals.shape[0] else -1.

    @staticmethod
    def _compute_scored_duration(timestamps: np.ndarray) -> float:
        return timestamps[-1] - timestamps[0] if timestamps.shape[0] else 0.

    @staticmethod
    def _compute_event_count(intervals: np.ndarray) -> int:
        return intervals.shape[0]


class EventAnalysisChannel(TemporalAnalysisChannel):

    data_channel: EventChannelData = None

    _active_duration: Tuple[float, Tuple] = None

    _delay_to_first: Tuple[float, Tuple] = None

    _scored_duration: Tuple[float, Tuple] = None

    _event_count: Tuple[int, Tuple] = None

    _active_interval: Tuple[Dict[str, np.ndarray], Tuple] = None

    def get_active_intervals(
            self, start=None, end=None) -> Dict[str, np.ndarray]:
        interval = self._active_interval
        if interval is not None and interval[1] == (start, end):
            return interval[0]

        intervals = self._get_active_intervals(
            self.data, self.analysis_file.timestamps, start=start, end=end)
        self._active_interval = intervals, (start, end)
        return intervals

    def compute_active_duration(self, start=None, end=None) -> float:
        duration = self._active_duration
        if duration is not None and duration[1] == (start, end):
            return duration[0]

        intervals = self.get_active_intervals(start, end)['intervals']
        val = self._compute_active_duration(intervals)
        self._active_duration = val, (start, end)
        return val

    def compute_delay_to_first(self, start=None, end=None) -> float:
        delay = self._delay_to_first
        if delay is not None and delay[1] == (start, end):
            return delay[0]

        intervals = self.get_active_intervals(start, end)['intervals']
        val = self._compute_delay_to_first(intervals)
        self._delay_to_first = val, (start, end)
        return val

    def compute_scored_duration(self, start=None, end=None) -> float:
        duration = self._scored_duration
        if duration is not None and duration[1] == (start, end):
            return duration[0]

        timestamps = self.get_active_intervals(start, end)['timestamps']
        val = self._compute_scored_duration(timestamps)
        self._scored_duration = val, (start, end)
        return val

    def compute_event_count(self, start=None, end=None) -> int:
        count = self._event_count
        if count is not None and count[1] == (start, end):
            return count[0]

        intervals = self.get_active_intervals(start, end)['intervals']
        val = self._compute_event_count(intervals)
        self._event_count = val, (start, end)
        return val


class PosAnalysisChannel(TemporalAnalysisChannel):

    data_channel: PosChannelData = None

    _active_duration: Dict[str, Tuple[float, Tuple]] = None

    _delay_to_first: Dict[str, Tuple[float, Tuple]] = None

    _scored_duration: Dict[str, Tuple[float, Tuple]] = None

    _event_count: Dict[str, Tuple[int, Tuple]] = None

    _mean_center_distance: Dict[str, Tuple[float, Tuple]] = None

    _mean_distance_traveled: Dict[str, Tuple[float, Tuple]] = None

    _mean_speed: Dict[str, Tuple[float, Tuple]] = None

    _active_interval: Dict[str, Tuple[Dict[str, np.ndarray], Tuple]] = None

    def __init__(self, **kwargs):
        super(PosAnalysisChannel, self).__init__(**kwargs)
        self._active_duration = {}
        self._delay_to_first = {}
        self._scored_duration = {}
        self._event_count = {}
        self._mean_center_distance = {}
        self._mean_distance_traveled = {}
        self._mean_speed = {}
        self._active_interval = {}

    def get_active_intervals(
            self, mask_channels: List[str] = (), mask_key: str = '',
            start=None, end=None) -> Dict[str, np.ndarray]:
        interval = self._active_interval
        if mask_key in interval and interval[mask_key][1] == (start, end):
            return interval[mask_key][0]

        data = self.data
        if not mask_channels:
            data = data[:, 0] != -1
        else:
            zone_channels = self.analysis_file.zone_channel_names
            event_channels = self.analysis_file.event_channel_names
            arr = [data[:, 0] != -1]
            for name in mask_channels:
                if name in zone_channels:
                    d = zone_channels[name].collider.collide_points(data)
                else:
                    d = event_channels[name].data
                arr.append(d)

            data = np.logical_and.reduce(arr, axis=0)

        intervals = self._get_active_intervals(
            data, self.analysis_file.timestamps, start=start, end=end)
        self._active_interval[mask_key] = intervals, (start, end)
        return intervals

    def compute_active_duration(
            self, mask_channels: List[str] = (), start=None,
            end=None) -> float:
        mask_key = '\0'.join(mask_channels)
        duration = self._active_duration
        if mask_key in duration and duration[mask_key][1] == (start, end):
            return duration[mask_key][0]

        intervals = self.get_active_intervals(
            mask_channels, mask_key, start, end)['intervals']
        val = self._compute_active_duration(intervals)
        self._active_duration[mask_key] = val, (start, end)
        return val

    def compute_delay_to_first(
            self, mask_channels: List[str] = (), start=None,
            end=None) -> float:
        mask_key = '\0'.join(mask_channels)
        delay = self._delay_to_first
        if mask_key in delay and delay[mask_key][1] == (start, end):
            return delay[mask_key][0]

        intervals = self.get_active_intervals(
            mask_channels, mask_key, start, end)['intervals']
        val = self._compute_delay_to_first(intervals)
        self._delay_to_first[mask_key] = val, (start, end)
        return val

    def compute_scored_duration(
            self, mask_channels: List[str] = (), start=None,
            end=None) -> float:
        mask_key = '\0'.join(mask_channels)
        duration = self._scored_duration
        if mask_key in duration and duration[mask_key][1] == (start, end):
            return duration[mask_key][0]

        timestamps = self.get_active_intervals(
            mask_channels, mask_key, start, end)['timestamps']
        val = self._compute_scored_duration(timestamps)
        self._scored_duration[mask_key] = val, (start, end)
        return val

    def compute_event_count(
            self, mask_channels: List[str] = (), start=None, end=None) -> int:
        mask_key = '\0'.join(mask_channels)
        count = self._event_count
        if mask_key in count and count[mask_key][1] == (start, end):
            return count[mask_key][0]

        intervals = self.get_active_intervals(
            mask_channels, mask_key, start, end)['intervals']
        val = self._compute_event_count(intervals)
        self._event_count[mask_key] = val, (start, end)
        return val

    def compute_mean_center_distance(
            self, zone: str, start=None, end=None) -> float:
        dist = self._mean_center_distance
        if zone in dist and dist[zone][1] == (start, end):
            return dist[zone][0]

        data = self.data - \
            self.analysis_file.zone_channel_names[zone].collider.get_centroid()
        val = float(np.mean(numpy.linalg.norm(data, axis=1)))

        self._mean_center_distance[zone] = val, (start, end)
        return val

    def compute_distance_traveled(
            self, mask_channels: List[str] = (), start=None,
            end=None) -> float:
        mask_key = '\0'.join(mask_channels)
        dist = self._mean_distance_traveled
        if mask_key in dist and dist[mask_key][1] == (start, end):
            return dist[mask_key][0]

        pixels_per_meter = self.analysis_file.metadata['pixels_per_meter']
        intervals_dict = self.get_active_intervals(
            mask_channels, mask_key, start, end)
        indices = intervals_dict['indices']
        data = self.data[intervals_dict['start']:intervals_dict['end'], :]

        val = 0
        for s, e in indices:
            val += np.sum(
                np.linalg.norm(data[s + 1:e + 1, :] - data[s:e, :], axis=1))
        if pixels_per_meter:
            val /= pixels_per_meter

        self._mean_distance_traveled[mask_key] = val, (start, end)
        return val

    def compute_mean_speed(
            self, mask_channels: List[str] = (), start=None,
            end=None) -> float:
        mask_key = '\0'.join(mask_channels)
        speed = self._mean_speed
        if mask_key in speed and speed[mask_key][1] == (start, end):
            return speed[mask_key][0]

        pixels_per_meter = self.analysis_file.metadata['pixels_per_meter']
        intervals_dict = self.get_active_intervals(
            mask_channels, mask_key, start, end)
        intervals = intervals_dict['intervals']
        indices = intervals_dict['indices']
        data = self.data[intervals_dict['start']:intervals_dict['end'], :]

        dist = 0
        for s, e in indices:
            dist += np.sum(
                np.linalg.norm(data[s + 1:e + 1, :] - data[s:e, :], axis=1))
        if pixels_per_meter:
            dist /= pixels_per_meter

        dt = np.sum(intervals[:, 1] - intervals[:, 0])
        val = 0.
        if dt:
            val = dist / dt

        self._mean_speed[mask_key] = val, (start, end)
        return val


class ZoneAnalysisChannel(AnalysisChannel):

    data_channel: ZoneChannelData = None

    _collider = None

    @property
    def collider(self):
        collider = self._collider
        if collider is not None:
            return collider

        shape_metadata = self.metadata['shape_config']
        cls_name = shape_metadata['cls']
        if cls_name in ('PaintPolygon', 'PaintFreeformPolygon'):
            collider = Collide2DPoly(
                points=shape_metadata['points'], cache=True)
        elif cls_name == 'PaintCircle':
            x, y = shape_metadata['center']
            r = shape_metadata['radius']
            collider = CollideEllipse(x=x, y=y, rx=r, ry=r)
        elif cls_name == 'PaintEllipse':
            x, y = shape_metadata['center']
            rx, ry = shape_metadata['radius_x'], shape_metadata['radius_y']
            collider = CollideEllipse(
                x=x, y=y, rx=rx, ry=ry, angle=shape_metadata['angle'])
        else:
            assert False

        self._collider = collider
        return collider

    def compute_area(self) -> float:
        return self.collider.get_area()
