"""自签证书生成脚本（服务端 HTTPS/WSS 用）。

用法（在 backend/ 目录下执行）：
    python tools/gen_self_signed_cert.py                    # 生成 certs/server.crt + certs/server.key
    python tools/gen_self_signed_cert.py --days 3650        # 指定有效期
    python tools/gen_self_signed_cert.py --host 192.168.5.5 --host camera.local
    python tools/gen_self_signed_cert.py --force            # 覆盖已存在的证书

生成后把 config.json 的 tls 块打开即可（或在「服务配置」页面勾选 HTTPS）：
    "tls": { "enabled": true, "cert_file": "certs/server.crt", "key_file": "certs/server.key" }

实现说明：优先用 openssl 命令行（Git for Windows 自带 C:\\Program Files\\Git\\usr\\bin\\openssl.exe，
脚本会自动探测常见路径）；若环境里装了 cryptography 库则直接用 Python 生成，无需外部命令。
两者都没有时会给出明确的安装提示而不是静默失败。
"""
import argparse
import ipaddress
import os
import shutil
import subprocess
import sys

DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "certs")
CERT_NAME = "server.crt"
KEY_NAME = "server.key"

# openssl 常见安装位置（Windows 上 Git 自带一份，系统 PATH 里通常没有）
_OPENSSL_HINTS = (
    r"C:\Program Files\Git\usr\bin\openssl.exe",
    r"C:\Program Files\Git\mingw64\bin\openssl.exe",
    r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
    r"C:\Program Files (x86)\OpenSSL-Win32\bin\openssl.exe",
    "/usr/bin/openssl",
    "/usr/local/bin/openssl",
    "/opt/homebrew/bin/openssl",
)


def find_openssl() -> str:
    """定位 openssl：先 PATH，再常见安装目录。找不到返回空串。"""
    hit = shutil.which("openssl")
    if hit:
        return hit
    for path in _OPENSSL_HINTS:
        if os.path.exists(path):
            return path
    return ""


def build_san(hosts) -> str:
    """构造 SAN（subjectAltName）：IP 用 IP:，其余按 DNS:（浏览器/客户端校验主机名时必需）。"""
    entries = []
    for h in hosts:
        try:
            ipaddress.ip_address(h)
            entries.append(f"IP:{h}")
        except ValueError:
            entries.append(f"DNS:{h}")
    return ",".join(entries)


def gen_with_openssl(openssl: str, cert_path: str, key_path: str, days: int, hosts) -> None:
    """调用 openssl 生成自签证书（RSA 2048 / SHA-256，带 SAN）。"""
    san = build_san(hosts)
    cmd = [
        openssl, "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes",
        "-keyout", key_path, "-out", cert_path, "-days", str(days),
        "-subj", "/C=CN/O=AIVisual/CN=" + hosts[0],
        "-addext", f"subjectAltName={san}",
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return
    except subprocess.CalledProcessError as e1:
        err1 = (e1.stderr or "").strip()
    except TypeError:
        err1 = ""
    # 退化路径：用临时 openssl 配置声明 SAN（不支持 -addext 的旧版本）
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".cnf", delete=False, encoding="utf-8") as f:
        f.write(
            "[req]\ndistinguished_name=dn\nx509_extensions=v3_req\nprompt=no\n"
            f"[dn]\nC=CN\nO=AIVisual\nCN={hosts[0]}\n"
            f"[v3_req]\nsubjectAltName={san}\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n"
        )
        cfg = f.name
    try:
        cmd = [
            openssl, "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes",
            "-keyout", key_path, "-out", cert_path, "-days", str(days),
            "-config", cfg,
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e2:
        raise RuntimeError(f"openssl 生成失败：{(e2.stderr or err1 or '').strip()}") from e2
    finally:
        try:
            os.unlink(cfg)
        except OSError:
            pass


def gen_with_cryptography(cert_path: str, key_path: str, days: int, hosts) -> None:
    """用 cryptography 库在 Python 内生成自签证书（无需外部命令）。"""
    import datetime
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    alt = []
    for h in hosts:
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            alt.append(x509.DNSName(h))
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AIVisual"),
        x509.NameAttribute(NameOID.COMMON_NAME, hosts[0]),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(alt), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def collect_default_hosts() -> list:
    """默认 SAN：本机回环 + 全部本机 IPv4（局域网访问时常按 IP 访问，必须进 SAN）。"""
    hosts = ["localhost", "127.0.0.1"]
    try:
        import socket
        name = socket.gethostname()
        if name and name not in hosts:
            hosts.append(name)
        for info in socket.getaddrinfo(name, None):
            ip = info[4][0]
            if ip and ip not in hosts and ":" not in ip:
                hosts.append(ip)
    except Exception:
        pass
    return hosts


def main() -> int:
    parser = argparse.ArgumentParser(description="生成服务端自签证书（HTTPS/WSS）")
    parser.add_argument("--dir", default=DEFAULT_DIR, help=f"输出目录（默认 {DEFAULT_DIR}）")
    parser.add_argument("--days", type=int, default=3650, help="有效期天数（默认 3650）")
    parser.add_argument("--host", action="append", default=[], dest="hosts",
                        help="证书覆盖的主机名/IP，可重复；默认取 localhost + 本机所有 IPv4")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的证书")
    args = parser.parse_args()

    hosts = args.hosts or collect_default_hosts()
    os.makedirs(args.dir, exist_ok=True)
    cert_path = os.path.join(args.dir, CERT_NAME)
    key_path = os.path.join(args.dir, KEY_NAME)

    if not args.force and (os.path.exists(cert_path) or os.path.exists(key_path)):
        print(f"证书已存在：{cert_path} / {key_path}\n如需重新生成请加 --force")
        return 1

    print(f"生成自签证书：{'、'.join(hosts)}（有效期 {args.days} 天）")
    openssl = find_openssl()
    try:
        if openssl:
            print(f"使用 openssl：{openssl}")
            gen_with_openssl(openssl, cert_path, key_path, args.days, hosts)
        else:
            try:
                import cryptography  # noqa: F401
            except ImportError:
                print("未找到 openssl，也未安装 cryptography 库，无法生成证书。\n"
                      "请任选其一：\n"
                      "  1) 安装 Git for Windows（自带 openssl）或 OpenSSL；\n"
                      "  2) pip install cryptography 后重跑本脚本。", file=sys.stderr)
                return 2
            print("使用 cryptography 库生成")
            gen_with_cryptography(cert_path, key_path, args.days, hosts)
    except Exception as e:  # noqa: BLE001
        print(f"生成失败：{e}", file=sys.stderr)
        return 2

    print(f"完成：\n  证书 {cert_path}\n  私钥 {key_path}\n"
          f"接下来把 config.json 的 tls 打开（或在「服务配置」页勾选 HTTPS）：\n"
          f'  "tls": {{ "enabled": true, "cert_file": "{os.path.relpath(cert_path).replace(os.sep, "/")}", '
          f'"key_file": "{os.path.relpath(key_path).replace(os.sep, "/")}" }}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
