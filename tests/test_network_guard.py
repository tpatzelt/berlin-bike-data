"""Proves the autouse network guard in conftest.py actually trips."""

import socket

import pytest

from tests.conftest import NetworkBlockedError


def test_socket_connect_is_blocked():
    with pytest.raises(NetworkBlockedError):
        socket.socket().connect(("127.0.0.1", 80))


def test_socket_connect_ex_is_blocked():
    with pytest.raises(NetworkBlockedError):
        socket.socket().connect_ex(("127.0.0.1", 80))


def test_create_connection_is_blocked():
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(("127.0.0.1", 80))
