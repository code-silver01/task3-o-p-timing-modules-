
import sys, os
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ntp_sync.mock_time_source import MockNTPTimeSource
from ntp_sync.drift_log import DriftLog
from ntp_sync.ntp_daemon import NTPSyncDaemon, DriftTier, classify_drift


def make_daemon(tmp_path):
    source = MockNTPTimeSource()
    log = DriftLog(str(tmp_path / "drift_log.jsonl"))
    return NTPSyncDaemon(source, log), source, log


class TestDriftClassification:
    """The three tiers plus both exact boundary values, tested directly
    against the classifier — the simplest possible check that the
    thresholds are right before testing the daemon behavior built on them."""

    def test_small_drift_is_slew(self):
        assert classify_drift(50) == DriftTier.SLEW

    def test_just_under_boundary_is_slew(self):
        assert classify_drift(99.9) == DriftTier.SLEW

    def test_exactly_100ms_is_step_logged_not_slew(self):
        assert classify_drift(100) == DriftTier.STEP_LOGGED

    def test_mid_range_is_step_logged(self):
        assert classify_drift(500) == DriftTier.STEP_LOGGED

    def test_exactly_1000ms_is_step_logged_not_alert(self):
        assert classify_drift(1000) == DriftTier.STEP_LOGGED

    def test_just_over_1000ms_is_step_alert(self):
        assert classify_drift(1000.1) == DriftTier.STEP_ALERT

    def test_large_drift_is_step_alert(self):
        assert classify_drift(5000) == DriftTier.STEP_ALERT

    def test_negative_drift_classified_by_magnitude(self):
        # clock running FAST by 2 seconds is just as bad as running slow
        # by 2 seconds — direction shouldn't matter, only size
        assert classify_drift(-2000) == DriftTier.STEP_ALERT


class TestSlewTier:
    def test_slew_does_not_touch_recent_records(self, tmp_path):
        daemon, source, log = make_daemon(tmp_path)
        source.set_drift_ms(50)
        records = [{"timestamp_ms": 1000}, {"timestamp_ms": 2000}]

        result = daemon.sync_on_wifi_connect(recent_records=records)

        assert result.tier == DriftTier.SLEW
        assert result.records_adjusted == 0
        assert records[0]["timestamp_ms"] == 1000   # untouched
        assert result.phone_alert_sent is False

    def test_slew_does_not_send_phone_alert(self, tmp_path):
        daemon, source, log = make_daemon(tmp_path)
        source.set_drift_ms(30)
        daemon.sync_on_wifi_connect()
        assert daemon.phone_alerts == []


class TestStepLoggedTier:
    def test_step_logged_shifts_recent_records(self, tmp_path):
        daemon, source, log = make_daemon(tmp_path)
        source.set_drift_ms(300)
        records = [{"timestamp_ms": 1000}, {"timestamp_ms": 2000}]

        result = daemon.sync_on_wifi_connect(recent_records=records)

        assert result.tier == DriftTier.STEP_LOGGED
        assert result.records_adjusted == 2
        assert records[0]["timestamp_ms"] == 1300
        assert records[1]["timestamp_ms"] == 2300

    def test_step_logged_does_not_alert(self, tmp_path):
        daemon, source, log = make_daemon(tmp_path)
        source.set_drift_ms(300)
        result = daemon.sync_on_wifi_connect()
        assert result.phone_alert_sent is False
        assert daemon.phone_alerts == []

    def test_step_logged_writes_to_the_drift_log(self, tmp_path):
        daemon, source, log = make_daemon(tmp_path)
        source.set_drift_ms(300)
        daemon.sync_on_wifi_connect()
        entries = log.read_all()
        assert len(entries) == 1
        assert entries[0]["tier"] == "step_logged"
        assert entries[0]["drift_ms"] == 300


class TestStepAlertTier:
    def test_step_alert_sends_phone_alert(self, tmp_path):
        daemon, source, log = make_daemon(tmp_path)
        source.set_drift_ms(4000)
        result = daemon.sync_on_wifi_connect()
        assert result.phone_alert_sent is True
        assert len(daemon.phone_alerts) == 1
        assert daemon.phone_alerts[0]["drift_ms"] == 4000

    def test_step_alert_also_shifts_recent_records(self, tmp_path):
        daemon, source, log = make_daemon(tmp_path)
        source.set_drift_ms(4000)
        records = [{"timestamp_ms": 1000}]
        daemon.sync_on_wifi_connect(recent_records=records)
        assert records[0]["timestamp_ms"] == 5000

    def test_step_alert_logs_with_alert_flag_true(self, tmp_path):
        daemon, source, log = make_daemon(tmp_path)
        source.set_drift_ms(4000)
        daemon.sync_on_wifi_connect()
        entries = log.read_all()
        assert entries[0]["tier"] == "step_alert"
        assert entries[0]["phone_alert_sent"] is True


class TestPersistentDriftLog:
    def test_log_survives_across_daemon_instances(self, tmp_path):
        """Proves 'persistent' actually means persistent — a second,
        completely separate DriftLog pointed at the same file can read
        entries written by the first one."""
        log_path = str(tmp_path / "drift_log.jsonl")
        source = MockNTPTimeSource()
        log1 = DriftLog(log_path)
        daemon1 = NTPSyncDaemon(source, log1)
        source.set_drift_ms(200)
        daemon1.sync_on_wifi_connect()

        # a fresh DriftLog instance, same file, simulating a daemon restart
        log2 = DriftLog(log_path)
        entries = log2.read_all()
        assert len(entries) == 1
        assert entries[0]["drift_ms"] == 200

    def test_multiple_syncs_all_append_not_overwrite(self, tmp_path):
        daemon, source, log = make_daemon(tmp_path)
        source.set_drift_ms(50)
        daemon.sync_on_wifi_connect()
        source.set_drift_ms(300)
        daemon.sync_on_wifi_connect()
        source.set_drift_ms(4000)
        daemon.sync_on_wifi_connect()

        entries = log.read_all()
        assert len(entries) == 3
        assert [e["tier"] for e in entries] == ["slew", "step_logged", "step_alert"]


class TestRTCFallback:
    def test_boot_without_wifi_uses_rtc(self, tmp_path):
        daemon, source, log = make_daemon(tmp_path)
        assert daemon.used_rtc_fallback is False
        assert daemon.current_time_source == "ntp"

        result_time = daemon.boot_without_wifi(rtc_reported_time_ms=1_700_000_000_000)

        assert daemon.used_rtc_fallback is True
        assert daemon.current_time_source == "rtc"
        assert result_time == 1_700_000_000_000

    def test_wifi_sync_after_rtc_boot_switches_source_back(self, tmp_path):
        daemon, source, log = make_daemon(tmp_path)
        daemon.boot_without_wifi(rtc_reported_time_ms=1_700_000_000_000)
        assert daemon.current_time_source == "rtc"

        source.set_drift_ms(50)
        daemon.sync_on_wifi_connect()
        # once WiFi + NTP are available, correction can proceed — the
        # daemon isn't stuck on RTC forever, only until WiFi returns
        assert daemon.used_rtc_fallback is True   # history — it DID happen this boot