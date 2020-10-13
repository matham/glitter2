"""Demo example file that shows how to read the data from a NixIO Glitter2 h5
file.
"""

import nixio
from glitter2.storage.data_file import DataFile
from os.path import join, dirname
import numpy as np

data_file = join(dirname(__file__), 'video_data.h5')

# open the nix data file as read only
nix_file = nixio.File.open(data_file, nixio.FileMode.ReadOnly)
# create our data controller
data_file = DataFile(nix_file=nix_file)
# load the data from the file
data_file.open_file()

# print some metadata
print('Data file Glitter version:', data_file.glitter2_version)
print('Data file ffpyplayer version:', data_file.ffpyplayer_version)

# print the video metadata
print('Video metadata:')
print(data_file.video_metadata_dict)

print('Video file pixels per meter:', data_file.pixels_per_meter)

# check whether we have seen all frame. If we haven't then the timestamps and
# channel data may be discontinuous, otherwise we can just read the data from
# the single timestamps array. For this demo file it should be True
print('Seen all frames:', data_file.saw_all_timestamps)


# get the timestamps
print('Timestamps:', np.array(data_file.timestamps))

# print the single event channel data. There should only be one event channel
# in the demo file
event = list(data_file.event_channels.values())[0]
print('Event metadata:', event.channel_config_dict)
print('Event data:', np.array(event.data_array))

# print the single pos channel data. There should only be one pos channel in
# the demo file
pos = list(data_file.pos_channels.values())[0]
print('Pos metadata:', pos.channel_config_dict)
print('Pos data:', np.array(pos.data_array))

# print the single circle zone channel data. There should only be one zone
# channel in the demo file
circle = list(data_file.zone_channels.values())[0]
print('Circle metadata:', circle.channel_config_dict)

# finally close the nix file
nix_file.close()
