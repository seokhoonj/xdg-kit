"""Tests for the ``Secret`` value type and ``mask_secret``.

These pin the council-review fixes: the ``edge <= 0`` whole-secret disclosure (the ``-0``
slice footgun) and the ``__eq__`` crash on a non-ASCII secret.
"""

from __future__ import annotations

import pytest

from credbox.secret import Secret, mask_secret

SECRET = "sk_live_0123456789abcdef"


def test_reveal_returns_the_raw_value() -> None:
    assert Secret(SECRET).reveal() == SECRET


def test_str_renders_the_mask_not_the_secret() -> None:
    text = str(Secret(SECRET))
    assert SECRET not in text
    assert text == mask_secret(SECRET)


def test_repr_is_masked_and_hides_the_secret() -> None:
    text = repr(Secret(SECRET))
    assert text.startswith("Secret(")
    assert SECRET not in text


def test_mask_reveals_both_edges_for_a_long_value() -> None:
    assert mask_secret("abcdefghijklmnop", edge=4) == "abcd...mnop"


def test_mask_fully_redacts_a_value_shorter_than_four_edges() -> None:
    # 9 chars at edge=4 needs len >= 16 -> fully redacted, not "8 of 9 chars shown".
    assert mask_secret("123456789", edge=4) == "***"


def test_mask_edge_zero_fully_redacts_and_never_reveals_the_whole_secret() -> None:
    # The -0 slice footgun: value[-0:] == value[0:] == the whole secret if the guard is
    # only `len >= 4*edge` (always true at edge=0). The `edge > 0` guard must catch this.
    assert mask_secret(SECRET, edge=0) == "***"


def test_mask_negative_edge_fully_redacts() -> None:
    assert mask_secret(SECRET, edge=-3) == "***"


def test_equal_secrets_compare_equal() -> None:
    assert Secret(SECRET) == Secret(SECRET)


def test_different_secrets_compare_unequal() -> None:
    assert Secret(SECRET) != Secret(SECRET + "x")


def test_equality_of_non_ascii_secrets_does_not_crash() -> None:
    # hmac.compare_digest raises TypeError on a non-ASCII *str*; the value type must encode
    # to bytes first so a secret with a non-ASCII char compares instead of crashing.
    assert Secret("café_péé") == Secret("café_péé")
    assert Secret("péér") != Secret("pééx")


def test_equality_against_a_non_secret_is_false_and_never_raises() -> None:
    assert (Secret(SECRET) == SECRET) is False
    assert (Secret(SECRET) == None) is False  # noqa: E711 - exercising __eq__, not identity


def test_secret_is_unhashable() -> None:
    with pytest.raises(TypeError):
        hash(Secret(SECRET))
    with pytest.raises(TypeError):
        {Secret(SECRET): 1}  # cannot become a dict key


def test_secret_rejects_a_non_str_value() -> None:
    with pytest.raises(TypeError):
        Secret(b"bytes-not-str")  # type: ignore[arg-type]
