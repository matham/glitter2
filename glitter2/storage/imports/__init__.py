"""Data import
==============
"""

from typing import List, Dict, Union
import numpy as np
from collections import defaultdict

__all__ = ('map_frame_rate_to_timestamps', 'map_timestamps_to_timestamps')


def map_frame_rate_to_timestamps(
        timestamps: Union[List[float], np.ndarray], frame_rate: float,
        min_frame: int, max_frame: int) -> Dict[int, List[float]]:
    """Maps video frames given as integer multiples of a frame rate to a
    monotonic list of timestamps.

    E.g. given a frame rate of ``10``, a start frame number of ``5`` and a end
    frame number of ``10``, and a list of timestamps of
    ``[.1, .2, .3, .4, .5, .58, .6, .66, .7, .9, 1.0, 1.1]``, it returns::

        >>> map_frame_rate_to_timestamps(\
            [.1, .2, .3, .4, .5, .58, .6, .66, .7, .74, .9, 1.0, 1.1], \
            10., 5, 10)
        {5: [0.5],
         6: [0.58, 0.6],
         7: [0.66, 0.7, 0.74],
         9: [0.9],
         10: [1.0]
        }

    Target timestamps outside the first/last frame time
    (with some fuzzy factor) are not assigned to any frames.

    :param timestamps: The sorted list of timestamps to be mapped to. It is
        assumed to be continuous with no gaps (i.e. all value between
        start and end of timestamps can be coded).
    :param frame_rate: The frame rate used to convert the frame numbers into
        estimated timestamps.
    :param min_frame: The frame number of the start frame (as integer multiple
        of the frame rate).
    :param max_frame: The frame number of the end frame (as integer multiple
        of the frame rate).
    :return: The mapping.
    """
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


def map_timestamps_to_timestamps(
        src_timestamps: Union[List[float], np.ndarray],
        target_timestamps: Union[List[float], np.ndarray]
) -> Dict[float, List[float]]:
    """Maps a continuous list of timestamps into another list of timestamps so
    that given an event occurring in the source timestamps, we can translate
    that event's occurrence into target timestamps.

    E.g.::

        >>> target_timestamps =  \
            [.1, .2, .3, .4, .5, .58, .6, .66, .7, .9, 1.0, 1.1]
        >>> source_timestamps = [.1, .2, .4, .5, .7, .8, .96]
        >>> map_timestamps_to_timestamps(source_timestamps, target_timestamps)
        {0.1: [0.1],
         0.2: [0.2, 0.3],
         0.4: [0.4],
         0.5: [0.5, 0.58],
         0.7: [0.6, 0.66, 0.7],
         0.96: [0.9, 1.0]
        }

    Target timestamps outside the first/last timestamp of the source timestamps
    (with some fuzzy factor) are not assigned to any source timestamps.

    :param src_timestamps: The sorted list of timestamps to map from. It is
        assumed to be continuous with no gaps (i.e. all value between
        start and end of timestamps can be coded).
    :param target_timestamps: The sorted list of timestamps to be mapped to.
        It is assumed to be continuous with no gaps (i.e. all value between
        start and end of timestamps can be coded).
    :return: The mapping.
    """
    if len(src_timestamps) <= 2 or len(target_timestamps) <= 2:
        raise ValueError('Timestamps list too short')

    mapping = defaultdict(list)
    n = len(target_timestamps)

    center_points = {}
    for s, e in zip(src_timestamps[:-1], src_timestamps[1:]):
        center_points[s] = (s + e) / 2
    # the last timestamp uses the previous frame rate for the interval
    half_interval = (src_timestamps[-1] - src_timestamps[-2]) / 2
    center_points[src_timestamps[-1]] = src_timestamps[-1] + half_interval

    # find the first timestamp
    half_interval = (src_timestamps[1] - src_timestamps[0]) / 2
    start_t = src_timestamps[0] - half_interval
    t_index = 0
    while t_index < n and target_timestamps[t_index] < start_t:
        t_index += 1

    # each src timestamp covers a interval, add all the target timestamps in
    # that interval to the map for the src timestamp
    for t, end_t in center_points.items():
        while t_index < n and target_timestamps[t_index] < end_t:
            mapping[t].append(target_timestamps[t_index])
            t_index += 1

    return mapping
