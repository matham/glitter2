import nixio as nix
import numpy as np
from typing import Dict, List
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

    event_channels: List['EventAnalysis'] = []

    pos_channels: List['PosAnalysis'] = []

    def __init__(self, filename, **kwargs):
        super(FileDataAnalysis, self).__init__(**kwargs)
        self.nix_file = nix.File.open(filename, nix.FileMode.ReadOnly)
        self.data_file = DataFile(nix_file=self.nix_file)
        self.filename = filename

    def load_data(self, ignore_unseen_frames=False):
        data_file = self.data_file
        data_file.open_file()

        self.metadata = metadata = data_file.get_video_metadata()
        metadata['saw_all_timestamps'] = data_file.saw_all_timestamps
        metadata['saw_first_timestamp'] = data_file._saw_first_timestamp
        metadata['saw_last_timestamp'] = data_file._saw_last_timestamp
        metadata['glitter2_version'] = data_file.glitter2_version
        metadata['ffpyplayer_version'] = data_file.ffpyplayer_version

        data_arrays_order = []
        if len(data_file.timestamps_arrays) > 1:
            if not ignore_unseen_frames:
                raise TypeError(
                    'Not all frames seen for "{}"'.format(self.filename))
        else:
            self.timestamps = np.array(data_file.timestamps)

        event_channels = self.event_channels = []
        for _, channel in _sort_dict(data_file.event_channels):
            analysis_channel = EventAnalysis(
                data_channel=channel, timestamps=self.timestamps,
                data_arrays_order=data_arrays_order)
            event_channels.append(analysis_channel)
            analysis_channel.load_data()

        pos_channels = self.pos_channels = []
        for _, channel in _sort_dict(data_file.pos_channels):
            analysis_channel = PosAnalysis(
                data_channel=channel, timestamps=self.timestamps,
                data_arrays_order=data_arrays_order)
            pos_channels.append(analysis_channel)
            analysis_channel.load_data()

    def compute_results(self):
        for channel in self.event_channels:
            channel.compute_statistics()

    def export_raw_data_to_excel(self, filename):
        excel_writer = pd.ExcelWriter(filename, engine='xlsxwriter')

        metadata = _sort_dict(self.metadata)
        for channel in self.event_channels:
            metadata.append(('event_channel', channel.metadata['name']))
            metadata.extend(_sort_dict(channel.metadata))
        for channel in self.pos_channels:
            metadata.append(('pos_channel', channel.metadata['name']))
            metadata.extend(_sort_dict(channel.metadata))
        df = pd.DataFrame(metadata, columns=['Property', 'Value'])
        df.to_excel(excel_writer, sheet_name='metadata')

        df = pd.DataFrame(self.timestamps, columns=['timestamp'])
        df.to_excel(excel_writer, sheet_name='timestamps')

        columns_header = []
        columns = []
        for channel in self.event_channels:
            columns_header.append(channel.metadata['name'])
            columns.append(channel.data)
        df = pd.DataFrame(columns).T
        df.columns = columns_header
        df.to_excel(excel_writer, sheet_name='event_channels')

        columns_header = []
        columns = []
        for channel in self.pos_channels:
            columns_header.append(channel.metadata['name'] + ':x')
            columns_header.append(channel.metadata['name'] + ':y')
            columns.append(channel.data[:, 0])
            columns.append(channel.data[:, 1])
        df = pd.DataFrame(columns).T
        df.columns = columns_header
        df.to_excel(excel_writer, sheet_name='pos_channels')

        excel_writer.save()

    def close(self):
        self.nix_file.close()


class ChannelAnalysis(object):

    data_channel: DataChannelBase = None

    timestamps: np.ndarray = None

    data_arrays_order: list = []

    metadata: Dict = {}

    def __init__(self, data_channel, timestamps, data_arrays_order, **kwargs):
        super(ChannelAnalysis, self).__init__(**kwargs)
        self.data_channel = data_channel
        self.timestamps = timestamps
        self.data_arrays_order = data_arrays_order

    def load_data(self):
        self.metadata = self.data_channel.read_channel_config()

    def compute_statistics(self):
        raise NotImplementedError


class TemporalAnalysis(ChannelAnalysis):

    data_channel: TemporalDataChannelBase = None

    data: np.ndarray = None

    def load_data(self):
        super(TemporalAnalysis, self).load_data()

        data_channel = self.data_channel
        if len(data_channel.data_arrays) > 1:
            pass
        else:
            self.data = np.array(data_channel.data_array)


class EventAnalysis(TemporalAnalysis):

    data_channel: EventChannelData = None


class PosAnalysis(TemporalAnalysis):

    data_channel: PosChannelData = None
