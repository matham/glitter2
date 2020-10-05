"""Legacy Glitter file importer
===============================

Converts legacy glitter h5 files into the glitter2 format.
"""
import nixio as nix
import numpy as np
import tables as tb
from distutils.version import LooseVersion

from glitter2.utils import fix_name
from glitter2.storage.data_file import DataFile

__all__ = ('LegacyFileReader', )


def unicodify(val):
    if isinstance(val, dict):
        return {unicodify(key): unicodify(value) for key, value in val.items()}
    elif isinstance(val, list):
        return [unicodify(element) for element in val]
    elif isinstance(val, bytes):
        return val.decode('utf8')
    elif isinstance(val, np.str_):
        return str(val)
    else:
        return val


class LegacyFileReader(object):

    def upgrade_legacy_file(self, src_path: str, nix_file: nix.File) -> None:
        if DataFile.get_file_glitter2_version(src_path) is not None:
            raise ValueError(
                '"{}" is a glitter v2 file already'.format(src_path))

        src_file = tb.open_file(src_path, mode='r')

        try:
            version = src_file.root._v_attrs['Glitter_version']
            if LooseVersion(str(version)) >= LooseVersion('3'):
                res = self._read_legacy_v3_file(src_file)
            else:
                res = self._read_legacy_file(src_file)

            data_file = DataFile(nix_file=nix_file)
            data_file.init_new_file()
            data_file.set_file_data(*res, [])
        finally:
            src_file.close()

    @staticmethod
    def _read_legacy_file(src_file):
        video_info = src_file.root.video_info._v_attrs
        file_metadata = unicodify(dict(video_info.video_params))
        file_metadata['filename_head'] = unicodify(video_info.file_path)
        file_metadata['filename_tail'] = unicodify(video_info.file_name)
        file_metadata['file_size'] = 0

        seen_all_frames = video_info.seen_all_frames
        timestamps = [
            np.array(d) for d in src_file.root.raw_data.pts._f_iter_nodes()]

        event_channels = {}
        pos_channels = {}
        for group in src_file.root.raw_data._f_iter_nodes():
            if group._v_name == 'pts':
                continue

            attrs = group._v_attrs
            chan_type = unicodify(attrs['score_type'])

            name = unicodify(
                fix_name(attrs['name'], event_channels, pos_channels))
            metadata = {'name': name}
            if 'keycode' in group._v_attrs:
                metadata['keyboard_key'] = unicodify(group._v_attrs['keycode'])

            data = [np.array(d) for d in group._f_iter_nodes()]
            if chan_type == 't':
                event_channels[name] = (metadata, data)
            elif chan_type == 'xyt':
                pos_channels[name] = (metadata, data)
            else:
                raise TypeError('xy channels are not supported')

        event_channels = list(event_channels.values())
        pos_channels = list(pos_channels.values())
        return file_metadata, seen_all_frames, timestamps, event_channels, \
            pos_channels

    @staticmethod
    def _read_legacy_v3_file(src_file):
        video_group = src_file.root.video_info
        file_metadata = unicodify(dict(video_group._v_attrs.video_params))
        file_metadata['filename_head'] = unicodify(
            video_group._v_attrs.file_path)
        file_metadata['filename_tail'] = unicodify(
            video_group._v_attrs.file_name)
        file_metadata['file_size'] = 0

        seen_all_frames = video_group._v_attrs.seen_all_frames
        timestamps = [
            np.array(d) for d in src_file.root.raw_data.pts._f_iter_nodes()]

        event_channels = {}
        pos_channels = {}
        for group in src_file.root.raw_data.t._f_iter_nodes():
            attrs = group._v_attrs
            name = unicodify(
                fix_name(attrs['name'], event_channels, pos_channels))
            metadata = {'name': name}
            if 'keycode' in attrs['config']:
                metadata['keyboard_key'] = unicodify(
                    attrs['config']['keycode'])

            data = [np.array(d) for d in group._f_iter_nodes()]
            event_channels[name] = (metadata, data)

        for group in src_file.root.raw_data.xyt._f_iter_nodes():
            attrs = group._v_attrs
            name = unicodify(
                fix_name(attrs['name'], event_channels, pos_channels))
            metadata = {'name': name}

            data = [np.array(d) for d in group._f_iter_nodes()]
            pos_channels[name] = (metadata, data)

        event_channels = list(event_channels.values())
        pos_channels = list(pos_channels.values())
        return file_metadata, seen_all_frames, timestamps, event_channels, \
            pos_channels
