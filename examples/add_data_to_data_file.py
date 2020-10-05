"""Demo example file that shows how to add or duplicate data channels in a
NixIO Glitter2 h5 file.
"""

import nixio
from glitter2.storage.data_file import DataFile
from os.path import join, dirname
import shutil
from kivy_garden.painter import PaintCircle
import numpy as np
import math

# first copy the file before editing
src_data_file = join(dirname(__file__), 'video_data.h5')
data_file = join(dirname(__file__), 'video.h5')
shutil.copy(src_data_file, data_file)

# open the nix data file for editing
nix_file = nixio.File.open(data_file, nixio.FileMode.ReadWrite)
# create our data controller
data_file = DataFile(nix_file=nix_file)
# load the data from the file
data_file.open_file()

# check whether we have seen all frame. If we haven't then the timestamps and
# channel data may be discontinuous, otherwise we can just read the data from
# the single timestamps array. For this demo file it should be True
assert data_file.saw_all_timestamps


# get video metadata
video_metadata = data_file.video_metadata_dict
width, height = video_metadata['src_vid_size']

# get the timestamps
timestamps = np.array(data_file.timestamps)


# Duplicate the event channel. There should only be one event channel
# in the demo file so get that one
event = list(data_file.event_channels.values())[0]
new_event = data_file.duplicate_channel(event)
# fix the name of the duplicated channel because all the channels should have
# unique names
metadata = event.channel_config_dict
metadata['name'] += ' copy'
event.channel_config_dict = metadata


# create the channels
event = data_file.create_channel('event')
pos = data_file.create_channel('pos')
zone = data_file.create_channel('zone')

# set channel metadata
event.channel_config_dict = {'name': 'A new event'}
pos.channel_config_dict = {'name': 'A new spiral'}

center_x = width / 2. + 10
center_y = height / 2. + 10
circle = PaintCircle.create_shape(
    [center_x, center_y], 5 / 12 * min(width, height))
zone.channel_config_dict = {
    'name': 'A new circle', 'shape_config': circle.get_state()}


# add the new channels' data
# set the channel data and timestamps as we "read" the timestamps
angle = 20 * math.pi / len(timestamps)
extent = 1 / 3 * min(width, height)
for i, t in enumerate(timestamps):
    event.set_timestamp_value(t, bool((i // 10) % 2))

    current_angle = i * angle
    pos.set_timestamp_value(t, (
        center_x + i / len(timestamps) * extent * math.cos(current_angle),
        center_y + i / len(timestamps) * extent * math.sin(current_angle)
    ))

# finally close the nix file
nix_file.close()
