import pytest

from payee_diff.iban import compact_iban, iban_is_valid, make_iban

# Specimens from the IBAN registry examples. Not live accounts.
SPECIMENS = [
    "GB82WEST12345698765432",
    "DE89370400440532013000",
    "FR1420041010050500013M02606",
    "NL91ABNA0417164300",
    "GB82 WEST 1234 5698 7654 32",
]


@pytest.mark.parametrize("value", SPECIMENS)
def test_known_specimens_pass(value):
    assert iban_is_valid(value)


def test_checksum_catches_a_changed_digit():
    assert not iban_is_valid("GB82WEST12345698765433")
    assert not iban_is_valid("DE89370400440532013001")


def test_rejects_bad_shape():
    assert not iban_is_valid("")
    assert not iban_is_valid("not an iban")
    assert not iban_is_valid("GB82WEST123456")  # too short
    assert not iban_is_valid("ZZ82WEST12345698765432")  # unknown country
    assert not iban_is_valid("GB00WEST12345698765432")


def test_lowercase_and_spaces():
    assert iban_is_valid("gb82 west 1234 5698 7654 32")
    assert compact_iban("gb82 west 1234 5698 7654 32") == "GB82WEST12345698765432"


def test_make_iban_round_trip():
    iban = make_iban("GB", "FAKE00112210293847")
    assert iban_is_valid(iban)
    assert iban.startswith("GB")
    assert len(iban) == 22
    hidden = make_iban("DE", "000000009988776655")
    assert iban_is_valid(hidden)
    assert hidden != iban


def test_make_iban_rejects_bad_length():
    with pytest.raises(ValueError):
        make_iban("GB", "SHORT")
