"""CleverSys Import
===================

"""

import re
import numpy as np
import os

from kivy_garden.painter import PaintCircle, PaintPolygon

from glitter2.utils import fix_name
from glitter2.storage.imports import map_frame_rate_to_timestamps
from glitter2.storage.data_file import DataFile

__all__ = (
    'read_clever_sys_file', 'compute_calibration',
    'add_clever_sys_data_to_file')

_clever_sys_regex = [
    re.compile(r'^Video\s+File\s*:\s*(?P<video_file>.+?)\s*$'),
    re.compile(r'^Background\s*:\s*(?P<background_file>.+?)\s*$'),
    re.compile(r'^Video\s+Width\s*:\s*(?P<width>\d+)\s*$'),
    re.compile(r'^Video\s+Height\s*:\s*(?P<height>\d+)\s*$'),
    re.compile(r'^Frame\s+Rate\s*:\s*(?P<rate>[\d.]+)\s*$'),
    re.compile(r'^Frame\s+From\s*:\s*(?P<from>\d+)\s*$'),
    re.compile(r'^Frame\s+To\s*:\s*(?P<to>\d+)\s*$'),
    re.compile(r'^Begin\s+Time\s*:\s*(?P<begin>[\d.]+)\(s\)\s*$'),
    re.compile(r'^End\s+Time\s*:\s*(?P<end>[\d.]+)\(s\)\s*$'),
    re.compile(
        r'^Format\s*:\s*FrameNum\s*CenterX\(mm\)\s*CenterY\(mm\)\s*'
        r'NoseX\(mm\)\s*NoseY\(mm\).+$'),
]

_clever_sys_arena_regex = re.compile(
    'Calibration Martrix:[\n\r]+'
    '([0-9.]+) +([0-9.-]+) +([0-9.-]+)[\n\r]+'
    '([0-9.-]+) +([0-9.]+) +([0-9.-]+).+'
    'ZoneNum += +([0-9.]+)[\n\r]+'
    '(.+)'
    'AreaNum += +([0-9.]+)[\n\r]+'
    '(.+)',
    re.DOTALL
)

_clever_sys_zone_polygon_regex = re.compile(
    'Zone ([0-9.]+):[\n\r]+'
    'Type Polygon:[\n\r]+'
    'Number of Vertex: ([0-9.]+)[\n\r]+'
    'V([V0-9, ()]+)[\n\r ]*'
)

_clever_sys_polygon_vertices_regex = re.compile(
    r'\(([0-9.]+), ([0-9.]+)\)'
)

_clever_sys_zone_circle_3p_regex = re.compile(
    'Zone ([0-9.]+):[\n\r]+'
    'Type Circle\\(Three Arc Points\\):[\n\r]+'
    'Arc Points.+[\n\r]+'
    r'Center\(([0-9.]+), ([0-9.]+)\) Radius\(([0-9.]+)\)'
)

_clever_sys_zone_circle_regex = re.compile(
    'Zone ([0-9.]+):[\n\r]+'
    'Type Circle\\(Center-Radius\\):[\n\r]+'
    r'Center\(([0-9.]+), ([0-9.]+)\) Radius\(([0-9.]+)\)'
)

_clever_sys_area_regex = re.compile(
    'Area ([0-9.]+):[\n\r]+'
    r'(.+): Zones\(([0-9,]*)\)'
)


def _parse_clever_sys_zones(zone_items, height):
    zones = {}
    for zone in zone_items:
        m = re.match(_clever_sys_zone_circle_3p_regex, zone)
        if m is not None:
            shape = PaintCircle.create_shape(
                [float(m.group(2)), height - float(m.group(3))],
                float(m.group(4)))
            zones[int(m.group(1))] = {
                'shape_config': shape.get_state(), 'name': 'Channel'}
            continue

        m = re.match(_clever_sys_zone_circle_regex, zone)
        if m is not None:
            shape = PaintCircle.create_shape(
                [float(m.group(2)), height - float(m.group(3))],
                float(m.group(4)))
            zones[int(m.group(1))] = {
                'shape_config': shape.get_state(), 'name': 'Channel'}
            continue

        m = re.match(_clever_sys_zone_polygon_regex, zone)
        if m is not None:
            points = re.findall(_clever_sys_polygon_vertices_regex, m.group(3))
            points = [list(map(float, p)) for p in points]
            n = int(m.group(2))

            if n != len(points):
                raise ValueError(
                    f'Unable to parse arena file. Expected {n} points '
                    f'but got {len(points)}')
            if n < 3:
                continue

            points = [[p[0], height - p[1]] for p in points]
            shape = PaintPolygon.create_shape(
                [coord for point in points for coord in point],
                points[0])
            zones[int(m.group(1))] = {
                'shape_config': shape.get_state(), 'name': 'Channel'}
            continue

        raise ValueError(
            f'Unable to parse arena file, zone type "{zone}" not recognized')

    return zones


def _parse_clever_sys_areas(area_items, zones):
    for areas in area_items:
        m = re.match(_clever_sys_area_regex, areas)
        if m is None:
            raise ValueError(f'Unable to parse arena file, zone type "{areas}" '
                             f'not recognized')

        n = int(m.group(1))

        zone_ids = [int(z) for z in m.group(3).split(',') if z]
        for zone in zone_ids:
            zones[zone]['name'] = m.group(2)

    return zones.values()


def _parse_clever_sys_arena_file(fh, height):
    data = fh.read()
    calibration = None
    zones = []
    arenas = [
        s.strip() for s in re.split('Arena [0-9]+:', data) if s.strip()]

    if not arenas:
        return calibration, zones

    m = re.match(_clever_sys_arena_regex, arenas[0])
    if m is None:
        return calibration, zones

    calibration = [
        list(map(float, m.groups()[:3])),
        list(map(float, m.groups()[3:6])),
    ]

    num_zones = int(m.group(7))
    zone_items = [
        s.strip() for s in re.split('[\n\r][\n\r]', m.group(8).strip())
        if s.strip()]
    if num_zones != len(zone_items):
        raise ValueError(
            f'Unable to parse arena file. Expected {num_zones} zones '
            f'but got {len(zone_items)}')

    num_areas = int(m.group(9))
    area_items = [
        s.strip() for s in re.split('[\n\r][\n\r]', m.group(10).strip())
        if s.strip()]
    if num_areas != len(area_items):
        raise ValueError(
            f'Unable to parse arena file. Expected {num_areas} areas '
            f'but got {len(area_items)}')

    zones = _parse_clever_sys_zones(zone_items, height)
    zones = _parse_clever_sys_areas(area_items, zones)
    return calibration, zones


def _parse_clever_sys_file(fh):
    metadata = {}
    data = []
    match = re.match
    re_split = re.split

    regex = _clever_sys_regex[::-1]
    current_re = regex.pop()

    # read metadata
    while True:
        line = fh.readline()
        if not line:
            break

        m = match(current_re, line)
        if m is not None:
            metadata.update(m.groupdict())
            if not regex:
                break
            current_re = regex.pop()

    for key in ('width', 'height', 'from', 'to'):
        metadata[key] = int(metadata[key])
    for key in ('begin', 'end', 'rate'):
        metadata[key] = float(metadata[key])

    start_frame = metadata['from']
    end_frame = metadata['to']
    h = metadata['height']

    # now read data
    while True:
        line = fh.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        item = re_split(r'\s+', line, maxsplit=11)
        if len(item) < 12:
            raise ValueError(f'Could not parse line "{line}"')
        frame, center_x, center_y, nose_x, nose_y, *_ = item
        data.append((
            int(frame), float(center_x), h - float(center_y),
            float(nose_x), h - float(nose_y)
        ))

    if not data:
        raise ValueError('No frame data in the file')
    if start_frame != data[0][0]:
        raise ValueError(
            f'Expected first frame to be "{start_frame}", but '
            f'got "{data[0][0]}" instead')
    if end_frame != data[-1][0]:
        raise ValueError(
            f'Expected last frame to be "{end_frame}", but '
            f'got "{data[-1][0]}" instead')

    return data, metadata


def read_clever_sys_file(filename):
    zones = []
    calibration = None

    clever_sys_filename = str(filename)

    with open(clever_sys_filename, 'r') as fh:
        data, metadata = _parse_clever_sys_file(fh)

    if clever_sys_filename.endswith('TCR.TXT'):
        arena_filename = clever_sys_filename[:-7] + 'TCG.TXT'
        if os.path.exists(arena_filename):
            with open(arena_filename, 'r') as fh:
                calibration, zones = _parse_clever_sys_arena_file(
                    fh, metadata['height'])

    return data, metadata, zones, calibration


def compute_calibration(calibration):
    (a, b, c), (d, e, f) = calibration
    if b or c or d or f or a != e:
        raise ValueError(f'Cannot parse calibration {calibration}')
    calibration_set = a != 1
    pixels_per_meter = 1000 / a

    return calibration_set, pixels_per_meter


def add_clever_sys_data_to_file(
        data_file: DataFile, data, video_metadata, zones, calibration):
    calibration_set, pixels_per_meter = compute_calibration(calibration)
    background_file = video_metadata['background_file']

    # set pixels_per_meter
    if not data_file.pixels_per_meter and calibration_set:
        data_file.set_pixels_per_meter(pixels_per_meter)

    # get the clever sys timing mapping
    rate = video_metadata['rate']
    estimated_start = video_metadata['from'] / rate
    assert estimated_start - 1 <= video_metadata['begin'] \
        <= estimated_start + 1
    estimated_end = video_metadata['to'] / rate
    assert estimated_end - 1 <= video_metadata['end'] \
        <= estimated_end + 1

    timestamps = np.asarray(data_file.timestamps)

    timestamps_mapping = map_frame_rate_to_timestamps(
        timestamps, rate, video_metadata['from'], video_metadata['to'])

    # track names to not have duplicates
    names = set()
    for channels in (
            data_file.event_channels, data_file.pos_channels,
            data_file.zone_channels):
        for channel in channels.values():
            names.add(channel.channel_config_dict['name'])

    center_channel = data_file.create_channel('pos')
    name = fix_name('animal_center', names)
    center_channel.channel_config_dict = {'name': name}
    names.add(name)

    nose_channel = data_file.create_channel('pos')
    name = fix_name('animal_nose', names)
    nose_channel.channel_config_dict = {'name': name}
    names.add(name)

    index_map = data_file.timestamp_data_map
    mask = np.zeros(len(timestamps), dtype=np.bool)
    center = np.zeros((len(timestamps), 2))
    nose = np.zeros((len(timestamps), 2))

    for frame, center_x, center_y, nose_x, nose_y in data:
        if frame not in timestamps_mapping:
            continue

        for t in timestamps_mapping[frame]:
            _, i = index_map[t]
            mask[i] = True
            center[i, :] = center_x, center_y
            nose[i, :] = nose_x, nose_y

    center_channel.set_channel_data(center[mask, :], mask)
    nose_channel.set_channel_data(nose[mask, :], mask)

    for zone in zones:
        channel = data_file.create_channel('zone')
        name = zone['name'] = fix_name(zone['name'], names)
        channel.channel_config_dict = zone
        names.add(name)
