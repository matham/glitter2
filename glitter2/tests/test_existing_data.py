
from glitter2.analysis import FileDataAnalysis
from glitter2.tests.coded_data import check_metadata, check_channel_metadata, \
    check_channel_data


def test_metadata(coded_data_file):
    with FileDataAnalysis(filename=str(coded_data_file)) as analysis:
        analysis.load_file_metadata()

        check_metadata(analysis)


def test_channel_metadata(coded_data_file):
    analysis = FileDataAnalysis(filename=str(coded_data_file))
    with analysis:
        analysis.load_file_metadata()

        check_channel_metadata(analysis)
    check_channel_metadata(analysis)


def test_channel_data(coded_data_file):
    analysis = FileDataAnalysis(filename=str(coded_data_file))
    with analysis:
        analysis.load_file_data()

        check_channel_data(analysis, first_timestamp_repeated=True)
    check_channel_data(analysis, first_timestamp_repeated=True)
