#!/usr/bin/env python3

import argparse
import functools
import ipaddress
import os
import pprint
import random
import time

import dns.query
import dns.resolver
import dns.reversename
import dns.zone

def query(resolver, domain, record_type='A'):
    try:
        return resolver.query(domain, record_type)
    except dns.resolver.NXDOMAIN:
        return None

def reverse_query(resolver, ip):
    return query(resolver, dns.reversename.from_address(ip), record_type='PTR')

def zone_transfer(address, domain):
    try:
        return dns.zone.from_xfr(dns.query.xfr(address, domain))
    except (ConnectionResetError, dns.exception.FormError):
        return None

def get_class_c_network(ip):
    ip = int(ip)
    floored = ipaddress.ip_address(ip - (ip % (2**8)))
    class_c = ipaddress.IPv4Network('{}/24'.format(floored))

    return class_c

def traverse_expander(ip, n=5):
    class_c = get_class_c_network(ip)

    result = [ipaddress.IPv4Address(ip + i) for i in range(-n, n + 1)]
    result = [i for i in result if i in class_c]

    return result

def wide_expander(ip):
    class_c = get_class_c_network(ip)

    result = list(class_c)

    return result

def search_filter(domains, address):
    return any(domain in address for domain in domains)

def find_nearby(resolver, ips, filter_func=None):
    reversed_ips = {str(i): reverse_query(resolver, str(i)) for i in ips}
    reversed_ips = {k: v for k, v in reversed_ips.items() if v is not None}

    if filter_func:
        reversed_ips = {k: v for k, v in reversed_ips.items() if filter_func(v[0].to_text())}

    if not reversed_ips:
        return

    print("Nearby:")
    pprint.pprint({k: v[0].to_text() for k, v in reversed_ips.items()})

def fierce(**kwargs):
    domain = kwargs['domain']

    resolver = dns.resolver.Resolver()

    nameservers = None
    if kwargs.get('dns_servers'):
        nameservers = kwargs['dns_servers']
    elif kwargs.get('dns_file'):
        nameservers = [ns.strip() for ns in open(kwargs["dns_file"]).readlines()]

    if nameservers:
        resolver.nameservers = nameservers

    if kwargs.get("range"):
        internal_range = ipaddress.IPv4Network(kwargs.get("range"))
        find_nearby(resolver, list(internal_range))

    if not kwargs.get("domain"):
        return

    ns = query(resolver, domain, record_type='NS')
    domain_name_servers = [n.to_text() for n in ns]
    print("NS: {}".format(" ".join(domain_name_servers)))

    soa = query(resolver, domain, record_type='SOA')
    soa_mname = soa[0].mname
    master = query(resolver, soa_mname, record_type='A')
    master_address = master[0].address
    print("SOA: {} ({})".format(soa_mname, master_address))

    zone = zone_transfer(master_address, domain)
    print("Zone: {}".format("success" if zone else "failure"))
    if zone:
        pprint.pprint({k: v.to_text(k) for k, v in zone.items()})
        return

    random_domain = "{}.{}".format(random.randint(1e10, 1e11), domain)
    wildcard = query(resolver, random_domain, record_type='A')
    print("Wildcard: {}".format("success" if wildcard else "failure"))

    if kwargs.get('subdomains'):
        subdomains = kwargs["subdomains"]
    else:
        subdomains = [sd.strip() for sd in open(kwargs["subdomain_file"]).readlines()]

    visited = set()

    for subdomain in subdomains:
        url = "{}.{}".format(subdomain, domain)
        record = query(resolver, url, record_type='A')

        if record is None:
            continue

        ip = ipaddress.IPv4Address(record[0].address)
        print("Found: {} ({})".format(url, ip))

        if kwargs.get("wide"):
            ips = wide_expander(ip)
        elif kwargs.get("traverse"):
            ips = traverse_expander(ip, kwargs["traverse"])
        else:
            continue

        filter_func = None
        if kwargs.get("search"):
            filter_func = functools.partial(search_filter, kwargs["search"])

        ips = set(ips) - set(visited)
        visited |= ips

        find_nearby(resolver, ips, filter_func=filter_func)

        if kwargs.get("delay"):
            time.sleep(kwargs["delay"])

def parse_args():
    p = argparse.ArgumentParser(description=
        '''
        A DNS reconnaissance tool for locating non-contiguous IP space.
        ''', formatter_class=argparse.RawTextHelpFormatter)

    p.add_argument('--domain', action='store',
        help='domain name to test')
    p.add_argument('--wide', action='store_true',
        help='scan entire class c of discovered records')
    p.add_argument('--traverse', action='store', type=int, default=5,
        help='scan IPs near discovered records, this won\'t enter adjacent class c\'s')
    p.add_argument('--search', action='store', nargs='+',
        help='filter on these domains when expanding lookup')
    p.add_argument('--range', action='store',
        help='scan an internal IP range, use cidr notation')
    p.add_argument('--delay', action='store', type=float, default=None,
        help='time to wait between lookups')

    subdomain_group = p.add_mutually_exclusive_group()
    subdomain_group.add_argument('--subdomains', action='store', nargs='+',
        help='use these subdomains')
    subdomain_group.add_argument('--subdomain-file', action='store',
        default=os.path.join("lists", "default.txt"),
        help='use subdomains specified in this file (one per line)')

    dns_group = p.add_mutually_exclusive_group()
    dns_group.add_argument('--dns-servers', action='store', nargs='+',
        help='use these dns servers for reverse lookups')
    dns_group.add_argument('--dns-file', action='store',
        help='use dns servers specified in this file for reverse lookups (one per line)')

    args = p.parse_args()
    return args

def main():
    args = parse_args()

    fierce(**vars(args))

if __name__ == "__main__":
    main()