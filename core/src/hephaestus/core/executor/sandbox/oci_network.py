"""Profile-v3 network evidence: kernel interface state, not sysfs filenames.

LinuxKit creates down tunnel devices even in a new networkless namespace, and
/sys/class/net also contains non-device entries such as bonding_masters. Neither
is evidence of connectivity. Enumerate real devices through the socket API and
cross-check procfs. The host accepts only an up loopback and inactive, unaddressed
other devices, with no non-loopback routes and failed IPv4/IPv6 connections.

This check is necessary, not sufficient: the enclosing OCI profile still requires
nonroot identity, all capability sets empty, no-new-privileges and private worker
execution. In particular a worker must not be able to bring a down device up.
"""

from __future__ import annotations

import errno
import ipaddress
import re
import socket
import struct
from pathlib import Path

_MAX_INTERFACES = 64
_NAME = re.compile(r"[a-zA-Z0-9_.:-]{1,15}", re.ASCII)
_IFF_UP = 0x1
_IFF_LOOPBACK = 0x8
_IFF_RUNNING = 0x40
# These are LINUX wire values, not the host's errno constants. Darwin assigns
# ENETUNREACH=51 whereas the Linux worker emits 101. Using host errno values
# would reject genuine Linux isolation even after the interface check passed.
_UNREACHABLE = frozenset({101, 113, 97, 100})  # ENETUNREACH, EHOSTUNREACH, EAFNOSUPPORT, ENETDOWN


def _read(path: str) -> str:
    with Path(path).open(encoding="ascii") as stream:
        text = stream.read(65537)
    if len(text) > 65536:
        raise RuntimeError("network observation exceeds bound")
    return text


def _name(value: object) -> bool:
    return isinstance(value, str) and _NAME.fullmatch(value) is not None


def parse_device_names(text: str) -> list[str]:
    lines = text.splitlines()
    if len(lines) < 2 or "Inter-|" not in lines[0] or "face |" not in lines[1]:
        raise RuntimeError("malformed network device table")
    names: list[str] = []
    for line in lines[2:]:
        name, separator, counters = line.strip().partition(":")
        fields = counters.split()
        if not separator or not _name(name) or len(fields) != 16:
            raise RuntimeError("malformed network device row")
        if not all(field.isascii() and field.isdecimal() for field in fields):
            raise RuntimeError("malformed network device counters")
        names.append(name)
    if not names or len(names) > _MAX_INTERFACES or len(set(names)) != len(names):
        raise RuntimeError("ambiguous network device inventory")
    return sorted(names)


def parse_ipv6_addresses(text: str, names: set[str]) -> dict[str, list[str]]:
    addresses: dict[str, list[str]] = {name: [] for name in names}
    rows = text.splitlines()
    if len(rows) > 256:
        raise RuntimeError("IPv6 address table exceeds bound")
    for line in rows:
        fields = line.split()
        if len(fields) != 6 or fields[-1] not in names:
            raise RuntimeError("malformed IPv6 address table")
        if re.fullmatch(r"[0-9a-fA-F]{32}", fields[0]) is None or any(
            re.fullmatch(r"[0-9a-fA-F]+", field) is None for field in fields[1:5]
        ):
            raise RuntimeError("malformed IPv6 address value")
        if int(fields[1], 16) <= 0 or not 0 <= int(fields[2], 16) <= 128:
            raise RuntimeError("malformed IPv6 address index/prefix")
        addresses[fields[-1]].append(str(ipaddress.IPv6Address(int(fields[0], 16))))
    return addresses


def parse_routes(ipv4: str, ipv6: str) -> list[str]:
    lines = ipv4.splitlines()
    header = [
        "Iface",
        "Destination",
        "Gateway",
        "Flags",
        "RefCnt",
        "Use",
        "Metric",
        "Mask",
        "MTU",
        "Window",
        "IRTT",
    ]
    if not lines or lines[0].split() != header:
        raise RuntimeError("malformed IPv4 route header")
    routes: list[str] = []
    for line in lines[1:]:
        row = line.split()
        if len(row) != 11 or not _name(row[0]):
            raise RuntimeError("malformed IPv4 route row")
        if any(re.fullmatch(r"[0-9a-fA-F]+", field) is None for field in row[1:]):
            raise RuntimeError("malformed IPv4 route value")
        if row[0] != "lo":
            routes.append(" ".join(row))
    for line in ipv6.splitlines():
        row = line.split()
        if len(row) != 10 or not _name(row[-1]):
            raise RuntimeError("malformed IPv6 route row")
        if any(re.fullmatch(r"[0-9a-fA-F]+", field) is None for field in row[:-1]):
            raise RuntimeError("malformed IPv6 route value")
        if row[-1] != "lo":
            routes.append(" ".join(row))
    return routes


def _connect_errno(family: socket.AddressFamily, address: tuple[str, int]) -> int:
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            sock.connect(address)
    except OSError as exc:
        return int(exc.errno or -1)
    return 0


def observe_network() -> dict[str, object]:
    # Linux ioctls are used only inside the Linux worker, never on the Mac host.
    import fcntl

    interfaces = socket.if_nameindex()
    names = [name for _, name in interfaces]
    indices = [index for index, _ in interfaces]
    if (
        not names
        or len(names) > _MAX_INTERFACES
        or len(set(names)) != len(names)
        or len(set(indices)) != len(indices)
        or any(not _name(name) for name in names)
        or any(type(index) is not int or index <= 0 for index in indices)
    ):
        raise RuntimeError("ambiguous socket interface inventory")
    proc_names = parse_device_names(_read("/proc/self/net/dev"))
    if sorted(names) != proc_names:
        raise RuntimeError("network interface inventories disagree")
    ipv6 = parse_ipv6_addresses(_read("/proc/self/net/if_inet6"), set(names))
    rows: list[dict[str, object]] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for index, name in sorted(interfaces, key=lambda item: item[1]):
            request = struct.pack("256s", name.encode("ascii"))
            flags_result = fcntl.ioctl(sock.fileno(), 0x8913, request)  # SIOCGIFFLAGS
            flags = struct.unpack_from("H", flags_result, 16)[0]
            try:
                address = fcntl.ioctl(sock.fileno(), 0x8915, request)  # SIOCGIFADDR
                primary_ipv4 = socket.inet_ntoa(address[20:24])
            except OSError as exc:
                if exc.errno != errno.EADDRNOTAVAIL:
                    raise  # Inspection failure is not evidence of no address.
                primary_ipv4 = None
            rows.append(
                {
                    "index": index,
                    "name": name,
                    "flags": flags,
                    "primary_ipv4": primary_ipv4,
                    "ipv6": ipv6[name],
                }
            )
    return {
        "interfaces": rows,
        "proc_interfaces": proc_names,
        "routes": parse_routes(_read("/proc/self/net/route"), _read("/proc/self/net/ipv6_route")),
        "connect_errno": _connect_errno(socket.AF_INET, ("198.51.100.1", 9)),
        "connect_errno_v6": _connect_errno(socket.AF_INET6, ("2001:db8::1", 9)),
    }


def network_isolated(value: object) -> bool:
    """Validate a closed raw observation; never infer absence from missing data."""
    if not isinstance(value, dict) or set(value) != {
        "interfaces",
        "proc_interfaces",
        "routes",
        "connect_errno",
        "connect_errno_v6",
    }:
        return False
    if value["routes"] != [] or any(
        type(value[key]) is not int or value[key] not in _UNREACHABLE
        for key in ("connect_errno", "connect_errno_v6")
    ):
        return False
    rows = value["interfaces"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_INTERFACES:
        return False
    names: set[str] = set()
    indices: set[int] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "index",
            "name",
            "flags",
            "primary_ipv4",
            "ipv6",
        }:
            return False
        name, index, flags = row["name"], row["index"], row["flags"]
        if (
            not _name(name)
            or name in names
            or type(index) is not int
            or not 0 < index < 2**31
            or index in indices
            or type(flags) is not int
            or not 0 <= flags <= 0xFFFF
        ):
            return False
        names.add(name)
        indices.add(index)
        ipv4, ipv6 = row["primary_ipv4"], row["ipv6"]
        if not isinstance(ipv6, list) or len(ipv6) > 256:
            return False
        if name == "lo":
            if flags & (_IFF_UP | _IFF_LOOPBACK) != (_IFF_UP | _IFF_LOOPBACK):
                return False
            try:
                if not isinstance(ipv4, str) or not ipaddress.IPv4Address(ipv4).is_loopback:
                    return False
                if any(
                    not isinstance(address, str) or not ipaddress.IPv6Address(address).is_loopback
                    for address in ipv6
                ):
                    return False
            except ValueError:
                return False
        elif flags & (_IFF_UP | _IFF_LOOPBACK | _IFF_RUNNING) or ipv4 is not None or ipv6:
            return False
    return "lo" in names and value["proc_interfaces"] == sorted(names)
