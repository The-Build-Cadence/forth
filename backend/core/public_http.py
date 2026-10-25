"""Bounded public HTTP reads with DNS pinned to a validated address.

Never use this transport for authenticated provider APIs or internal services.
"""
import ipaddress
import socket
import time
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter


def public_addresses(url):
    parsed = urlsplit(url)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username or parsed.password
            or parsed.port not in {None, 80, 443}):
        raise ValueError('Use a public HTTP(S) URL without credentials or custom ports.')
    try:
        addresses = sorted({row[4][0] for row in socket.getaddrinfo(
            parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80),
            type=socket.SOCK_STREAM)})
    except socket.gaierror as exc:
        raise ValueError('The source hostname could not be resolved.') from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global
                            or ipaddress.ip_address(address).is_multicast for address in addresses):
        raise ValueError('Source URLs must resolve only to public network addresses.')
    return parsed, addresses


class PublicAddressAdapter(HTTPAdapter):
    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        parsed, addresses = public_addresses(request.url)
        host_params, pool_kwargs = self.build_connection_pool_key_attributes(request, verify, cert)
        host_params['host'] = addresses[0]
        request.headers['Host'] = parsed.netloc
        if parsed.scheme == 'https':
            pool_kwargs.update(server_hostname=parsed.hostname, assert_hostname=parsed.hostname)
        return self.poolmanager.connection_from_host(**host_params, pool_kwargs=pool_kwargs)


def public_get(url, *, timeout=8, headers=None, max_bytes=2_000_000, **kwargs):
    # Redirects must be revalidated explicitly by callers. Ignore proxy/netrc env.
    with requests.Session() as session:
        session.trust_env = False
        adapter = PublicAddressAdapter(max_retries=0)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        started = time.monotonic()
        with session.get(url, timeout=timeout, headers=headers, stream=True,
                         allow_redirects=False) as response:
            content = bytearray()
            for chunk in response.iter_content(chunk_size=16384):
                content.extend(chunk)
                if len(content) > max_bytes or time.monotonic() - started > 30:
                    raise ValueError('Public response exceeded the size or time limit.')
            response._content = bytes(content)
            response._content_consumed = True
            return response
