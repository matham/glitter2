"""CleverSys Import
===================

"""

import re
import os
from collections import defaultdict

__all__ = ('read_clever_sys_file', 'map_frames_to_timestamps')

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

_clever_sys_area_regex = re.compile(
    'Area ([0-9.]+):[\n\r]+'
    r'(.+): Zones\(([0-9,]*)\)'
)


def _parse_clever_sys_zones(zone_items, height):
    zones = {}
    for zone in zone_items:
        m = re.match(_clever_sys_zone_circle_3p_regex, zone)
        if m is not None:
            zones[int(m.group(1))] = {
                'shape_class': 'circle', 'name': 'Channel',
                'center': [float(m.group(2)), height - float(m.group(3))],
                'radius': float(m.group(4))}
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
            zones[int(m.group(1))] = {
                'shape_class': 'polygon', 'name': 'Channel',
                'points': [coord for point in points for coord in point],
                'selection_point': points[0]}
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


def map_frames_to_timestamps(timestamps, frame_rate, min_frame, max_frame):
    n = len(timestamps)
    mapping = defaultdict(list)
    half_period = 1 / (frame_rate * 2)

    start_t = min_frame / frame_rate - half_period
    t_index = 0
    while t_index < n and timestamps[t_index] < start_t:
        t_index += 1

    for frame in range(min_frame, max_frame + 1):
        end_t = frame / frame_rate + half_period
        while t_index < n and timestamps[t_index] < end_t:
            mapping[frame].append(timestamps[t_index])
            t_index += 1

    return mapping
