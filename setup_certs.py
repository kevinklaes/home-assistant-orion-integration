#!/usr/bin/env python3
"""
Generate a local CA and server TLS certificate for the Orion server mimic.

Usage:
    python setup_certs.py [--out-dir certs] [--extra-ip 192.168.1.100]

Output (all in --out-dir):
    ca.crt       Root CA certificate  ← install on devices / HA to trust the server
    ca.key       Root CA private key  ← keep secret
    server.crt   Server certificate (covers api1.orionbed.com + live.api1.orionbed.com)
    server.key   Server private key

After generating, install ca.crt as a trusted root on:
  - Home Assistant host:  sudo cp certs/ca.crt /usr/local/share/ca-certificates/orion-local-ca.crt && sudo update-ca-certificates
  - The physical device (if accessible): device-specific procedure
"""

from __future__ import annotations

import argparse
import datetime
import ipaddress
import os
import socket
import sys

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
except ImportError:
    print("ERROR: cryptography package not installed.", file=sys.stderr)
    print("Run: pip install cryptography", file=sys.stderr)
    sys.exit(1)

# Domains that the server certificate must cover
SERVER_DOMAINS = [
    "api1.orionbed.com",
    "live.api1.orionbed.com",
    "localhost",
]


def _write_pem(path: str, obj) -> None:
    if hasattr(obj, "private_bytes"):
        data = obj.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    else:
        data = obj.public_bytes(serialization.Encoding.PEM)
    with open(path, "wb") as f:
        f.write(data)
    print(f"  Wrote {path}")


def generate_ca(out_dir: str):
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Local Orion CA"),
        x509.NameAttribute(NameOID.COMMON_NAME, "Local Orion Root CA"),
    ])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True,
                content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    _write_pem(os.path.join(out_dir, "ca.key"), ca_key)
    _write_pem(os.path.join(out_dir, "ca.crt"), ca_cert)
    return ca_key, ca_cert


def generate_server_cert(
    out_dir: str,
    ca_key,
    ca_cert,
    domains: list[str],
    extra_ips: list[str],
):
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.now(datetime.timezone.utc)

    san_entries = [x509.DNSName(d) for d in domains]
    for ip_str in extra_ips:
        try:
            san_entries.append(x509.IPAddress(ipaddress.ip_address(ip_str)))
        except ValueError:
            print(f"  WARNING: skipping invalid IP SAN: {ip_str}", file=sys.stderr)

    server_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, domains[0]),
        ]))
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=825))  # Apple/browser limit
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_encipherment=True,
                content_commitment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=False, crl_sign=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    _write_pem(os.path.join(out_dir, "server.key"), server_key)
    _write_pem(os.path.join(out_dir, "server.crt"), server_cert)
    return server_key, server_cert


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", default="certs", help="Output directory (default: certs/)")
    parser.add_argument(
        "--extra-ip",
        action="append",
        default=[],
        metavar="IP",
        help="Extra IP address to include in the server cert SAN (repeatable). "
             "Your local server IP is detected automatically.",
    )
    args = parser.parse_args()

    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    # Auto-detect local machine IP
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = None

    extra_ips = list(args.extra_ip)
    auto_ips = ["127.0.0.1"]
    if local_ip and local_ip not in ("127.0.0.1", "::1") and local_ip not in extra_ips:
        auto_ips.append(local_ip)
    all_ips = list(dict.fromkeys(auto_ips + extra_ips))  # deduplicate, preserve order

    print(f"\nGenerating certificates in '{out_dir}/'...")
    print(f"  Domains: {', '.join(SERVER_DOMAINS)}")
    print(f"  IP SANs: {', '.join(all_ips)}")
    print()

    print("Generating CA...")
    ca_key, ca_cert = generate_ca(out_dir)

    print("\nGenerating server certificate...")
    generate_server_cert(out_dir, ca_key, ca_cert, SERVER_DOMAINS, all_ips)

    print(f"""
Done.

Next steps:
  1. Trust the CA on the Home Assistant machine:
       sudo cp {out_dir}/ca.crt /usr/local/share/ca-certificates/orion-local-ca.crt
       sudo update-ca-certificates

  2. (Optional) Install {out_dir}/ca.crt as a trusted root on your Orion device.
     Method depends on the device OS — see networking/README.md for guidance.

  3. Set up DNS redirection so api1.orionbed.com and live.api1.orionbed.com
     resolve to this machine's IP. See networking/README.md.

  4. Start the server:
       ORION_DEVICE_SERIALS=YOUR_SERIAL python run_local_server.py
""")


if __name__ == "__main__":
    main()
