"""Profile-v3 network evidence regression tests; live controls are separate."""

from __future__ import annotations

import errno
from typing import Any

import pytest
from hephaestus.core.executor.sandbox import oci_network as network
from hephaestus.core.executor.sandbox.oci_protocol import OCI_PROFILE_VERSION, manifest_record


def evidence() -> dict[str, Any]:
    return {
        "interfaces": [
            {"index": 1, "name": "lo", "flags": 73, "primary_ipv4": "127.0.0.1", "ipv6": ["::1"]},
            {"index": 2, "name": "gre0", "flags": 128, "primary_ipv4": None, "ipv6": []},
        ],
        "proc_interfaces": ["gre0", "lo"],
        "routes": [],
        "connect_errno": 101,  # Linux ENETUNREACH, not the test host's errno
        "connect_errno_v6": 101,
    }


def test_profile_is_versioned_and_down_unaddressed_devices_are_not_connectivity() -> None:
    assert OCI_PROFILE_VERSION == 5
    assert manifest_record()["oci_profile_version"] == 5
    assert network.network_isolated(evidence())
    value = evidence()
    # This is not a name allowlist. State and the rest of the enclosing OCI
    # profile (including all capability sets dropped) establish confinement.
    value["interfaces"][1]["name"] = "other0"
    value["proc_interfaces"] = ["lo", "other0"]
    assert network.network_isolated(value)


@pytest.mark.parametrize("field", list(evidence()))
def test_missing_network_evidence_refuses(field: str) -> None:
    value = evidence()
    del value[field]
    assert not network.network_isolated(value)


@pytest.mark.parametrize("field", ["index", "name", "flags", "primary_ipv4", "ipv6"])
def test_missing_device_evidence_refuses(field: str) -> None:
    value = evidence()
    del value["interfaces"][1][field]
    assert not network.network_isolated(value)


@pytest.mark.parametrize("flags", [1, 65, 4163, 64, 8, -1, 65536, True, "128", None])
def test_up_running_loopback_spoofed_or_malformed_nonloopback_refuses(flags: object) -> None:
    value = evidence()
    value["interfaces"][1]["flags"] = flags
    assert not network.network_isolated(value)


@pytest.mark.parametrize(
    "key,address",
    [
        ("primary_ipv4", "172.17.0.2"),
        ("primary_ipv4", "0.0.0.0"),
        ("primary_ipv4", False),
        ("ipv6", ["fe80::1"]),
        ("ipv6", None),
    ],
)
def test_addressed_device_refuses_even_when_down(key: str, address: object) -> None:
    value = evidence()
    value["interfaces"][1][key] = address
    assert not network.network_isolated(value)


@pytest.mark.parametrize("key", ["connect_errno", "connect_errno_v6"])
@pytest.mark.parametrize("error", [0, -1, errno.ETIMEDOUT, errno.ECONNREFUSED, True, [], None])
def test_timeout_refused_connection_or_missing_errno_is_not_isolation(
    key: str, error: object
) -> None:
    value = evidence()
    value[key] = error
    assert not network.network_isolated(value)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("interfaces", []),
        ("interfaces", ["lo"]),
        ("interfaces", None),
        ("proc_interfaces", ["lo"]),
        ("proc_interfaces", ["lo", "gre0"]),
        ("routes", ["eth0 00000000 010011AC"]),
        ("routes", ["IPv6 non-loopback route"]),
        ("routes", None),
    ],
)
def test_inventory_and_route_evidence_is_exact(field: str, bad: object) -> None:
    value = evidence()
    value[field] = bad
    assert not network.network_isolated(value)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("index", True),
        ("index", 1),
        ("index", 0),
        ("index", -1),
        ("name", "lo"),
        ("name", []),
        ("name", "x" * 16),
    ],
)
def test_duplicate_or_invalid_device_identity_refuses(field: str, bad: object) -> None:
    value = evidence()
    value["interfaces"][1][field] = bad
    assert not network.network_isolated(value)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("flags", 8),
        ("flags", 1),
        ("primary_ipv4", "172.17.0.1"),
        ("primary_ipv4", None),
        ("ipv6", ["fe80::1"]),
        ("ipv6", ["invalid"]),
    ],
)
def test_loopback_identity_requires_loopback_evidence(field: str, bad: object) -> None:
    value = evidence()
    value["interfaces"][0][field] = bad
    assert not network.network_isolated(value)


@pytest.mark.parametrize("error", [101, 113, 97, 100])
def test_linux_errno_wire_values_do_not_depend_on_host(error: int) -> None:
    value = evidence()
    value["connect_errno"] = value["connect_errno_v6"] = error
    assert network.network_isolated(value)


def test_darwin_errno_is_not_accepted_as_a_linux_wire_value() -> None:
    value = evidence()
    value["connect_errno"] = 51  # ENETUNREACH on Darwin, not on Linux
    assert not network.network_isolated(value)


def test_old_schema_and_extra_fields_refuse() -> None:
    assert not network.network_isolated({"interfaces": ["lo"], "routes": [], "connect_errno": 101})
    value = evidence()
    value["ignored"] = True
    assert not network.network_isolated(value)
    value = evidence()
    value["interfaces"][0]["ignored"] = True
    assert not network.network_isolated(value)


def test_proc_device_parser_excludes_no_real_device_and_rejects_malformed() -> None:
    header = "Inter-|   Receive | Transmit\n face |bytes packets\n"
    row = " lo: " + " ".join(["0"] * 16) + "\n"
    assert network.parse_device_names(header + row) == ["lo"]
    for invalid in ("", header, header + row + row, header + "lo: 0\n"):
        with pytest.raises(RuntimeError):
            network.parse_device_names(invalid)


def test_ipv6_address_parser_rejects_unknown_device_or_malformed_value() -> None:
    line = "00000000000000000000000000000001 01 80 10 80 lo\n"
    assert network.parse_ipv6_addresses(line, {"lo"}) == {"lo": ["::1"]}
    for invalid in (
        line.replace("lo", "eth0"),
        line.replace("00001", "0000z"),
        line.replace("01 80", "01 81"),
        "partial",
    ):
        with pytest.raises(RuntimeError):
            network.parse_ipv6_addresses(invalid, {"lo"})


def test_route_parser_does_not_hide_nonloopback_or_malformed_rows() -> None:
    header = "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
    route = "eth0 00000000 010011AC 0003 0 0 0 00000000 0 0 0"
    assert network.parse_routes(header, "") == []
    assert network.parse_routes(header + route, "") == [route]
    with pytest.raises(RuntimeError):
        network.parse_routes(header + "lo", "")
    with pytest.raises(RuntimeError):
        network.parse_routes(header, "malformed lo")
    with pytest.raises(RuntimeError):
        network.parse_routes("", "")
