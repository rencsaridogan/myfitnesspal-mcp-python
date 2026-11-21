"""Tests for the eating time on diary adds and mfp_set_entry_time.

Pure: the network is faked. Pins the request shapes verified live on
2026-11-21 against a throwaway test entry: POST /v2/diary accepts
`consumed_at` on the item, and PATCH /v2/diary/{id} with
{"item": {"consumed_at": ...}} answers 204 and changes only the time.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mfp_mcp import server  # noqa: E402


class _Response:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class _Session:
    def __init__(self, status=204):
        self.status = status
        self.calls = []

    def post(self, url, data=None, **kwargs):
        self.calls.append(("POST", url, json.loads(data)))
        return _Response(201, {"items": [{"id": "e-1"}]})

    def patch(self, url, data=None, **kwargs):
        self.calls.append(("PATCH", url, json.loads(data)))
        return _Response(self.status)


@pytest.fixture
def client(monkeypatch):
    c = SimpleNamespace(session=_Session())
    monkeypatch.setattr(server, "_mfp_api_headers", lambda *a, **k: {})
    monkeypatch.setattr(server, "get_food_v2", lambda _c, _id: {"id": 7, "version": "v1"})
    monkeypatch.setattr(server, "select_serving_size", lambda _f, _u: {"value": 1.0, "unit": "meal"})
    monkeypatch.setattr(server, "get_meal_names", lambda _c, _d: ["Breakfast", "Lunch"])
    return c


def test_add_with_time_sends_consumed_at(client):
    server.add_food_to_diary(client, "7", "Breakfast", date(2026, 11, 21), time="11:00")
    _, _, body = client.session.calls[0]
    assert body["items"][0]["consumed_at"] == "11:00:00"


def test_add_without_time_sends_no_consumed_at(client):
    server.add_food_to_diary(client, "7", "Breakfast", date(2026, 11, 21))
    _, _, body = client.session.calls[0]
    assert "consumed_at" not in body["items"][0]


def test_set_entry_time_patches_only_consumed_at(client):
    server.set_entry_time(client, "abc", "13:30")
    method, url, body = client.session.calls[0]
    assert method == "PATCH"
    assert url.endswith("/v2/diary/abc")
    assert body == {"item": {"consumed_at": "13:30:00"}}


def test_set_entry_time_raises_on_failure(client):
    client.session.status = 404
    with pytest.raises(RuntimeError, match="HTTP 404"):
        server.set_entry_time(client, "abc", "13:30")


@pytest.mark.parametrize("bad", ["1100", "25:00", "11:60", "9:00", "11:00:00"])
def test_time_must_be_hh_mm(bad):
    with pytest.raises(ValidationError):
        server.SetEntryTimeInput(entry_id="abc", time=bad)
    with pytest.raises(ValidationError):
        server.AddFoodToDiaryInput(mfp_id="7", time=bad)


def test_tool_reports_success(client, monkeypatch):
    monkeypatch.setattr(server, "get_mfp_client", lambda: client)
    out = asyncio.run(server.mfp_set_entry_time(server.SetEntryTimeInput(entry_id="abc", time="11:00")))
    assert json.loads(out) == {"success": True, "entry_id": "abc", "time": "11:00"}
