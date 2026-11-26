"""Turning a MAC address into a hardware vendor, offline.

The first three octets of a MAC are the Organisationally Unique Identifier the
IEEE assigns to a manufacturer. The full registry is ~35,000 entries; NetPulse
ships the prefixes that actually show up on home and office networks so device
discovery works with no download and no network call.
"""

from __future__ import annotations

# OUI prefix (lower-case, colon separated) -> vendor
VENDORS: dict[str, str] = {
    "00:03:93": "Apple", "00:0a:27": "Apple", "00:17:f2": "Apple",
    "00:1b:63": "Apple", "00:1e:c2": "Apple", "00:25:00": "Apple",
    "3c:07:54": "Apple", "40:a6:d9": "Apple", "58:55:ca": "Apple",
    "7c:d1:c3": "Apple", "a4:83:e7": "Apple", "ac:bc:32": "Apple",
    "d0:81:7a": "Apple", "f0:18:98": "Apple", "f4:5c:89": "Apple",
    "00:16:cb": "Apple", "8c:85:90": "Apple", "dc:a9:04": "Apple",

    "00:1a:11": "Google", "3c:5a:b4": "Google", "94:eb:2c": "Google",
    "f4:f5:d8": "Google", "f4:f5:e8": "Google", "da:a1:19": "Google",
    "00:1a:22": "Google Nest", "18:b4:30": "Google Nest",

    "00:15:5d": "Microsoft (Hyper-V)", "00:50:f2": "Microsoft",
    "28:18:78": "Microsoft", "7c:1e:52": "Microsoft", "50:1a:c5": "Microsoft",

    "00:05:69": "VMware", "00:0c:29": "VMware", "00:1c:14": "VMware",
    "00:50:56": "VMware", "08:00:27": "VirtualBox", "52:54:00": "QEMU/KVM",
    "02:42:ac": "Docker", "00:16:3e": "Xen",

    "00:1d:0f": "TP-Link", "14:cc:20": "TP-Link", "50:c7:bf": "TP-Link",
    "a4:2b:b0": "TP-Link", "b0:48:7a": "TP-Link", "c0:25:e9": "TP-Link",
    "e8:de:27": "TP-Link", "f4:f2:6d": "TP-Link", "30:de:4b": "TP-Link",

    "00:18:e7": "D-Link", "00:1b:11": "D-Link", "14:d6:4d": "D-Link",
    "78:54:2e": "D-Link", "c8:be:19": "D-Link", "ac:f1:df": "D-Link",

    "00:09:5b": "Netgear", "00:14:6c": "Netgear", "20:4e:7f": "Netgear",
    "a0:40:a0": "Netgear", "c0:3f:0e": "Netgear", "e0:46:9a": "Netgear",

    "00:0c:e7": "MediaTek", "00:1c:df": "Belkin", "94:10:3e": "Belkin",
    "00:24:01": "D-Link", "00:26:5a": "D-Link",

    "00:1d:7e": "Cisco-Linksys", "00:25:9c": "Cisco-Linksys",
    "48:f8:b3": "Cisco-Linksys", "00:1a:70": "Cisco-Linksys",
    "00:0b:86": "Aruba", "24:de:c6": "Aruba", "00:1c:b3": "Cisco",
    "00:23:04": "Cisco", "00:26:99": "Cisco", "70:79:b3": "Cisco Meraki",

    "00:15:6d": "Ubiquiti", "24:a4:3c": "Ubiquiti", "44:d9:e7": "Ubiquiti",
    "78:8a:20": "Ubiquiti", "b4:fb:e4": "Ubiquiti", "fc:ec:da": "Ubiquiti",
    "74:83:c2": "Ubiquiti", "e0:63:da": "Ubiquiti",

    "00:0e:8f": "Sercomm", "00:1e:a6": "Best IT World", "d8:47:32": "Huawei",
    "00:18:82": "Huawei", "00:25:9e": "Huawei", "48:46:fb": "Huawei",
    "70:72:3c": "Huawei", "e0:24:7f": "Huawei", "ac:e3:42": "Huawei",

    "00:12:fb": "Samsung", "00:1d:25": "Samsung", "34:23:ba": "Samsung",
    "5c:0a:5b": "Samsung", "78:1f:db": "Samsung", "8c:77:12": "Samsung",
    "a0:21:95": "Samsung", "bc:20:a4": "Samsung", "e8:50:8b": "Samsung",
    "f0:25:b7": "Samsung", "1c:5a:3e": "Samsung",

    "00:1a:8a": "Xiaomi", "28:6c:07": "Xiaomi", "34:ce:00": "Xiaomi",
    "64:09:80": "Xiaomi", "78:11:dc": "Xiaomi", "8c:be:be": "Xiaomi",
    "f8:a4:5f": "Xiaomi", "50:8f:4c": "Xiaomi", "ac:c1:ee": "Xiaomi",

    "00:1e:42": "Teltonika", "00:e0:4c": "Realtek", "52:54:ab": "Realtek",
    "00:07:32": "Aaeon", "00:04:4b": "NVIDIA", "48:b0:2d": "NVIDIA",

    "00:1b:44": "SanDisk", "00:0d:3a": "Microsoft Azure",
    "00:24:d7": "Intel", "34:13:e8": "Intel", "3c:a9:f4": "Intel",
    "5c:51:4f": "Intel", "7c:5c:f8": "Intel", "94:65:9c": "Intel",
    "a4:c4:94": "Intel", "e4:a4:71": "Intel", "f8:63:3f": "Intel",
    "00:1f:3b": "Intel", "88:53:2e": "Intel",

    "00:1f:16": "Wistron", "00:26:b6": "Askey", "00:1c:c0": "Intel",
    "b8:27:eb": "Raspberry Pi", "dc:a6:32": "Raspberry Pi",
    "e4:5f:01": "Raspberry Pi", "28:cd:c1": "Raspberry Pi",
    "2c:cf:67": "Raspberry Pi",

    "00:17:88": "Philips Hue", "ec:b5:fa": "Philips Hue",
    "18:74:2e": "Amazon", "44:65:0d": "Amazon", "68:54:fd": "Amazon",
    "74:c2:46": "Amazon", "fc:65:de": "Amazon", "ac:63:be": "Amazon",
    "00:bb:3a": "Amazon", "40:b4:cd": "Amazon",

    "00:04:20": "Slim Devices", "00:09:0f": "Fortinet", "70:4c:a5": "Fortinet",
    "00:1a:1e": "Aruba", "6c:f3:7f": "Aruba", "00:0f:b5": "Netgear",

    "00:21:cc": "Foxconn", "00:24:7e": "Foxconn", "90:2b:34": "Giga-Byte",
    "1c:1b:0d": "Giga-Byte", "00:1f:c6": "ASUS", "2c:56:dc": "ASUS",
    "38:d5:47": "ASUS", "50:46:5d": "ASUS", "ac:22:0b": "ASUS",
    "d8:50:e6": "ASUS", "04:d9:f5": "ASUS", "1c:87:2c": "ASUS",

    "00:1e:68": "Wistron", "00:26:c7": "Intel", "00:22:68": "Hon Hai",
    "b8:ac:6f": "Dell", "00:14:22": "Dell", "18:03:73": "Dell",
    "d4:be:d9": "Dell", "f8:bc:12": "Dell", "00:1e:c9": "Dell",

    "00:23:ae": "Dell", "3c:d9:2b": "HP", "00:1f:29": "HP",
    "00:25:b3": "HP", "9c:8e:99": "HP", "b4:b5:2f": "HP", "e4:11:5b": "HP",

    "00:1c:42": "Parallels", "00:16:3f": "Cradlepoint",
    "00:0f:60": "Lenovo", "00:12:fe": "Lenovo", "54:ee:75": "Lenovo",
    "68:f7:28": "Lenovo", "8c:16:45": "Lenovo",

    "00:11:32": "Synology", "00:1b:21": "Intel", "90:09:d0": "Synology",
    "00:08:9b": "ICP Electronics", "24:5e:be": "QNAP", "00:0e:c6": "ASIX",

    "00:13:10": "Cisco-Linksys", "58:ef:68": "Belkin/Wemo",
    "d0:73:d5": "LIFX", "cc:b8:a8": "Wyze", "2c:aa:8e": "Sonos",
    "00:0e:58": "Sonos", "5c:aa:fd": "Sonos", "94:9f:3e": "Sonos",

    "64:16:66": "Nest", "00:1a:79": "Roku",
    "b0:a7:37": "Roku", "cc:6d:a0": "Roku", "d8:31:34": "Roku",
    "ac:3a:7a": "Roku", "00:0d:4b": "Roku",

    "00:04:f2": "Polycom", "64:16:7f": "Polycom", "00:1a:e8": "Unify",
    "00:60:b9": "NEC", "00:09:7b": "Cisco", "00:1e:bd": "Cisco",
}


def normalise(mac: str) -> str | None:
    """Return ``aa:bb:cc:dd:ee:ff`` form, or ``None`` if this is not a MAC."""
    if not mac:
        return None
    cleaned = mac.strip().lower().replace("-", ":").replace(".", ":")
    parts = [p for p in cleaned.split(":") if p]
    if len(parts) != 6 or not all(len(p) <= 2 and _is_hex(p) for p in parts):
        return None
    return ":".join(p.zfill(2) for p in parts)


def lookup(mac: str) -> str:
    """Vendor for a MAC address, or a descriptive fallback."""
    normalised = normalise(mac)
    if normalised is None:
        return "Unknown"

    prefix = normalised[:8]
    vendor = VENDORS.get(prefix)
    if vendor:
        return vendor

    # Bit 1 of the first octet marks a locally administered address: a made-up
    # MAC, which is exactly what phones use for Wi-Fi privacy.
    try:
        first_octet = int(normalised[:2], 16)
    except ValueError:
        return "Unknown"
    if first_octet & 0b10:
        return "Randomised MAC"
    return "Unknown"


def _is_hex(value: str) -> bool:
    try:
        int(value, 16)
        return True
    except ValueError:
        return False
