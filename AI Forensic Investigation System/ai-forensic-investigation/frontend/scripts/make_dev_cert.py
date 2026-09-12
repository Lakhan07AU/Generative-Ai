"""Generate a self-signed certificate for the local HTTPS dev server.

Usage: python scripts/make_dev_cert.py --ip 10.121.240.164 [--host localhost]
Writes cert.pem + key.pem next to the script (frontend/scripts/) and prints
how to trust it on PC + phone. Uses the `cryptography` package (no openssl
dependency) so it runs on stock Windows Python.

The phone only needs to *temporarily* trust the certificate; the PC can add it
to the system trust store so Chrome/Firefox stop warning. The certificate is a
dev-only artifact shipped nowhere.
"""

import argparse
import datetime
import ipaddress
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

OUT = Path(__file__).resolve().parent


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ip", default="127.0.0.1", help="PC LAN IPv4 for phone access")
    p.add_argument("--host", default="localhost")
    p.add_argument("--days", type=int, default=365)
    args = p.parse_args()

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.now(datetime.timezone.utc)

    san_entries = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    if args.host not in ("localhost", "127.0.0.1"):
        try:
            san_entries.append(x509.IPAddress(ipaddress.ip_address(args.host)))
        except ValueError:
            san_entries.append(x509.DNSName(args.host))
    try:
        ip = ipaddress.ip_address(args.ip)
        san_entries.append(x509.IPAddress(ip))
        san_entries.append(x509.DNSName(str(ip)))
    except ValueError:
        san_entries.append(x509.DNSName(args.ip))

    if args.host.lower() != "localhost":
        san_entries.append(x509.DNSName(args.host))

    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "AI Forensics Dev")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=args.days))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .sign(key, hashes.SHA256())
    )

    (OUT / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (OUT / "key.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    print(f"Wrote {OUT / 'cert.pem'} and {OUT / 'key.pem'}")
    print("PC trust (PowerShell, admin):")
    print("  Import-Certificate -FilePath 'frontend/scripts/cert.pem' -CertStoreLocation Cert:/LocalMachine/Root")
    print("Phone: e-mail the cert.pem to the phone, install it as a CA cert,")
    print("  or accept the 'Your connection is not private' warning once.")


if __name__ == "__main__":
    main()