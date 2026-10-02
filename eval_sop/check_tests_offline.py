"""Run the backend suite with DNS disabled to find tests that need the network.

    cd backend && python ../eval_sop/check_tests_offline.py
"""
import socket
import sys

import pytest


def _no_dns(*a, **k):
    raise socket.gaierror("DNS disabled by check_tests_offline.py")


socket.getaddrinfo = _no_dns
sys.exit(pytest.main(["tests", "-q", "-p", "no:cacheprovider"]))
