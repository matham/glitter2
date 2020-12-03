from glitter2.analysis import FileDataAnalysis
from glitter2.tests.coded_data import check_metadata, check_channel_data


def test_export_coded_data_stats(sample_csv_data_file):
    from glitter2.analysis.export import CSVImporter, SourceFile

    hf_file = sample_csv_data_file.parent.joinpath('video.h5')
    src = SourceFile(
        filename=sample_csv_data_file, source_root=sample_csv_data_file.parent)
    exporter = CSVImporter(output_files_root=str(sample_csv_data_file.parent))
    exporter.init_process()
    exporter.process_file(src)
    if src.exception is not None:
        e, exec_info = src.exception
        print(exec_info)
        raise Exception(e)
    exporter.finish_process()

    with FileDataAnalysis(filename=str(hf_file)) as analysis:
        analysis.load_file_data()

        check_metadata(analysis)
        check_channel_data(analysis, first_timestamp_repeated=True)
