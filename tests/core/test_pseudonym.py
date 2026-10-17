"""Pseudonymisation, not anonymisation (plan step 0.4): keyed tokens, and a key that stays put."""

import os
import stat

import pytest

import qpilot.core.pseudonym as pseudonym
from qpilot.core.pseudonym import (
    KEY_BYTES,
    TOKEN,
    PseudonymError,
    Pseudonymiser,
    endpoint_is_local,
    hmac_key,
)
from qpilot.schemas_studio import QuarantineEntry, text_id_for


def test_the_key_is_created_once_private_and_random(tmp_path):
    key = hmac_key(tmp_path)
    path = tmp_path / ".keys" / "hmac.key"
    assert len(key) == KEY_BYTES and path.read_bytes() == key
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) & 0o077 == 0
    assert hmac_key(tmp_path) == key
    assert hmac_key(tmp_path / "other") != key


def test_tokens_are_stable_within_a_workspace_and_differ_across_workspaces(tmp_path):
    a, b = Pseudonymiser(tmp_path / "a"), Pseudonymiser(tmp_path / "b")
    token = a.pseudonymise("Patient_007")
    assert TOKEN.match(token)
    assert (
        a.pseudonymise("Patient_007")
        == token
        == Pseudonymiser(tmp_path / "a").pseudonymise("Patient_007")
    )
    assert a.pseudonymise("Patient_008") != token
    assert b.pseudonymise("Patient_007") != token
    assert "Patient" not in token and str(a.key) not in repr(a)


def test_entries_keep_their_ids_and_flags(tmp_path):
    value = "jane.doe@uni.example.org"
    entry = QuarantineEntry(
        text_id=text_id_for("rdml:sample.id", value),
        origin="rdml:sample.id",
        value=value,
        flags=["email_like"],
    )
    (out,) = Pseudonymiser(tmp_path).pseudonymise_entries([entry])
    assert TOKEN.match(out.value) and out.value != value
    assert (out.text_id, out.origin, out.flags) == (entry.text_id, entry.origin, entry.flags)


def test_two_names_sharing_a_token_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(pseudonym, "token", lambda text, key: "s_0000000000")
    entries = [
        QuarantineEntry(text_id=text_id_for("o", v), origin="o", value=v) for v in ("A", "B")
    ]
    with pytest.raises(PseudonymError, match="share"):
        Pseudonymiser(tmp_path).pseudonymise_entries(entries)


@pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX")
def test_a_key_others_can_read_or_a_linked_key_is_refused(tmp_path):
    hmac_key(tmp_path)
    path = tmp_path / ".keys" / "hmac.key"
    path.chmod(0o644)
    with pytest.raises(PseudonymError, match="readable by other users"):
        hmac_key(tmp_path)
    other = tmp_path / "elsewhere"
    hmac_key(other)
    path.unlink()
    path.symlink_to(other / ".keys" / "hmac.key")
    with pytest.raises(OSError):
        hmac_key(tmp_path)


def test_a_damaged_key_is_refused(tmp_path):
    hmac_key(tmp_path)
    path = tmp_path / ".keys" / "hmac.key"
    path.write_bytes(b"short")
    with pytest.raises(PseudonymError, match="damaged"):
        hmac_key(tmp_path)


@pytest.mark.parametrize(
    ("provider", "endpoint", "local"),
    [
        ("none", None, True),
        ("openai_compatible", "http://127.0.0.1:11434", True),
        ("openai_compatible", "http://localhost:8000/v1", True),
        ("openai_compatible", "http://[::1]:11434", True),
        ("openai_compatible", "http://127.0.0.2:1234", True),
        ("openai_compatible", "https://api.openai.example.com", False),
        ("openai_compatible", "http://127.0.0.1@evil.example.com", False),
        ("openai_compatible", "http://evil.example.com#@127.0.0.1", False),
        ("openai_compatible", "http://localhost.evil.example.com", False),
        ("openai_compatible", "http://10.0.0.5:11434", False),
        ("openai_compatible", None, False),
        ("openai_compatible", "not a url", False),
        ("anthropic", None, False),
        ("anthropic", "http://127.0.0.1:8080", False),
    ],
)
def test_what_counts_as_this_machine(provider, endpoint, local):
    assert endpoint_is_local(provider, endpoint) is local


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, "outbound (Studio): none"),
        (
            {
                "QPILOT_MODEL_PROVIDER": "openai_compatible",
                "QPILOT_MODEL_ENDPOINT": "http://127.0.0.1:11434",
            },
            "outbound (Studio): local, http://127.0.0.1:11434",
        ),
        (
            {"QPILOT_MODEL_PROVIDER": "anthropic"},
            "outbound (Studio): REMOTE, https://api.anthropic.com (provider anthropic); "
            "sample names are pseudonymised",
        ),
        (
            {
                "QPILOT_MODEL_PROVIDER": "openai_compatible",
                "QPILOT_MODEL_ENDPOINT": "https://user:secret@llm.example.com/v1?key=k",
            },
            "outbound (Studio): REMOTE, https://llm.example.com/v1",
        ),
    ],
)
def test_the_doctor_line_for_studio(monkeypatch, env, expected):
    from qpilot.cli.core_cmds import studio_outbound_line

    for var in ("QPILOT_MODEL_PROVIDER", "QPILOT_MODEL_ENDPOINT", "QPILOT_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    line = studio_outbound_line()
    assert line.startswith(expected)
    assert "secret" not in line and "key=k" not in line
