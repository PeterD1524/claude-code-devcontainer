#!/usr/sbin/python
import ipaddress
import json
import re
import subprocess

# 1. Extract Docker DNS info BEFORE any flushing
process = subprocess.run(
    ["iptables-save", "-t", "nat"], stdout=subprocess.PIPE, check=True, text=True
)
DOCKER_DNS_RULES = list[str]()
for line in process.stdout.splitlines():
    if "127.0.0.11" in line:
        DOCKER_DNS_RULES.append(line)

# Flush existing rules and delete existing ipsets
subprocess.run(["iptables", "-F"], check=True)
subprocess.run(["iptables", "-X"], check=True)
subprocess.run(["iptables", "-t", "nat", "-F"], check=True)
subprocess.run(["iptables", "-t", "nat", "-X"], check=True)
subprocess.run(["iptables", "-t", "mangle", "-F"], check=True)
subprocess.run(["iptables", "-t", "mangle", "-X"], check=True)
subprocess.run(["ipset", "destroy", "allowed-domains"], stderr=subprocess.DEVNULL)

# 2. Selectively restore ONLY internal Docker DNS resolution
if DOCKER_DNS_RULES:
    print("Restoring Docker DNS rules...")
    subprocess.run(
        ["iptables", "-t", "nat", "-N", "DOCKER_OUTPUT"], stderr=subprocess.DEVNULL
    )
    subprocess.run(
        ["iptables", "-t", "nat", "-N", "DOCKER_POSTROUTING"], stderr=subprocess.DEVNULL
    )
    for line in DOCKER_DNS_RULES:
        subprocess.run(["iptables", "-t", "nat", *line.split()])
else:
    print("No Docker DNS rules to restore")


# First allow DNS and localhost before any restrictions
# Allow outbound DNS
subprocess.run(
    ["iptables", "-A", "OUTPUT", "-p", "udp", "--dport", "53", "-j", "ACCEPT"],
    check=True,
)
# Allow inbound DNS responses
subprocess.run(
    ["iptables", "-A", "INPUT", "-p", "udp", "--sport", "53", "-j", "ACCEPT"],
    check=True,
)
# Allow outbound SSH
subprocess.run(
    ["iptables", "-A", "OUTPUT", "-p", "tcp", "--dport", "22", "-j", "ACCEPT"],
    check=True,
)
# Allow inbound SSH responses
subprocess.run(
    [
        "iptables",
        "-A",
        "INPUT",
        "-p",
        "tcp",
        "--sport",
        "22",
        "-m",
        "state",
        "--state",
        "ESTABLISHED",
        "-j",
        "ACCEPT",
    ],
    check=True,
)
# Allow localhost
subprocess.run(["iptables", "-A", "INPUT", "-i", "lo", "-j", "ACCEPT"], check=True)
subprocess.run(["iptables", "-A", "OUTPUT", "-o", "lo", "-j", "ACCEPT"], check=True)


# Create ipset with CIDR support
subprocess.run(["ipset", "create", "allowed-domains", "hash:net"], check=True)

# Fetch GitHub meta information and aggregate + add their IP ranges
print("Fetching GitHub IP ranges...")
process = subprocess.run(
    ["curl", "-s", "https://api.github.com/meta"], stdout=subprocess.PIPE, check=True
)
if not process.stdout:
    print("ERROR: Failed to fetch GitHub IP ranges")
    exit(1)
gh_ranges = json.loads(process.stdout)
if not (
    isinstance(gh_ranges, dict)
    and all(key in gh_ranges for key in ("web", "api", "git"))
):
    print("ERROR: GitHub API response missing required fields")
    exit(1)

print("Processing GitHub IPs...")
addresses = list[ipaddress.IPv4Network]()
for key in ("web", "api", "git"):
    o = gh_ranges[key]
    assert isinstance(o, list)
    for cidr in o:
        assert isinstance(cidr, str)
        try:
            address = ipaddress.IPv4Network(cidr)
        except ipaddress.AddressValueError:
            continue
        addresses.append(address)
for cidr in ipaddress.collapse_addresses(addresses):
    if (
        re.fullmatch(
            r"^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}/[0-9]{1,2}$", str(cidr)
        )
        is None
    ):
        print("ERROR: Invalid CIDR range from GitHub meta: {}".format(cidr))
        exit(1)
    print("Adding GitHub range {}".format(cidr))
    subprocess.run(["ipset", "add", "allowed-domains", str(cidr)], check=True)

# Resolve and add other allowed domains
for domain in (
    "registry.npmjs.org",
    "api.anthropic.com",
    "sentry.io",
    "statsig.anthropic.com",
    "statsig.com",
    "crates.io",
    "dioxuslabs.com",
    "docs.astral.sh",
    "docs.rs",
    "nodejs.org",
    "npm.jsr.io",
    "zod.dev",
):
    print("Resolving {}...".format(domain))
    process = subprocess.run(
        ["dig", "+noall", "+answer", "A", domain],
        stdout=subprocess.PIPE,
        check=True,
        text=True,
    )
    ips = list[str]()
    for line in process.stdout.splitlines():
        split = line.split()
        if split[3] == "A":
            ips.append(split[4])
    if not ips:
        print("ERROR: Failed to resolve {}".format(domain))
        exit(1)
    for ip in ips:
        if (
            re.fullmatch(r"^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$", ip)
            is None
        ):
            print("ERROR: Invalid IP from DNS for {}: {}".format(domain, ip))
            exit(1)
        print("Adding {} for {}".format(ip, domain))
        subprocess.run(["ipset", "add", "allowed-domains", ip], check=True)

# Get host IP from default route
HOST_IP = None
process = subprocess.run(["ip", "route"], stdout=subprocess.PIPE, check=True, text=True)
for line in process.stdout.splitlines():
    if "default" in line:
        assert HOST_IP is None
        HOST_IP = line.split()[2]
if not HOST_IP:
    print("ERROR: Failed to detect host IP")
    exit(1)

HOST_NETWORK = re.sub(r"\.[0-9]*$", ".0/24", HOST_IP)
print("Host network detected as: {}".format(HOST_NETWORK))

# Set up remaining iptables rules
subprocess.run(
    ["iptables", "-A", "INPUT", "-s", HOST_NETWORK, "-j", "ACCEPT"], check=True
)
subprocess.run(
    ["iptables", "-A", "OUTPUT", "-d", HOST_NETWORK, "-j", "ACCEPT"], check=True
)

# Set default policies to DROP first
subprocess.run(["iptables", "-P", "INPUT", "DROP"], check=True)
subprocess.run(["iptables", "-P", "FORWARD", "DROP"], check=True)
subprocess.run(["iptables", "-P", "OUTPUT", "DROP"], check=True)

# First allow established connections for already approved traffic
subprocess.run(
    [
        "iptables",
        "-A",
        "INPUT",
        "-m",
        "state",
        "--state",
        "ESTABLISHED,RELATED",
        "-j",
        "ACCEPT",
    ],
    check=True,
)
subprocess.run(
    [
        "iptables",
        "-A",
        "OUTPUT",
        "-m",
        "state",
        "--state",
        "ESTABLISHED,RELATED",
        "-j",
        "ACCEPT",
    ],
    check=True,
)

# Then allow only specific outbound traffic to allowed domains
subprocess.run(
    [
        "iptables",
        "-A",
        "OUTPUT",
        "-m",
        "set",
        "--match-set",
        "allowed-domains",
        "dst",
        "-j",
        "ACCEPT",
    ],
    check=True,
)

# Explicitly REJECT all other outbound traffic for immediate feedback
subprocess.run(
    [
        "iptables",
        "-A",
        "OUTPUT",
        "-j",
        "REJECT",
        "--reject-with",
        "icmp-admin-prohibited",
    ],
    check=True,
)

print("Firewall configuration complete")
print("Verifying firewall rules...")
process = subprocess.run(
    ["curl", "--connect-timeout", "5", "https://example.com"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
if not process.returncode:
    print("ERROR: Firewall verification failed - was able to reach https://example.com")
    exit(1)
else:
    print(
        "Firewall verification passed - unable to reach https://example.com as expected"
    )

# Verify GitHub API access
process = subprocess.run(
    ["curl", "--connect-timeout", "5", "https://api.github.com/zen"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
if process.returncode:
    print(
        "ERROR: Firewall verification failed - unable to reach https://api.github.com"
    )
    exit(1)
else:
    print(
        "Firewall verification passed - able to reach https://api.github.com as expected"
    )
