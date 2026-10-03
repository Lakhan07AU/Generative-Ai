"""ONVIF camera discovery helper (WS-Discovery probe + profile fetch).

Discovers ONVIF-compliant cameras on the local network using WS-Discovery,
then - when a camera or host is given explicitly - pulls device identity using
the ``onvif`` PyPI package (optional dependency).

Because ONVIF NVRs expose their RTSP URLs through an authenticated
``GetProfiles``/``GetStreamUri`` call, every discovered profile is mapped to a
candidate ``rtsp_url`` that can be saved against a Camera row (the
``rtsp_url`` / ``rtsp_url_alt`` fields the auto-processing supervisor reads).

No camera is required to run this script: with no ``--host`` it performs a
multicast probe and reports what (if anything) answers. Hardware-bound checks
are reported honestly as ``NOT TESTED`` - never fabricated.

Usage:
    python scripts/discover_onvif_cameras.py                # WS-Discovery probe
    python scripts/discover_onvif_cameras.py --host 192.168.1.64
    python scripts/discover_onvif_cameras.py --host 192.168.1.64 \\
        --username admin --password secret --timeout 20 --onvif-port 8899
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
from xml.etree import ElementTree as ET

WS_DISCOVERY_TIMEOUT_DEFAULT = 5.0
ONVIF_PORT_DEFAULT = 80

_XNS_ENV = "http://www.w3.org/2003/05/soap-envelope"
_XNS_ADDR = "http://schemas.xmlsoap.org/ws/2004/08/addressing"


def _ws_discovery_probe(timeout: float = WS_DISCOVERY_TIMEOUT_DEFAULT) -> list[dict]:
    """Multicast WS-Discovery ``Probe`` and collect matching device replies."""
    payload = f"""<?xml version="1.0"?>
<e:Envelope xmlns:e="{_XNS_ENV}">
 <e:Header>
  <a:Action e:mustUnderstand="1">{_XNS_ADDR}/Probe</a:Action>
  <a:MessageID>uuid:forensic-ai-discover-0001</a:MessageID>
  <a:To e:mustUnderstand="0">urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To>
 </e:Header>
 <e:Body>
  <d:Probe xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
   <d:Types>dn:NetworkVideoTransmitter</d:Types>
  </d:Probe>
 </e:Body>
</e:Envelope>""".encode("utf-8")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    out: list[dict] = []
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for target in ("239.255.255.250", "255.255.255.255"):
            try:
                sock.sendto(payload, (target, 3702))
            except OSError:
                continue
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, peer = sock.recvfrom(65535)
            except socket.timeout:
                break
            if peer[0].startswith("127."):
                continue
            entry: dict = {"ip": peer[0], "port": peer[1], "bytes": len(data), "xml": False}
            try:
                ET.fromstring(data)
                entry["xml"] = True
            except ET.ParseError:
                pass
            out.append(entry)
    except OSError as exc:
        sys.stderr.write(f"  [FAIL] WS-Discovery probe failed: {exc}\n")
    finally:
        sock.close()
    return out


def _fetch_profiles(host: str, port: int, username: str, password: str, timeout: float) -> dict:
    """Fetch device identity + RTSP stream URIs via the optional ``onvif`` lib."""
    try:
        from onvif import ONVIFCamera
    except ImportError as exc:
        return {
            "error": "onvif package not installed (pip install onvif-zeep); "
            "identity fetch needs the optional dependency",
            "caused_by": "dep",
        }
    try:
        cam = ONVIFCamera(host, port, username, password)
        dev = cam.create_devicemgmt_service()
        info = dev.GetDeviceInformation()
        media = cam.create_media_service()
        profiles = media.GetProfiles()
        streams = []
        for prof in profiles:
            stream_uri = media.GetStreamUri({
                "StreamSetup": {"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}},
                "ProfileToken": prof.token,
            })
            streams.append({
                "profile": getattr(prof, "Name", None) or getattr(prof, "token", None),
                "rtsp_url": getattr(stream_uri, "Uri", None),
            })
        return {"info": info, "streams": streams}
    except Exception as exc:  # noqa: BLE001 - camera/contact failure
        return {"error": f"{exc}", "caused_by": "contact"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default=None, help="known ONVIF device IP to profile-fetch")
    ap.add_argument("--onvif-port", type=int, default=ONVIF_PORT_DEFAULT)
    ap.add_argument("--username", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--timeout", type=float, default=WS_DISCOVERY_TIMEOUT_DEFAULT)
    args = ap.parse_args(argv)

    print("== ONVIF camera discovery ==\n")
    print("  [ON]  multicast WS-Discovery probe (239.255.255.250:3702)\n")
    found = _ws_discovery_probe(args.timeout)

    if not found:
        print("  [NOT TESTED] no WS-Discovery responders found on this network")
        print("               - nothing answered the multicast probe. Either no ONVIF")
        print("                 device is present, or the probe is blocked by the LAN.")
    else:
        print(f"  [PASS] {len(found)} device(s) answered the probe:")
        for dev in found:
            print(f"         * {dev['ip']}:{dev['port']} (xml={dev.get('xml')})")

    print()
    fetch_result: dict = {}
    if args.host:
        print(f"== profile fetch from {args.host}:{args.onvif_port} ==\n")
        fetch_result = _fetch_profiles(args.host, args.onvif_port, args.username, args.password, args.timeout)
        if "error" in fetch_result:
            if fetch_result.get("caused_by") == "dep":
                print(f"  [NOT TESTED] {fetch_result['error']}")
            else:
                print(f"  [FAIL] profile fetch: {fetch_result['error']}")
                print("         the device did not complete GetDeviceInformation/GetProfiles -")
                print("         check the host, credentials and SOAP port.")
        else:
            identity = fetch_result.get("info", {})
            print("  [PASS] device identity fetched:")
            for key in ("Manufacturer", "Model", "FirmwareVersion", "SerialNumber"):
                print(f"         {key}: {getattr(identity, key, 'n/a') if not isinstance(identity, dict) else identity.get(key, 'n/a')}")
            streams = fetch_result.get("streams", [])
            if not streams:
                print("  [FAIL] no RTSP profiles were returned by GetProfiles")
            else:
                print(f"  [PASS] {len(streams)} RTSP profile(s):")
                for s in streams:
                    print(f"         - {s['profile']}: {s['rtsp_url']}")
    else:
        print("  note: use --host to fetch identity + RTSP URLs from a specific camera")

    profile_ok = "error" not in fetch_result and bool(fetch_result.get("streams")) and args.host
    print()
    print("  verdicts:")
    print(f"    WS-Discovery probe : {'PASS' if found else 'NOT TESTED'}")
    print(f"    Profile fetch       : {'PASS' if profile_ok else ('NOT TESTED' if not args.host else 'FAIL')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())