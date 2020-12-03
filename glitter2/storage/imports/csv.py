"""CSV import
=============

"""
import csv
import numpy as np

from kivy_garden.painter import PaintCircle, PaintPolygon

from glitter2.storage.imports import map_timestamps_to_timestamps
from glitter2.utils import fix_name
from glitter2.storage.data_file import DataFile


__all__ = ('read_csv', 'add_csv_data_to_file')


def _parse_pos(header, data, i, width, height):
    name = header[i][4:-2]
    if not header[i].endswith(':x') or len(header) - 1 == i or \
            header[i + 1] != f'pos:{name}:y':
        raise ValueError(
            f'Expected two columns named "pos:{name}:x" and '
            f'"pos:{name}:y" at columns ({i}, {i + 1})')

    state = np.array([data[i], data[i + 1]], dtype=np.float).T
    return name, state


def _parse_zone(header, data, i, width, height):
    name = header[i][5:-9]
    if not header[i].endswith(':property') or len(header) - 1 == i or \
            header[i + 1] != f'zone:{name}:value':
        raise ValueError(
            f'Expected two columns named "zone:{name}:property" and '
            f'"zone:{name}:value" at columns ({i}, {i + 1})')

    metadata = {key: value for key, value in zip(data[i], data[i + 1])}
    if 'type' not in metadata:
        raise ValueError(f'Expected to find a shape property for {name}')
    shape_type = metadata['type']

    if shape_type == 'polygon':
        if 'points' not in metadata:
            raise ValueError(f'Expected points property for channel {name}')

        points = [float(p.strip()) for p in metadata['points'].split(',')]
        if len(points) % 2:
            raise ValueError(
                f'Expected even number of points for channel {name}')
        if len(points) < 6:
            raise ValueError(
                f'Expected at least 6 points for channel {name}')

        # flip y-axis
        for i in range(0, len(points), 2):
            points[i] = height - points[i]

        shape = PaintPolygon.create_shape(points)
    elif shape_type == 'circle':
        if 'center' not in metadata or 'radius' not in metadata:
            raise ValueError(
                f'Expected center and radius property for channel {name}')

        radius = float(metadata['radius'])
        center = [float(p.strip()) for p in metadata['center'].split(',')]
        if not len(center) == 2:
            raise ValueError(
                f'Expected center to be tuple of "x, y" for channel {name}')

        # flip y-axis
        center[1] = height - center[1]
        shape = PaintCircle.create_shape(center, radius)
    else:
        raise ValueError(
            f'Unrecognized shape type "{shape_type}" for channel "{name}"')

    return name, shape


def _parse_csv(rows):
    header = rows[0]
    done = [False, ] * len(header)
    data = [[] for _ in header]

    for row in rows[1:]:
        for col, value in enumerate(row):
            if done[col]:
                if value:
                    raise ValueError(
                        f'Got {value} for column {header[col]} after column '
                        f'was done')
                continue

            if not value:
                done[col] = True
                continue

            data[col].append(value)
    return header, data


def read_csv(filename: str):
    with open(filename, encoding='utf-8-sig') as fh:
        header, data = _parse_csv(list(csv.reader(fh)))

    first_cols = ['metadata', 'value', 'timestamps']
    if header[:3] != first_cols:
        raise ValueError(
            f'Expected the first three columns to be labeled {first_cols}')

    metadata = {key: value for key, value in zip(data[0], data[1])}
    for key in ('filename', 'video_width', 'video_height'):
        if key not in metadata:
            raise ValueError(f'Could not find {key} in the metadata')
    width = metadata['video_width'] = float(metadata['video_width'])
    height = metadata['video_height'] = float(metadata['video_height'])
    metadata['pixels_per_meter'] = float(metadata['pixels_per_meter'])
    if 'saw_all_timestamps' in metadata:
        metadata['saw_all_timestamps'] = \
            metadata['saw_all_timestamps'] in ('true', 'TRUE', 'True')

    timestamps = np.array(data[2], dtype=np.float64)

    events = {}
    pos = {}
    zones = {}

    i = 3
    while i < len(header):
        if header[i].startswith('event:'):
            state = np.array(data[i], dtype=np.uint8)
            name = fix_name(header[i][6:], events, pos, zones)
            events[name] = state
            i += 1

        elif header[i].startswith('pos:'):
            name, state = _parse_pos(header, data, i, width, height)
            name = fix_name(name, events, pos, zones)
            pos[name] = state
            i += 2

        elif header[i].startswith('zone:'):
            name, shape = _parse_zone(header, data, i, width, height)
            name = fix_name(name, events, pos, zones)
            zones[name] = shape
            i += 2
        elif not header[i]:
            i += 1
        else:
            raise ValueError(f'Unrecognized column type with name {header[i]}')

    return metadata, timestamps, events, pos, zones


def _set_data_from_mapped_video_timestamps(
        data_file: DataFile, timestamps, events, pos, names):
    assert data_file.saw_all_timestamps
    timestamps_mapping = map_timestamps_to_timestamps(
        timestamps, np.asarray(data_file.timestamps))

    index_map = data_file.timestamp_data_map
    n = len(data_file.timestamps)

    for channel_type, channels in [('event', events), ('pos', pos)]:
        if channel_type == 'event':
            data_arr = np.zeros(n, dtype=np.uint8)
        else:
            data_arr = np.zeros((n, 2))

        for name, data in channels.items():
            name = fix_name(name, names)
            names.add(name)

            channel = data_file.create_channel(channel_type)
            channel.channel_config_dict = {'name': name}

            mask = np.zeros(n, dtype=np.bool)
            for i in range(len(timestamps)):
                t = timestamps[i]
                if t not in timestamps_mapping:
                    continue

                for val in timestamps_mapping[t]:
                    _, idx = index_map[val]
                    mask[idx] = True
                    data_arr[idx] = data[i]

            channel.set_channel_data(data_arr[mask], mask)


def _set_data_from_src_timestamps(data_file: DataFile, events, pos, names):
    assert data_file.saw_all_timestamps

    for channel_type, channels in [('event', events), ('pos', pos)]:
        for name, data in channels.items():
            name = fix_name(name, names)
            names.add(name)

            channel = data_file.create_channel(channel_type)
            channel.channel_config_dict = {'name': name}
            channel.set_channel_data(data)


def add_csv_data_to_file(
        data_file: DataFile, metadata, timestamps, events, pos, zones,
        use_src_timestamps):
    pixels_per_meter = metadata.get('pixels_per_meter', 0)
    if pixels_per_meter:
        data_file.set_pixels_per_meter(pixels_per_meter)

    names = set()
    for channels in (
            data_file.event_channels, data_file.pos_channels,
            data_file.zone_channels):
        for channel in channels.values():
            names.add(channel.channel_config_dict['name'])

    if use_src_timestamps:
        _set_data_from_src_timestamps(data_file, events, pos, names)
    else:
        _set_data_from_mapped_video_timestamps(
            data_file, timestamps, events, pos, names)

    for name, shape in zones.items():
        name = fix_name(name, names)
        names.add(name)

        channel = data_file.create_channel('zone')
        channel.channel_config_dict = {
            'shape_config': shape.get_state(), 'name': name}
