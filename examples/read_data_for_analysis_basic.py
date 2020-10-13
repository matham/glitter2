"""Demo example file that shows how to read the data from a NixIO Glitter2 h5
file and to export the raw data as well as print some pre-defined analysis
of the data.

See file ``read_data_for_analysis_batch.py`` for a way to batch the
statistics and export to an excel file, in addition to the raw data.

None of the operations in here effects or changes the original h5 file in
any way.
"""

from glitter2.analysis import FileDataAnalysis, \
    EventAnalysisChannel, PosAnalysisChannel, ZoneAnalysisChannel
from os.path import join, dirname

data_file = join(dirname(__file__), 'video_data.h5')
raw_excel_file = join(dirname(__file__), 'coded_data_raw.xlsx')

with FileDataAnalysis(filename=data_file) as analysis:
    # load all the channel data from the file
    analysis.load_file_data()

    # export the raw data to an excel file
    analysis.export_raw_data_to_excel(
        filename=raw_excel_file, dump_zone_collider=True)

    # print the channel names in the file
    print('Channels: ', list(analysis.channels_metadata.keys()))
    # print the video metadata
    print('Video metadata: ', analysis.video_metadata)
    # print file metadata
    print('File metadata: ', analysis.metadata)

    # create analysis channels for each data channel
    event = EventAnalysisChannel(name='An event', analysis_object=analysis)
    pos = PosAnalysisChannel(name='A spiral', analysis_object=analysis)
    zone = ZoneAnalysisChannel(name='A circle', analysis_object=analysis)

    # create an event channel that is true both when the event is active
    # and when the position channel is coded at that time.
    # The name of the new channel will be 'Spiral event'
    # These are special compute_xxx channels that return the result required
    # for creating a new channel of the appropriate type in analysis
    res = pos.compute_event_from_pos(event_channels=['An event'])
    analysis.add_event_channel('Spiral event', *res)

    # create an event channel that is true when the pos is in the zone
    res = pos.compute_pos_in_any_zone(zone_channels=['A circle'])
    analysis.add_event_channel('Spiral in zone', *res)

    # create event channel that is active when the 'Spiral in zone',
    # 'Spiral event' and the event channel is active
    res = event.compute_combine_events_and(
        event_channels=['Spiral in zone', 'Spiral event'])
    analysis.add_event_channel('Spiraling', *res)

    # create analysis channels for the new channels
    spiral_event = EventAnalysisChannel(
        name='Spiral event', analysis_object=analysis)
    spiral_in_zone = EventAnalysisChannel(
        name='Spiral in zone', analysis_object=analysis)
    spiraling = EventAnalysisChannel(
        name='Spiraling', analysis_object=analysis)

    # now print some stats
    for event_channel in (event, spiral_event, spiral_in_zone, spiraling):
        print(f'Channel: {event_channel.name}')

        res = event_channel.compute_active_duration()
        print(f'\tActive duration:\t{res}')

        res = event_channel.compute_delay_to_first()
        print(f'\tDelay to first:\t{res}')

        res = event_channel.compute_scored_duration()
        print(f'\tScored duration:\t{res}')

        res = event_channel.compute_event_count()
        print(f'\tNum events:\t{res}')

    print(f'Channel: {pos.name}')

    res = pos.compute_mean_center_distance(zone_channel='A circle')
    print(f'\tDistance to circle:\t{res}')

    res = pos.compute_distance_traveled()
    print(f'\tDist traveled:\t{res}')

    res = pos.compute_mean_speed()
    print(f'\tMean speed:\t{res}')

    print(f'Channel: {zone.name}')

    res = zone.compute_centroid()
    print(f'\tCentroid:\t{res}')

    res = zone.compute_area()
    print(f'\tArea:\t{res}')
