"""Demo example file that shows how to create a NixIO Glitter2 h5 file
from a video file and example coded channels.
"""

import nixio
from glitter2.storage.data_file import DataFile
from glitter2.player import GlitterPlayer
from os.path import join, dirname
from kivy_garden.painter import PaintCircle
import math

video_file = join(dirname(__file__), 'video.mp4')
data_file = join(dirname(__file__), 'video_data.h5')

# create nix data file
nix_file = nixio.File.open(
    data_file, nixio.FileMode.Overwrite,
    compression=nixio.Compression.DeflateNormal)
# create our data controller
data_file = DataFile(nix_file=nix_file)
# initialize the glitter data structures in the file
data_file.init_new_file()

# read all the frame timestamps and video metadata from the video file, this
# may take some time as all the frames are read
timestamps, video_metadata = GlitterPlayer.get_file_data(video_file)
width, height = video_metadata['src_vid_size']

# create an event channel
event = []
for i in range(len(timestamps)):
    event.append(bool((i // 10) % 2))
event_metadata = {'name': 'An event'}

# create an pos channel with spiral data
angle = 20 * math.pi / len(timestamps)
pos = []
extent = 1 / 3 * min(width, height)
center_x = width / 2
center_y = height / 2
for i in range(len(timestamps)):
    current_angle = i * angle
    pos.append((
        center_x + i / len(timestamps) * extent * math.cos(current_angle),
        center_y + i / len(timestamps) * extent * math.sin(current_angle)
    ))
pos_metadata = {'name': 'A spiral'}

# create a circle zone channel
circle = PaintCircle.create_shape(
    [center_x, center_y], 5 / 12 * min(width, height))
zone_metadata = {'name': 'A circle', 'shape_config': circle.get_state()}

# now set the file data
data_file.set_file_data(
    video_file_metadata=video_metadata, saw_all_timestamps=True,
    timestamps=[timestamps], event_channels=[(event_metadata, [event])],
    pos_channels=[(pos_metadata, [pos])],
    zone_channels=[zone_metadata])

# if you want to inspect the data file instance, load the data
data_file.open_file()

# finally close the nix file
nix_file.close()
