"""Data Analysis
================

"""
from os.path import exists
import nixio as nix
import numpy as np
import numpy.linalg
from typing import Dict, List, Tuple, Type, Union, Set, Any, Optional, Iterator
import pandas as pd
from collections import defaultdict

from kivy_garden.collider import Collide2DPoly, CollideEllipse

from kivy_garden.painter import PaintCircle, PaintEllipse, PaintPolygon, \
    PaintFreeformPolygon, PaintPoint, PaintShape

from glitter2.storage.data_file import DataFile

__all__ = (
    'default_value', 'not_cached', 'AnalysisFactory', 'AnalysisSpec',
    'FileDataAnalysis', 'AnalysisChannel', 'TemporalAnalysisChannel',
    'EventAnalysisChannel', 'PosAnalysisChannel', 'ZoneAnalysisChannel')


def _sort_dict(d: dict) -> List[tuple]:
    return list(sorted(d.items(), key=lambda x: x[0]))


def _get_flat_types(type_hint):
    if hasattr(type_hint, '__origin__') and type_hint.__origin__ is Union:
        return type_hint.__args__
    return type_hint,


def _filter_default(type_hint):
    types = _get_flat_types(type_hint)
    default_types = {DefaultType, None, type(None)}
    types = [t for t in types if t not in default_types]
    if len(types) == 1:
        return types[0]
    raise ValueError(f'Expected one type value but got {types}')


class default_value(int):
    pass


DefaultType = Type[default_value]
DefaultFloat = Union[float, None, DefaultType]
DefaultStr = Union[str, None, DefaultType]
not_cached = object()


class AnalysisFactory:

    analysis_classes: Set[Type['AnalysisChannel']] = set()

    by_name: Dict[str, Type['AnalysisChannel']] = {}

    @classmethod
    def register_analysis_class(cls, analysis_class: Type['AnalysisChannel']):
        cls.analysis_classes.add(analysis_class)
        name = f'{analysis_class.__module__}\0{analysis_class.__qualname__}'
        cls.by_name[name] = analysis_class

    @classmethod
    def get_class_from_method(
            cls, method) -> Tuple[Type['AnalysisChannel'], str]:
        mod = method.__module__
        cls_name, method_name = method.__qualname__.rsplit('.', maxsplit=1)
        name = f'{mod}\0{cls_name}'

        if name not in cls.by_name:
            raise ValueError(
                f'Unrecognized class {cls_name} of method {method}')

        return cls.by_name[name], method_name


class AnalysisSpec:

    _default_args: Dict[Type['AnalysisChannel'], Dict[str, Any]] = {}

    _new_channels: List[
        Tuple[str, str, Type['AnalysisChannel'], str, tuple, dict]] = []

    _computations: List[
        Tuple[Optional[List[str]], str, Type['AnalysisChannel'], str, tuple,
              dict]] = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._default_args = defaultdict(dict)
        self._new_channels = []
        self._computations = []

    def add_arg_default(
            self, cls: Type['AnalysisChannel'], name: str, value: Any):
        self._default_args[cls][name] = value

    def add_new_channel_computation(
            self, channel: str, new_channel_name: str, compute_method,
            *args, **kwargs):
        cls, method_name = AnalysisFactory.get_class_from_method(
            compute_method)
        self._new_channels.append(
            (channel, new_channel_name, cls, method_name, args, kwargs))

    def add_computation(
            self, channels: Optional[List[str]], compute_method, *args,
            compute_key: str = '', **kwargs):
        cls, method_name = AnalysisFactory.get_class_from_method(
            compute_method)
        self._computations.append(
            (channels, compute_key, cls, method_name, args, kwargs))

    def compute_create_channels(self, analysis_object: 'FileDataAnalysis'):
        default_args = self._default_args
        cls_cache = {}

        for channel, new_name, cls, method_name, args, kwargs in \
                self._new_channels:
            cache_key = cls, channel
            if cache_key not in cls_cache:
                obj = cls_cache[cache_key] = cls(
                    name=channel, analysis_object=analysis_object)

                for name, value in default_args.get(cls, {}).items():
                    setattr(obj, name, value)

            analysis_channel = cls_cache[cache_key]

            brief_name = method_name
            if brief_name.startswith('compute_'):
                brief_name = brief_name[8:]

            # get the type of channel created
            create_map = \
                analysis_channel.spec_get_channel_creating_methods()
            ret_type = create_map[brief_name]

            f = getattr(analysis_channel, method_name)
            res = f(*args, **kwargs)

            # add the channel to the data analysis object
            add = getattr(analysis_object, f'add_{ret_type}_channel')
            add(new_name, *res)

    def compute(self, analysis_object: 'FileDataAnalysis') -> list:
        output = []
        default_args = self._default_args
        cls_cache = {}

        for channels, compute_key, cls, method_name, args, kwargs in \
                self._computations:
            if not channels:
                if cls.analysis_type == 'event':
                    channels = analysis_object.event_channels_data.keys()
                elif cls.analysis_type == 'pos':
                    channels = analysis_object.pos_channels_data.keys()
                elif cls.analysis_type == 'zone':
                    channels = analysis_object.zone_channels_shapes.keys()

            for channel in channels:
                cache_key = cls, channel
                if cache_key not in cls_cache:
                    obj = cls_cache[cache_key] = cls(
                        name=channel, analysis_object=analysis_object)

                    for name, value in default_args.get(cls, {}).items():
                        setattr(obj, name, value)

                analysis_channel = cls_cache[cache_key]

                brief_name = method_name
                if brief_name.startswith('compute_'):
                    brief_name = brief_name[8:]

                f = getattr(analysis_channel, method_name)
                res = f(*args, **kwargs)

                output.append(
                    (analysis_channel.analysis_type, channel, brief_name,
                     compute_key, res))

        return output


class FileDataAnalysis:

    filename: str = ''

    data_file: DataFile = None

    nix_file: Optional[nix.File] = None

    metadata: Dict = {}

    video_metadata: Dict = {}

    timestamps: np.ndarray = None

    event_channels_data: Dict[str, np.ndarray] = {}

    pos_channels_data: Dict[str, np.ndarray] = {}

    zone_channels_shapes: Dict[str, PaintShape] = {}

    channels_metadata: Dict[str, dict] = {}

    missed_timestamps = False

    missing_timestamp_values = []

    pixels_per_meter = 0

    def __init__(self, filename, **kwargs):
        super(FileDataAnalysis, self).__init__(**kwargs)
        self.filename = filename

        self.event_channels_data = {}
        self.pos_channels_data = {}
        self.zone_channels_shapes = {}
        self.channels_metadata = {}

    def flatten_data(self, data_arrays) -> np.ndarray:
        ordered_indices = self.data_file.timestamp_intervals_ordered_keys
        if len(data_arrays) > 1:
            data = [data_arrays[i] for i in ordered_indices]
            return np.concatenate(data)
        else:
            return np.array(data_arrays[0])

    def __enter__(self):
        self.open_data_file()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_data_file()

    def open_data_file(self):
        self.nix_file = nix.File.open(self.filename, nix.FileMode.ReadOnly)
        self.data_file = DataFile(nix_file=self.nix_file)

    def load_file_data(self, channels: Set[str] = None):
        data_file = self.data_file
        data_file.open_file()

        self.video_metadata = data_file.video_metadata_dict
        self.metadata = metadata = {}
        metadata['saw_all_timestamps'] = data_file.saw_all_timestamps
        metadata['glitter2_version'] = data_file.glitter2_version
        metadata['ffpyplayer_version'] = data_file.ffpyplayer_version
        metadata['pixels_per_meter'] = data_file.pixels_per_meter
        self.pixels_per_meter = data_file.pixels_per_meter

        self.missed_timestamps = not data_file.saw_all_timestamps
        if self.missed_timestamps:
            data_arrays_order = data_file.timestamp_intervals_ordered_keys
            data = [data_file.timestamps_arrays[i] for i in data_arrays_order]
            missing = [float(item[-1]) for item in data[:-1]]
            if not data_file._saw_first_timestamp:
                missing.insert(0, float(data[0][0]))
            if not data_file._saw_last_timestamp:
                missing.append(float(data[-1][-1]))

            self.missing_timestamp_values = missing
        else:
            self.missing_timestamp_values = []

        self.timestamps = self.flatten_data(data_file.timestamps_arrays)

        metadata = self.channels_metadata
        zone_channels_shapes = self.zone_channels_shapes
        shape_cls_map = {
            'PaintCircle': PaintCircle, 'PaintEllipse': PaintEllipse,
            'PaintPolygon': PaintPolygon,
            'PaintFreeformPolygon': PaintFreeformPolygon,
            'PaintPoint': PaintPoint
        }
        for channels_data, src_channels in (
                (self.event_channels_data, data_file.event_channels),
                (self.pos_channels_data, data_file.pos_channels),
                (None, data_file.zone_channels)):
            for _, channel in _sort_dict(src_channels):
                m = channel.channel_config_dict
                name = m['name']
                if channels and name not in channels:
                    continue

                metadata[name] = m
                if channels_data is None:
                    state = m['shape_config']
                    cls = shape_cls_map[state['cls']]
                    shape = cls.create_shape_from_state(state)
                    zone_channels_shapes[name] = shape
                else:
                    channels_data[name] = self.flatten_data(
                        channel.data_arrays)

    def close_data_file(self):
        if self.nix_file is None:
            return
        self.nix_file.close()
        self.nix_file = None

    def compute_data_summary(self, spec: AnalysisSpec) -> list:
        # export_computed_statistics provides the header
        rows = []

        filename = self.filename
        video_head = self.video_metadata['filename_head']
        video_tail = self.video_metadata['filename_tail']
        missed_timestamps = self.missed_timestamps
        row = [filename, video_head, video_tail, missed_timestamps]

        # first create all new data channels
        spec.compute_create_channels(self)

        # now compute any stats
        for stat in spec.compute(self):
            rows.append(row + list(stat))

        return rows

    @staticmethod
    def export_computed_data_summary(filename: str, data: list):
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
        df.to_excel(excel_writer, sheet_name='statistics', index=False)

        excel_writer.save()

    def export_raw_data_to_excel(self, filename, dump_zone_collider=False):
        if not filename.endswith('.xlsx'):
            filename += '.xlsx'

        if exists(filename):
            raise ValueError('"{}" already exists'.format(filename))
        excel_writer = pd.ExcelWriter(filename, engine='xlsxwriter')

        if self.missed_timestamps:
            # if we have timestamp discontinuities, indicate it
            data = [
                'Not all video frames were watched - timestamps are missing']
            if self.missing_timestamp_values:
                data.append('timestamps around where frames are missing:')
                data.extend(self.missing_timestamp_values)

            df = pd.DataFrame(data)
            df.to_excel(
                excel_writer, sheet_name='missing_timestamps', index=False)

        file_metadata = dict(self.metadata)
        file_metadata.update(self.video_metadata)
        file_metadata = _sort_dict(file_metadata)
        df = pd.DataFrame(file_metadata, columns=['Property', 'Value'])
        df.to_excel(excel_writer, sheet_name='file_metadata', index=False)

        # add sheet for all the channels metadata
        metadata = []
        channels_metadata = self.channels_metadata
        for channel_name in self.event_channels_data:
            metadata.append(('event_channel', channel_name))
            metadata.extend(_sort_dict(channels_metadata[channel_name]))
        for channel_name in self.pos_channels_data:
            metadata.append(('pos_channel', channel_name))
            metadata.extend(_sort_dict(channels_metadata[channel_name]))
        for channel_name in self.zone_channels_shapes:
            metadata.append(('zone_channel', channel_name))
            # shape info is saved in the zone channels sheet
            d = dict(channels_metadata[channel_name])
            d.pop('shape_config', None)
            metadata.extend(_sort_dict(d))
        df = pd.DataFrame(metadata, columns=['Property', 'Value'])
        df.to_excel(excel_writer, sheet_name='channels_metadata', index=False)

        # add timestamps
        df = pd.DataFrame(self.timestamps, columns=['timestamp'])
        df.to_excel(excel_writer, sheet_name='timestamps', index=False)

        # add event channels data
        columns_header = []
        columns = []
        for channel_name, data in self.event_channels_data.items():
            columns_header.append(channel_name)
            columns.append(data)
        df = pd.DataFrame(columns).T
        df.columns = columns_header
        df.to_excel(excel_writer, sheet_name='event_channels', index=False)

        # add pos channels data
        colliders = {}
        if dump_zone_collider:
            for channel_name, shape in self.zone_channels_shapes.items():
                colliders[channel_name] = \
                    ZoneAnalysisChannel.collider_from_shape(shape)

        columns_header = []
        columns = []
        for channel_name, data in self.pos_channels_data.items():
            columns_header.append(f'{channel_name}:x')
            columns_header.append(f'{channel_name}:y')
            columns.append(data[:, 0])
            columns.append(data[:, 1])

            for zone_name, collider in colliders.items():
                valid_points = data[:, 0] != -1
                columns_header.append(f'{channel_name}:--:{zone_name}')

                valid_points[valid_points] = collider.collide_points(
                    data[valid_points, :].tolist())
                columns.append(valid_points)

        df = pd.DataFrame(columns).T
        df.columns = columns_header
        df.to_excel(excel_writer, sheet_name='pos_channels', index=False)

        # add zone channels metadata
        shape_config = []
        for channel_name in self.zone_channels_shapes:
            shape_config.append(('zone_channel', channel_name))
            # only save shape info
            d = channels_metadata[channel_name].get('shape_config', {})
            shape_config.extend(_sort_dict(d))
        df = pd.DataFrame(shape_config, columns=['Property', 'Value'])
        df.to_excel(excel_writer, sheet_name='zone_channels', index=False)

        excel_writer.save()

    def add_event_channel(self, name: str, data: np.ndarray, metadata: dict):
        if name in self.channels_metadata:
            raise ValueError(f'name "{name}" already exists as a channel')

        d = {'name': name}
        d.update(metadata)
        self.channels_metadata[name] = d
        self.event_channels_data[name] = data

    def add_pos_channel(self, name: str, data: np.ndarray, metadata: dict):
        if name in self.channels_metadata:
            raise ValueError(f'name "{name}" already exists as a channel')

        d = {'name': name}
        d.update(metadata)
        self.channels_metadata[name] = d
        self.pos_channels_data[name] = data

    def add_zone_channel(self, name: str, shape: PaintShape, metadata: dict):
        if name in self.channels_metadata:
            raise ValueError(f'name "{name}" already exists as a channel')

        d = {'name': name, 'shape_config': shape.get_state()}
        d.update(metadata)
        self.channels_metadata[name] = d
        self.zone_channels_shapes[name] = shape


class AnalysisChannel:
    """compute_variables and compute_methods are per-class."""

    analysis_type: str = ''

    analysis_object: FileDataAnalysis = None

    name: str = ''

    metadata: Dict = {}

    _compute_variables_: Dict[str, str] = {}
    """Dict of variables names to their brief docs shown to the user.
    """

    _compute_variables_cache: Dict[str, Tuple[str, Type]] = {}

    _compute_methods_: Dict[str, str] = {}
    """Dict of compute method names to their brief docs shown to the user.

    The keys must exist as methods prefixed with ``compute_``.
    """

    _compute_methods_cache: Dict[str, Tuple[str, Type]] = {}

    _channel_creating_methods_: Dict[str, str] = {}
    """Dict for each method that returns a new channel, mapping to the type
    of channel created.
    """

    _special_arg_type_: Dict[str, str] = {}
    """Dict for each arg that accepts a special type, indicating what the arg
    means. E.g. whether it's a event channel name etc.
    """

    _compute_method_args_cache: Dict[str, Dict[str, Tuple[str, Type]]] = {}

    def __init__(self, name: str, analysis_object: FileDataAnalysis, **kwargs):
        self.analysis_object = analysis_object
        self.name = name
        self.metadata = analysis_object.channels_metadata[name]

    def compute_named_statistics(self, stat_options: Dict[str, dict]) -> List:
        res = []
        for stat, kwargs in stat_options.items():
            f = getattr(self, f'compute_{stat}')
            res.append(f(**kwargs))

        return res

    @classmethod
    def spec_get_compute_variables(cls) -> Dict[str, Tuple[str, Type]]:
        if cls.__dict__.get('_compute_variables_cache', None) is not None:
            return cls._compute_variables_cache

        cls._compute_variables_cache = variables = {}
        if '_compute_variables_' not in cls.__dict__:
            return variables

        annotations = cls.__annotations__
        for name, value in cls._compute_variables_.items():
            if name not in annotations:
                raise ValueError(
                    f'No type annotation found for variable {name} of {cls}')

            annotated_type = _filter_default(annotations[name])
            special_arg_type = cls.spec_get_special_arg_type()
            if name not in special_arg_type and \
                    annotated_type not in (int, float, str):
                raise ValueError(
                    f'Type {annotated_type} for {name} of {cls} is not one of '
                    f'(int, float, or str)')

            variables[name] = value, annotated_type
        return variables

    @classmethod
    def spec_get_compute_methods(cls) -> Dict[str, Tuple[str, Type]]:
        if cls.__dict__.get('_compute_methods_cache', None) is not None:
            return cls._compute_methods_cache

        cls._compute_methods_cache = methods = {}
        if '_compute_methods_' not in cls.__dict__:
            return methods

        for name, value in cls._compute_methods_.items():
            annotations = getattr(
                getattr(cls, f'compute_{name}'), '__annotations__', {})
            if 'return' not in annotations:
                raise ValueError(
                    f'No return type annotation found for {name} of {cls}')

            annotated_type = _filter_default(annotations['return'])
            channel_methods = cls.spec_get_channel_creating_methods()
            # if it doesn't create a channel and we don't recognize the type...
            if name not in channel_methods and \
                    annotated_type not in (int, float, str):
                raise ValueError(
                    f'Return type {annotated_type} for {name} of {cls} is not '
                    f'a understood type')

            methods[name] = value, annotated_type
        return methods

    @classmethod
    def spec_get_is_global_arg(cls, name: str) -> bool:
        """Returns whether the argument is a global argument for all methods
        of the class (i.e. it was defined as a class variable), or it is
        method specific with no global default value.
        """
        return name in cls.__dict__

    @classmethod
    def spec_get_channel_creating_methods(cls) -> Dict[str, str]:
        if '_channel_creating_methods_' not in cls.__dict__:
            return {}
        return cls._channel_creating_methods_

    @classmethod
    def spec_get_special_arg_type(cls) -> Dict[str, str]:
        if '_special_arg_type_' not in cls.__dict__:
            return {}
        return cls._special_arg_type_

    @classmethod
    def spec_get_compute_method_args(cls, name) -> Dict[str, Tuple[str, Type]]:
        if '_compute_method_args_cache' not in cls.__dict__:
            cls._compute_method_args_cache = {}
        cache = cls._compute_method_args_cache

        if name not in cache:
            variables = cache[name] = {}
            known_variables = cls.spec_get_compute_variables()

            f = getattr(cls, f'compute_{name}')
            annotations = getattr(f, '__annotations__', {})
            for var_name, var_type in annotations.items():
                if var_name in {'return', 'self'}:
                    continue
                if var_name not in known_variables:
                    raise ValueError(
                        f'Variable {var_name} of method {name} is not '
                        f'documented in the _compute_variables_ dictionary')

                doc, var_type_ = known_variables[var_name]
                var_type = _filter_default(var_type)
                if var_type != var_type_:
                    raise ValueError(
                        f'Variable {var_name} of method {name} was documented '
                        f'as both {var_type} and {var_type_}')

                variables[var_name] = doc, var_type

        return cache[name]

    def get_args(self, **kwargs) -> list:
        res = []
        for name, value in kwargs.items():
            if value is not default_value:
                res.append(value)
            else:
                res.append(getattr(self, name, None))
        return res

    def get_cache(self, prop: str, **kwargs) -> Tuple:
        args = tuple(self.get_args(**kwargs))
        prop_val = getattr(self, prop)

        if prop_val is not None and prop_val[1] == args:
            return prop_val[0], args
        return not_cached, args

    def get_cache_these_args(self, prop: str, **kwargs) -> Any:
        args = tuple(kwargs.values())
        prop_val = getattr(self, prop)

        if prop_val is not None and prop_val[1] == args:
            return prop_val[0]
        return not_cached


class TemporalAnalysisChannel(AnalysisChannel):

    data: np.ndarray = None

    timestamps: np.ndarray = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.timestamps = self.analysis_object.timestamps
        self.data = getattr(
            self.analysis_object,
            f'{self.analysis_type}_channels_data')[self.name]

    @staticmethod
    def _get_active_intervals(
            data: np.ndarray, timestamps: np.ndarray,
            start: Optional[float] = None,
            end: Optional[float] = None
    ) -> Dict[str, np.ndarray]:
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
    def _compute_delay_to_first(
            timestamps: np.ndarray, intervals: np.ndarray) -> float:
        return intervals[0, 0] - timestamps[0] if intervals.shape[0] else -1.

    @staticmethod
    def _compute_scored_duration(timestamps: np.ndarray) -> float:
        return timestamps[-1] - timestamps[0] if timestamps.shape[0] else 0.

    @staticmethod
    def _compute_event_count(intervals: np.ndarray) -> int:
        return intervals.shape[0]


class EventAnalysisChannel(TemporalAnalysisChannel):

    analysis_type: str = 'event'

    _active_duration: Tuple[float, Tuple] = None

    _delay_to_first: Tuple[float, Tuple] = None

    _scored_duration: Tuple[float, Tuple] = None

    _event_count: Tuple[int, Tuple] = None

    _active_interval: Tuple[Dict[str, np.ndarray], Tuple] = None

    start: float = None

    end: float = None

    event_channels: List[str]

    _compute_variables_: Dict[str, str] = {
        'start': 'The start time in video time, or none if to start from '
                 'the beginning of the video',
        'end': 'The end time in video time, or none if to end at '
                 'the end of the video',
        'event_channels': 'The event channels',
    }

    _compute_methods_: Dict[str, str] = {
        'active_duration':
            'The total duration in seconds that the event was active',
        'delay_to_first':
            'The delay relative to the start of the video of the first '
            'occurrence of the event',
        'scored_duration':
            'The duration of the video or the section that was analyzed, if '
            'only part of the data is exported',
        'event_count': 'The number of time the event occurred',
        'combine_events_and':
            'Creates a new event channel from the given event channel, where '
            'it is active if "all" the channels are active',
        'combine_events_or':
            'Creates a new event channel from the given event channel, where '
            'it is active if "any" the channels are active',
    }

    _channel_creating_methods_: Dict[str, str] = {
        'combine_events_and': 'event',
        'combine_events_or': 'event',
    }

    _special_arg_type_: Dict[str, str] = {'event_channels': 'event'}

    def get_active_intervals(
            self, start: Optional[float] = None,
            end: Optional[float] = None) -> Dict[str, np.ndarray]:
        val = self.get_cache_these_args(
            '_active_interval', start=start, end=end)
        if val is not not_cached:
            return val

        intervals = self._get_active_intervals(
            self.data, self.timestamps, start=start, end=end)
        self._active_interval = intervals, (start, end)
        return intervals

    def compute_active_duration(
            self, start: DefaultFloat = default_value,
            end: DefaultFloat = default_value) -> float:
        val, (start, end) = self.get_cache(
            '_active_duration', start=start, end=end)
        if val is not not_cached:
            return val

        intervals = self.get_active_intervals(start, end)['intervals']
        val = self._compute_active_duration(intervals)
        self._active_duration = val, (start, end)
        return val

    def compute_delay_to_first(
            self, start: DefaultFloat = default_value,
            end: DefaultFloat = default_value) -> float:
        val, (start, end) = self.get_cache(
            '_delay_to_first', start=start, end=end)
        if val is not not_cached:
            return val

        active_intervals = self.get_active_intervals(start, end)
        val = self._compute_delay_to_first(
            active_intervals['timestamps'], active_intervals['intervals'])
        self._delay_to_first = val, (start, end)
        return val

    def compute_scored_duration(
            self, start: DefaultFloat = default_value,
            end: DefaultFloat = default_value) -> float:
        val, (start, end) = self.get_cache(
            '_scored_duration', start=start, end=end)
        if val is not not_cached:
            return val

        timestamps = self.get_active_intervals(start, end)['timestamps']
        val = self._compute_scored_duration(timestamps)
        self._scored_duration = val, (start, end)
        return val

    def compute_event_count(
            self, start: DefaultFloat = default_value,
            end: DefaultFloat = default_value) -> int:
        val, (start, end) = self.get_cache(
            '_event_count', start=start, end=end)
        if val is not not_cached:
            return val

        intervals = self.get_active_intervals(start, end)['intervals']
        val = self._compute_event_count(intervals)
        self._event_count = val, (start, end)
        return val

    def compute_combine_events_and(
            self, event_channels: List[str]) -> Tuple[np.ndarray, dict]:
        channels_data = self.analysis_object.event_channels_data

        arr = [channels_data[name] for name in event_channels]
        arr.append(self.data)

        return np.logical_and.reduce(arr, axis=0), {}

    def compute_combine_events_or(
            self, event_channels: List[str]) -> Tuple[np.ndarray, dict]:
        channels_data = self.analysis_object.event_channels_data

        arr = [channels_data[name] for name in event_channels]
        arr.append(self.data)

        return np.logical_or.reduce(arr, axis=0), {}


class PosAnalysisChannel(TemporalAnalysisChannel):

    analysis_type: str = 'pos'

    _mean_center_distance: Tuple[float, Tuple] = None

    _distance_traveled: Tuple[float, Tuple] = None

    _mean_speed: Tuple[float, Tuple] = None

    _active_interval: Tuple[Dict[str, np.ndarray], Tuple] = None

    _colliders: Dict[str, Union[Collide2DPoly, CollideEllipse]]

    start: float = None

    end: float = None

    event_channel: str

    event_channels: List[str]

    zone_channel: str

    zone_channels: List[str]

    _compute_variables_: Dict[str, str] = {
        'start': 'The start time in video time, or none if to start from '
                 'the beginning of the video',
        'end': 'The end time in video time, or none if to end at '
                 'the end of the video',
        'event_channel': 'The event channel',
        'event_channels': 'The event channels',
        'zone_channel': 'The zone channel',
        'zone_channels': 'The zone channels',
    }

    _compute_methods_: Dict[str, str] = {
        'event_from_pos':
            'Creates a new event channel from the pos channel, where '
            'it is active for time t if the channel was coded with a position'
            ' for time t',
        'pos_in_any_zone':
            'Creates a new event channel where it is active for time t if the '
            'position is in any of the given zones for time t',
        'mean_center_distance':
            'The mean distance of the channel to the zone, while the event '
            'channel is active, if an event channel is selected',
        'distance_traveled':
            'The total distance the channel traveled in pixels while the '
            'event, if given, is active',
        'mean_speed':
            'The mean speed of the channel in pixels per second while the '
            'event, if given, is active',
    }

    _channel_creating_methods_: Dict[str, str] = {
        'event_from_pos': 'event', 'pos_in_any_zone': 'event'}

    _special_arg_type_: Dict[str, str] = {
        'event_channel': 'event', 'event_channels': 'event',
        'zone_channel': 'zone', 'zone_channels': 'zone'}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._colliders = {}

    def get_collider(
            self, zone_name: str) -> Union[Collide2DPoly, CollideEllipse]:
        if zone_name not in self._colliders:
            shape = self.analysis_object.zone_channels_shapes[zone_name]
            self._colliders[zone_name] = \
                ZoneAnalysisChannel.collider_from_shape(shape)

        return self._colliders[zone_name]

    def get_active_intervals(
            self, event_channel: Optional[str] = None,
            start: Optional[float] = None,
            end: Optional[float] = None) -> Dict[str, np.ndarray]:
        val = self.get_cache_these_args(
            '_active_interval', event_channel=event_channel, start=start,
            end=end)
        if val is not not_cached:
            return val

        data = self.data[:, 0] != -1
        if event_channel:
            data = np.logical_and(
                data, self.analysis_object.event_channels_data[event_channel])

        intervals = self._get_active_intervals(
            data, self.timestamps, start=start, end=end)
        self._active_interval = intervals, (start, end)
        return intervals

    def compute_event_from_pos(
            self, event_channels: List[str]) -> Tuple[np.ndarray, dict]:
        channels_data = self.analysis_object.event_channels_data

        arr = [channels_data[name] for name in event_channels]
        arr.append(self.data[:, 0] != -1)

        return np.logical_or.reduce(arr, axis=0), {}

    def compute_pos_in_any_zone(
            self, zone_channels: List[str]) -> Tuple[np.ndarray, dict]:
        arr = []
        valid_points = self.data[:, 0] != -1
        points = self.data[valid_points, :].tolist()
        for zone in zone_channels:
            collider = self.get_collider(zone)
            arr.append(collider.collide_points(points))

        valid_points[valid_points] = np.logical_or.reduce(arr, axis=0)

        return valid_points, {}

    def compute_mean_center_distance(
            self, zone_channel: DefaultStr,
            event_channel: DefaultStr = default_value,
            start: DefaultFloat = default_value,
            end: DefaultFloat = default_value) -> float:
        val, (zone_channel, event_channel, start, end) = self.get_cache(
            '_mean_center_distance', zone_channel=zone_channel,
            event_channel=event_channel, start=start, end=end)
        if val is not not_cached:
            return val

        intervals = self.get_active_intervals(event_channel, start, end)
        collider = self.get_collider(zone_channel)

        data = self.data[intervals['start']:intervals['end'], :]
        data = data[intervals['mask'], :] - collider.get_centroid()
        val = float(np.mean(numpy.linalg.norm(data, axis=1)))

        self._mean_center_distance = val, (
            zone_channel, event_channel, start, end)
        return val

    def compute_distance_traveled(
            self, event_channel: DefaultStr = default_value,
            start: DefaultFloat = default_value,
            end: DefaultFloat = default_value) -> float:
        val, (event_channel, start, end) = self.get_cache(
            '_distance_traveled', event_channel=event_channel, start=start,
            end=end)
        if val is not not_cached:
            return val

        intervals = self.get_active_intervals(event_channel, start, end)
        indices = intervals['indices']
        data = self.data[intervals['start']:intervals['end'], :]

        val = 0
        for s, e in indices:
            val += np.sum(
                np.linalg.norm(data[s + 1:e + 1, :] - data[s:e, :], axis=1))
        val = float(val)

        self._distance_traveled = val, (event_channel, start, end)
        return val

    def compute_mean_speed(
            self, event_channel: DefaultStr = default_value,
            start: DefaultFloat = default_value,
            end: DefaultFloat = default_value) -> float:
        val, (event_channel, start, end) = self.get_cache(
            '_mean_speed', event_channel=event_channel, start=start,
            end=end)
        if val is not not_cached:
            return val

        intervals = self.get_active_intervals(event_channel, start, end)
        indices = intervals['indices']
        interval_times = intervals['intervals']
        data = self.data[intervals['start']:intervals['end'], :]

        dist = 0
        for s, e in indices:
            dist += np.sum(
                np.linalg.norm(data[s + 1:e + 1, :] - data[s:e, :], axis=1))

        dt = np.sum(interval_times[:, 1] - interval_times[:, 0])
        val = 0.
        if dt:
            val = float(dist / dt)

        self._mean_speed = val, (event_channel, start, end)
        return val


class ZoneAnalysisChannel(AnalysisChannel):

    analysis_type: str = 'zone'

    shape: PaintShape = None

    _collider = None

    _compute_methods_: Dict[str, str] = {
        'area': 'Computes the area of the zone in pixels',
        'centroid': 'Computes the centroid of the zone in pixels',
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.shape = self.analysis_object.zone_channels_shapes[self.name]

    @staticmethod
    def collider_from_shape(
            shape: PaintShape) -> Union[Collide2DPoly, CollideEllipse]:
        if isinstance(shape, PaintPolygon):
            return Collide2DPoly(points=shape.points, cache=True)
        elif isinstance(shape, PaintCircle):
            x, y = shape.center
            r = shape.radius
            return CollideEllipse(x=x, y=y, rx=r, ry=r)
        elif isinstance(shape, PaintEllipse):
            x, y = shape.center
            rx, ry = shape.radius_x, shape.radius_y
            return CollideEllipse(
                x=x, y=y, rx=rx, ry=ry, angle=shape.angle)
        elif isinstance(shape, PaintPoint):
            x, y = shape.position
            return CollideEllipse(x=x, y=y, rx=1, ry=1)
        else:
            assert False

    @property
    def collider(self):
        collider = self._collider
        if collider is not None:
            return collider

        self._collider = self.collider_from_shape(self.shape)
        return self._collider

    def compute_area(self) -> float:
        return self.collider.get_area()

    def compute_centroid(self) -> float:
        return self.collider.get_centroid()


AnalysisFactory.register_analysis_class(EventAnalysisChannel)
AnalysisFactory.register_analysis_class(PosAnalysisChannel)
AnalysisFactory.register_analysis_class(ZoneAnalysisChannel)
