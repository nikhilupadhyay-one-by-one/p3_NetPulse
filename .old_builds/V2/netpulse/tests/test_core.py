"""Tests for the parsing and calculation logic.

Everything here runs without a network connection or a display. The ping and
traceroute cases use captured output from Windows, Linux and macOS, which is
what keeps the cross-platform regexes honest.
"""

from __future__ import annotations

import pytest

from netpulse.core import formatting, oui, portscan
from netpulse.core.bandwidth import BandwidthMonitor
from netpulse.core.lanscan import parse_subnet
from netpulse.core.ping import PingStats, Reply, parse_output, parse_reply_line
from netpulse.core.traceroute import parse_hop_line

# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #


class TestFormatting:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (0, "0 B"),
            (512, "512 B"),
            (1024, "1.0 KB"),
            (1536, "1.5 KB"),
            (1048576, "1.0 MB"),
            (1073741824, "1.0 GB"),
            (-5, "0 B"),
        ],
    )
    def test_human_bytes(self, value, expected):
        assert formatting.human_bytes(value) == expected

    def test_human_speed_appends_per_second(self):
        assert formatting.human_speed(1048576) == "1.0 MB/s"

    def test_human_bits_uses_decimal_steps(self):
        # 1 MB/s is 8 Mbps at 1000-based ISP units, not 8.39.
        assert formatting.human_bits(1_000_000) == "8.0 Mbps"

    def test_split_speed_separates_unit(self):
        assert formatting.split_speed(1048576) == ("1.0", "MB/s")

    @pytest.mark.parametrize(
        "seconds,expected",
        [(9, "9s"), (69, "1m 09s"), (3849, "1h 04m 09s"), (-3, "0s")],
    )
    def test_human_duration(self, seconds, expected):
        assert formatting.human_duration(seconds) == expected

    def test_human_latency_keeps_submillisecond_precision(self):
        assert formatting.human_latency(0.42) == "0.42 ms"
        assert formatting.human_latency(12.34) == "12.3 ms"
        assert formatting.human_latency(250.6) == "251 ms"
        assert formatting.human_latency(None) == "—"


# --------------------------------------------------------------------------- #
# Ping parsing
# --------------------------------------------------------------------------- #

WINDOWS_PING = """
Pinging google.com [142.250.194.78] with 32 bytes of data:
Reply from 142.250.194.78: bytes=32 time=12ms TTL=115

Ping statistics for 142.250.194.78:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
"""

LINUX_PING = """
PING google.com (142.250.194.78) 56(84) bytes of data.
64 bytes from bom12s15-in-f14.1e100.net (142.250.194.78): icmp_seq=1 ttl=115 time=11.9 ms

--- google.com ping statistics ---
1 packets transmitted, 1 received, 0% packet loss, time 0ms
"""

MACOS_PING = """
PING example.com (93.184.216.34): 56 data bytes
64 bytes from 93.184.216.34: icmp_seq=0 ttl=56 time=8.472 ms
"""

WINDOWS_TIMEOUT = """
Pinging 10.255.255.1 with 32 bytes of data:
Request timed out.

Ping statistics for 10.255.255.1:
    Packets: Sent = 1, Received = 0, Lost = 1 (100% loss),
"""

SPANISH_PING = "Respuesta desde 142.250.194.78: bytes=32 tiempo=14ms TTL=115"


class TestPingParsing:
    def test_windows_reply(self):
        rtt, ttl, address = parse_reply_line(
            "Reply from 142.250.194.78: bytes=32 time=12ms TTL=115"
        )
        assert rtt == 12.0
        assert ttl == 115
        assert address == "142.250.194.78"

    def test_linux_reply(self):
        rtt, ttl, address = parse_reply_line(
            "64 bytes from 142.250.194.78: icmp_seq=1 ttl=115 time=11.9 ms"
        )
        assert rtt == pytest.approx(11.9)
        assert ttl == 115
        assert address == "142.250.194.78"

    def test_sub_millisecond_uses_less_than(self):
        rtt, _, _ = parse_reply_line("Reply from 192.168.1.1: bytes=32 time<1ms TTL=64")
        assert rtt == 1.0

    def test_localised_output_still_parses(self):
        rtt, ttl, _ = parse_reply_line(SPANISH_PING)
        assert rtt == 14.0
        assert ttl == 115

    def test_timeout_line_yields_nothing(self):
        assert parse_reply_line("Request timed out.") == (None, None, None)

    def test_header_line_yields_nothing(self):
        assert parse_reply_line("Pinging google.com [142.250.194.78] with 32 bytes") == (
            None, None, None,
        )

    def test_unreachable_is_not_read_as_a_reply(self):
        assert parse_reply_line("Reply from 10.0.0.1: Destination host unreachable.") == (
            None, None, None,
        )

    @pytest.mark.parametrize(
        "output,rtt", [(WINDOWS_PING, 12.0), (LINUX_PING, 11.9), (MACOS_PING, 8.472)]
    )
    def test_full_output_across_platforms(self, output, rtt):
        parsed_rtt, ttl, address, error = parse_output(output)
        assert parsed_rtt == pytest.approx(rtt)
        assert ttl is not None
        assert address is not None
        assert error is None

    def test_full_output_timeout_reports_the_reason(self):
        rtt, _, _, error = parse_output(WINDOWS_TIMEOUT)
        assert rtt is None
        assert error == "Request timed out."


class TestPingStats:
    def _session(self, rtts, losses=0):
        stats = PingStats()
        for index, rtt in enumerate(rtts, start=1):
            stats.add(Reply(index, "host", True, rtt_ms=rtt))
        for index in range(losses):
            stats.add(Reply(index, "host", False))
        return stats

    def test_averages_and_extremes(self):
        stats = self._session([10, 20, 30])
        assert stats.average == 20
        assert stats.minimum == 10
        assert stats.maximum == 30

    def test_jitter_is_mean_consecutive_difference(self):
        # Differences are 10 and 5, so the mean is 7.5.
        stats = self._session([10, 20, 15])
        assert stats.jitter == pytest.approx(7.5)

    def test_jitter_needs_two_samples(self):
        assert self._session([10]).jitter is None

    def test_loss_percentage(self):
        stats = self._session([10, 20], losses=2)
        assert stats.sent == 4
        assert stats.lost == 2
        assert stats.loss_pct == 50.0

    def test_quality_grades(self):
        assert self._session([10, 12, 11]).quality == "Excellent"
        assert self._session([300, 310, 305]).quality == "Poor"
        assert self._session([], losses=3).quality == "Unreachable"
        assert PingStats().quality == "No data"


# --------------------------------------------------------------------------- #
# Traceroute parsing
# --------------------------------------------------------------------------- #


class TestTracerouteParsing:
    def test_windows_hop_puts_times_before_the_address(self):
        hop = parse_hop_line("  1     1 ms     1 ms     1 ms  192.168.1.1")
        assert hop is not None
        assert hop.number == 1
        assert hop.address == "192.168.1.1"
        assert hop.rtts == [1.0, 1.0, 1.0]

    def test_unix_hop_puts_times_after_the_address(self):
        hop = parse_hop_line(" 7  142.250.56.1  9.211 ms  9.180 ms  9.145 ms")
        assert hop is not None
        assert hop.number == 7
        assert hop.address == "142.250.56.1"
        assert hop.average == pytest.approx(9.179, abs=0.01)

    def test_timed_out_hop(self):
        hop = parse_hop_line("  3     *        *        *     Request timed out.")
        assert hop is not None
        assert hop.timed_out is True
        assert hop.address is None
        assert hop.average is None

    def test_banner_lines_are_skipped(self):
        assert parse_hop_line("Tracing route to google.com [142.250.194.78]") is None
        assert parse_hop_line("") is None
        assert parse_hop_line("traceroute to google.com, 30 hops max") is None

    def test_private_address_detection(self):
        assert parse_hop_line("  1  1 ms  192.168.1.1").is_private is True
        assert parse_hop_line("  2  1 ms  10.0.0.1").is_private is True
        assert parse_hop_line("  3  1 ms  172.16.5.4").is_private is True
        assert parse_hop_line("  4  1 ms  172.32.5.4").is_private is False
        assert parse_hop_line("  5  9 ms  142.250.56.1").is_private is False

    def test_label_falls_back_through_hostname_then_address(self):
        hop = parse_hop_line(" 2  1 ms  10.0.0.1")
        assert hop.label == "10.0.0.1"
        hop.hostname = "gateway.local"
        assert hop.label == "gateway.local"


# --------------------------------------------------------------------------- #
# Port ranges
# --------------------------------------------------------------------------- #


class TestPortRanges:
    def test_single_ports(self):
        assert portscan.parse_port_range("22,80,443") == [22, 80, 443]

    def test_ranges_expand(self):
        assert portscan.parse_port_range("8000-8003") == [8000, 8001, 8002, 8003]

    def test_mixed_input_is_sorted_and_deduplicated(self):
        assert portscan.parse_port_range("443,22,22,80-82") == [22, 80, 81, 82, 443]

    def test_reversed_range_is_accepted(self):
        assert portscan.parse_port_range("85-83") == [83, 84, 85]

    def test_whitespace_is_ignored(self):
        assert portscan.parse_port_range(" 22 , 80 ") == [22, 80]

    @pytest.mark.parametrize("bad", ["", "abc", "0", "70000", "22-99999", "80-"])
    def test_invalid_input_raises(self, bad):
        with pytest.raises(ValueError):
            portscan.parse_port_range(bad)

    def test_known_service_names(self):
        assert portscan.service_name(443) == "HTTPS"
        assert portscan.service_name(22) == "SSH"


# --------------------------------------------------------------------------- #
# MAC vendors
# --------------------------------------------------------------------------- #


class TestVendorLookup:
    @pytest.mark.parametrize(
        "mac", ["b8:27:eb:11:22:33", "B8-27-EB-11-22-33", "B8:27:EB:11:22:33"]
    )
    def test_separator_and_case_do_not_matter(self, mac):
        assert oui.lookup(mac) == "Raspberry Pi"

    def test_locally_administered_addresses_are_flagged(self):
        # Bit 1 of the first octet set means the MAC was made up by the device,
        # which is what phones do for Wi-Fi privacy.
        assert oui.lookup("a2:11:22:33:44:55") == "Randomised MAC"

    def test_unknown_global_address(self):
        assert oui.lookup("00:00:01:22:33:44") == "Unknown"

    def test_malformed_input(self):
        assert oui.lookup("not-a-mac") == "Unknown"
        assert oui.lookup("") == "Unknown"

    def test_normalise_pads_short_octets(self):
        assert oui.normalise("0:1:2:3:4:5") == "00:01:02:03:04:05"
        assert oui.normalise("00:11:22") is None


# --------------------------------------------------------------------------- #
# Subnets
# --------------------------------------------------------------------------- #


class TestSubnets:
    def test_slash_24_yields_254_hosts(self):
        hosts = parse_subnet("192.168.1.0/24")
        assert len(hosts) == 254
        assert hosts[0] == "192.168.1.1"
        assert hosts[-1] == "192.168.1.254"

    def test_host_address_is_normalised_to_its_network(self):
        assert parse_subnet("192.168.1.57/24")[0] == "192.168.1.1"

    def test_oversized_range_is_refused(self):
        with pytest.raises(ValueError, match="Narrow it"):
            parse_subnet("10.0.0.0/8")

    def test_malformed_input_is_refused(self):
        with pytest.raises(ValueError):
            parse_subnet("not a subnet")
        with pytest.raises(ValueError):
            parse_subnet("")


# --------------------------------------------------------------------------- #
# Bandwidth arithmetic
# --------------------------------------------------------------------------- #


class TestBandwidthMath:
    def test_counter_reset_does_not_produce_a_negative_rate(self):
        # Adapter counters restart at zero when the driver reloads. A negative
        # delta must read as zero rather than a huge spike.
        assert BandwidthMonitor._delta(50, 1000) == 0

    def test_normal_delta(self):
        assert BandwidthMonitor._delta(1500, 1000) == 500

    def test_first_sample_only_sets_a_baseline(self):
        monitor = BandwidthMonitor()
        assert monitor.sample() is None

    def test_history_is_bounded(self):
        monitor = BandwidthMonitor(history=5)
        assert monitor.history.maxlen == 5

    def test_empty_series_is_safe_to_plot(self):
        assert BandwidthMonitor().series() == ([], [], [])

    def test_average_of_empty_history_is_zero(self):
        assert BandwidthMonitor().average() == (0.0, 0.0)


# --------------------------------------------------------------------------- #
# Device classification
# --------------------------------------------------------------------------- #


class TestDeviceRoles:
    def _device(self, **kwargs):
        from netpulse.core.lanscan import Device

        return Device(ip="192.168.1.10", **kwargs)

    def test_self_and_gateway_win_over_vendor(self):
        assert self._device(vendor="Apple", is_self=True).role == "This computer"
        assert self._device(vendor="TP-Link", is_gateway=True).role == "Router"

    def test_vendor_implies_a_device_class(self):
        assert self._device(vendor="Raspberry Pi").role == "Single-board computer"
        assert self._device(vendor="Roku").role == "Streaming box"
        assert self._device(vendor="HP").role == "Printer"

    def test_unknown_vendor_says_nothing_rather_than_guessing(self):
        assert self._device(vendor="Unknown").role == "—"
        assert self._device(vendor="Randomised MAC").role == "—"
        assert self._device().role == "—"

    def test_label_remains_an_alias_for_role(self):
        assert self._device(vendor="Sonos").label == "Speaker"
