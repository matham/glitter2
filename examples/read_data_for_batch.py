"""Demo example file that shows how to read the data from a NixIO Glitter2 h5
file and to export the raw data as well as to pre-define some analysis
that will be performed on the files in a batch and the exported to a excel
file.

See file ``read_data_for_analysis_basic.py`` for how to print the individual
statistics for each channel rather than batching them for export to a file.
The output computed by this file is the same as the above-mentioned file.

None of the operations in here effects or changes the original h5 file in
any way.
"""

from glitter2.analysis import AnalysisSpec, FileDataAnalysis, \
    EventAnalysisChannel, PosAnalysisChannel, ZoneAnalysisChannel
from os.path import join, dirname

data_file = join(dirname(__file__), 'video_data.h5')
raw_excel_file = join(dirname(__file__), 'coded_data_raw.xlsx')
summary_excel_file = join(dirname(__file__), 'coded_data_summary.xlsx')


def make_spec():
    # define some summaries to compute. There three channels in the data file
    # named: 'An event', 'A spiral', and 'A circle', corresponding to an event,
    # zone, and circle channel
    spec = AnalysisSpec()

    # below we'll create some channels from existing channels, it's not as
    # intuitive as when doing it manually, but this is how we do it for
    # batching
    # Creates an event channel that is true both when the named event
    # is active and when the 'A spiral' position channel is coded at that
    # time. The name of the new channel will be 'Spiral event'
    spec.add_new_channel_computation(
        'A spiral', 'Spiral event', PosAnalysisChannel.compute_event_from_pos,
        event_channels=['An event'])

    # create an event channel that is true when the 'A spiral' pos is in the
    # zone
    spec.add_new_channel_computation(
        'A spiral', 'Spiral in zone',
        PosAnalysisChannel.compute_pos_in_any_zone, zone_channels=['A circle'])

    # create event channel that is active when the 'Spiral in zone',
    # 'Spiral event', and the 'An event' channel is active
    spec.add_new_channel_computation(
        'An event', 'Spiraling',
        EventAnalysisChannel.compute_combine_events_and,
        event_channels=['Spiral in zone', 'Spiral event'])

    # now add the summaries to compute
    # Empty list means apply it to all channels of the given type (e.g. event)
    spec.add_computation([], EventAnalysisChannel.compute_active_duration)
    spec.add_computation([], EventAnalysisChannel.compute_delay_to_first)
    spec.add_computation([], EventAnalysisChannel.compute_scored_duration)
    spec.add_computation([], EventAnalysisChannel.compute_event_count)
    # distance between the later given pos channel and the circle
    spec.add_computation(
        [], PosAnalysisChannel.compute_mean_center_distance,
        zone_channel='A circle')
    spec.add_computation([], PosAnalysisChannel.compute_distance_traveled)
    spec.add_computation([], PosAnalysisChannel.compute_mean_speed)
    spec.add_computation([], ZoneAnalysisChannel.compute_centroid)
    spec.add_computation([], ZoneAnalysisChannel.compute_area)

    return spec


# get spec used to compute the summaries for each file
analysis_spec = make_spec()

# we'll store the summary data as we get it from each file (if there was more
# than one file we'd loop over them and apply the same spec - as long as the
# files contain the same channel names/types)
summary = []

with FileDataAnalysis(filename=data_file) as analysis:
    # load all the channel data from the file
    analysis.load_file_data()

    # export the raw data to an excel file
    # analysis.export_raw_data_to_excel(
    #     filename=raw_excel_file, dump_zone_collider=True)

    file_summary = analysis.compute_data_summary(analysis_spec)
    summary.extend(file_summary)

# now that we have all the summary data accumulated, export it to a file
FileDataAnalysis.export_computed_data_summary(summary_excel_file, summary)
