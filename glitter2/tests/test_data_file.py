
from glitter2.storage.data_file import DataFile


def test_notify_ends_straight(raw_data_file: DataFile):
    assert not raw_data_file._saw_first_timestamp
    assert not raw_data_file._saw_last_timestamp
    assert not raw_data_file.saw_all_timestamps

    assert raw_data_file.notify_add_timestamp(1) == 0
    raw_data_file.notify_saw_first_timestamp()

    assert raw_data_file._saw_first_timestamp
    assert not raw_data_file._saw_last_timestamp
    assert not raw_data_file.saw_all_timestamps

    assert raw_data_file.notify_add_timestamp(1) == 0
    assert raw_data_file.notify_add_timestamp(2) == 0

    raw_data_file.notify_saw_last_timestamp()

    assert raw_data_file._saw_first_timestamp
    assert raw_data_file._saw_last_timestamp
    assert raw_data_file.saw_all_timestamps


def test_notify_seek(raw_data_file: DataFile):
    assert raw_data_file.notify_add_timestamp(1) == 0
    raw_data_file.notify_saw_first_timestamp()
    assert raw_data_file.notify_add_timestamp(2) == 0

    raw_data_file.notify_interrupt_timestamps()

    assert raw_data_file.notify_add_timestamp(4) == 1
    raw_data_file.notify_saw_last_timestamp()

    assert raw_data_file._saw_first_timestamp
    assert raw_data_file._saw_last_timestamp
    assert not raw_data_file.saw_all_timestamps

    raw_data_file.notify_interrupt_timestamps()
    assert raw_data_file.notify_add_timestamp(2) == 0
    assert raw_data_file.notify_add_timestamp(3) == 0
    assert raw_data_file.notify_add_timestamp(4) == 0

    assert raw_data_file._saw_first_timestamp
    assert raw_data_file._saw_last_timestamp
    assert raw_data_file.saw_all_timestamps


def test_condition(raw_data_file: DataFile):
    assert raw_data_file.notify_add_timestamp(1) == 0
    raw_data_file.notify_saw_first_timestamp()
    assert raw_data_file.condition_timestamp(0) == 1.

    assert raw_data_file.notify_add_timestamp(2) == 0
    assert raw_data_file.condition_timestamp(1.4) == 1.
    assert raw_data_file.condition_timestamp(1.6) == 2.

    assert raw_data_file.notify_add_timestamp(3) == 0
    assert raw_data_file.notify_add_timestamp(4) == 0

    raw_data_file.notify_saw_last_timestamp()
    assert raw_data_file.condition_timestamp(3.4) == 3.
    assert raw_data_file.condition_timestamp(3.6) == 4.
    assert raw_data_file.condition_timestamp(5) == 4.
    assert raw_data_file.saw_all_timestamps


def test_condition_seek(raw_data_file: DataFile):
    assert raw_data_file.notify_add_timestamp(1) == 0
    raw_data_file.notify_saw_first_timestamp()
    assert raw_data_file.notify_add_timestamp(2) == 0
    raw_data_file.notify_interrupt_timestamps()

    assert raw_data_file.condition_timestamp(.5) == 1
    assert raw_data_file.notify_add_timestamp(1.) == 0
    assert raw_data_file.condition_timestamp(1.) == 1.
    assert raw_data_file.notify_add_timestamp(1) == 0
    assert raw_data_file.condition_timestamp(1.4) == 1.
    assert raw_data_file.notify_add_timestamp(1) == 0
    assert raw_data_file.condition_timestamp(1.6) == 2.
    assert raw_data_file.notify_add_timestamp(2.) == 0
    assert raw_data_file.condition_timestamp(2.) == 2.
    assert raw_data_file.notify_add_timestamp(2.) == 0

    raw_data_file.notify_interrupt_timestamps()

    assert raw_data_file.notify_add_timestamp(3) == 1
    assert raw_data_file.notify_add_timestamp(4) == 1

    raw_data_file.notify_saw_last_timestamp()
    assert not raw_data_file.saw_all_timestamps

    raw_data_file.notify_interrupt_timestamps()
    assert raw_data_file.condition_timestamp(1.6) == 2.
    assert raw_data_file.notify_add_timestamp(2.) == 0
    assert raw_data_file.condition_timestamp(2.) == 2.
    assert raw_data_file.notify_add_timestamp(2.) == 0

    assert raw_data_file.condition_timestamp(2.1) is None
    assert raw_data_file.notify_add_timestamp(2.1) == 0
    assert raw_data_file.condition_timestamp(2.5) is None
    assert raw_data_file.notify_add_timestamp(2.5) == 0
    assert raw_data_file.condition_timestamp(2.9) is None
    assert raw_data_file.notify_add_timestamp(2.9) == 0
    assert not raw_data_file.saw_all_timestamps

    assert raw_data_file.condition_timestamp(3.) == 3.
    assert raw_data_file.notify_add_timestamp(3.) == 0
    assert raw_data_file.saw_all_timestamps

    assert raw_data_file.condition_timestamp(3.4) == 3.
    assert raw_data_file.notify_add_timestamp(3.) == 0
    assert raw_data_file.condition_timestamp(3.6) == 4.
    assert raw_data_file.notify_add_timestamp(4.) == 0
    assert raw_data_file.condition_timestamp(4.4) == 4.
    assert raw_data_file.notify_add_timestamp(4.) == 0
    assert raw_data_file.condition_timestamp(5.) == 4.
    assert raw_data_file.notify_add_timestamp(4.) == 0
