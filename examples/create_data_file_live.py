"""Demo example file that shows how to create a NixIO Glitter2 h5 file
by adding timestamps and channel data as the timestamps are acquired.
"""

import nixio
from glitter2.storage.data_file import DataFile
from glitter2.player import GlitterPlayer
from os.path import join, dirname
from kivy_garden.painter import PaintCircle
import math

video_file = join(dirname(__file__), 'video.mp4')
data_file = join(dirname(__file__), 'video.h5')

# create nix data file
nix_file = nixio.File.open(data_file, nixio.FileMode.ReadWrite)
# create our data controller
data_file = DataFile(nix_file=nix_file)
# initialize the glitter data structures in the file
data_file.init_new_file()

# read all the frame timestamps and video metadata from the video file, this
# may take some time as all the frames are read
timestamps, video_metadata = GlitterPlayer.get_file_data(video_file)
t0 = timestamps[0]
width, height = video_metadata['src_vid_size']
center_x = width / 2.
center_y = height / 2.

# add first timestamp
data_file.notify_add_timestamp(t0)
data_file.notify_saw_first_timestamp()

# create channels
event = data_file.create_channel('event')
pos = data_file.create_channel('pos')
zone = data_file.create_channel('zone')

# set channel metadata
event.channel_config_dict = {'name': 'An event'}
pos.channel_config_dict = {'name': 'A spiral'}

circle = PaintCircle.create_shape(
    [center_x, center_y], 5 / 12 * min(width, height))
zone.channel_config_dict = {
    'name': 'A circle', 'shape_config': circle.get_state()}

# set channel data for first timestamp
event.set_timestamp_value(t0, False)
pos.set_timestamp_value(t0, (center_x, center_y))

# set the channel data and timestamps as we "read" the timestamps
angle = 20 * math.pi / len(timestamps)
extent = 1 / 3 * min(width, height)
for i, t in enumerate(timestamps[1:], start=1):
    data_file.notify_add_timestamp(t)

    event.set_timestamp_value(t, bool((i // 10) % 2))

    current_angle = i * angle
    pos.set_timestamp_value(t, (
        center_x + i / len(timestamps) * extent * math.cos(current_angle),
        center_y + i / len(timestamps) * extent * math.sin(current_angle)
    ))

# Indicate that we saw last timestamp
data_file.notify_saw_last_timestamp()

# finally close the nix file
nix_file.close()
