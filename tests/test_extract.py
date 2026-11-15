from payee_diff.extract import extract_findings
from payee_diff.iban import make_iban

IBAN = make_iban("GB", "FAKE00112210293847")


def _by_field(text: str) -> dict[str, str]:
    return {item.field: item.normalized for item in extract_findings(text)}


def test_labeled_invoice_block():
    text = "\n".join(
        [
            "Payee: Northwind Paper Ltd",
            f"IBAN: {IBAN}",
            "Account number: 10293847",
            "Sort code: 00-11-22",
            "IFSC: FAKE0NWP123",
            "UPI: northwind.paper@upi",
            "Amount due: GBP 1,250.00",
        ]
    )
    found = _by_field(text)
    assert found["iban"] == IBAN
    assert found["account_number"] == "10293847"
    assert found["sort_code"] == "00-11-22"
    assert found["ifsc"] == "FAKE0NWP123"
    assert found["upi"] == "northwind.paper@upi"
    assert found["amount"] == "GBP 1250.00"
    assert found["payee"] == "northwind paper ltd"


def test_spaced_iban_and_currency_symbols():
    spaced = "GB82 WEST 1234 5698 7654 32"
    text = f"IBAN {spaced}\nTotal: £1,250.00\nAmount due: €99.50"
    found = extract_findings(text)
    ibans = [item.normalized for item in found if item.field == "iban"]
    amounts = [item.normalized for item in found if item.field == "amount"]
    assert ibans == ["GB82WEST12345698765432"]
    assert "GBP 1250.00" in amounts
    assert "EUR 99.50" in amounts


def test_unlabeled_numbers_are_ignored():
    found = extract_findings("Reference 10293847 and sort 001122 and hello@example.com")
    assert found == []


def test_invalid_iban_is_ignored():
    assert extract_findings("IBAN: GB00WEST12345698765432") == []


def test_payee_stops_before_the_next_label():
    text = "Payee: Grey Harbor Supplies GmbH IBAN: GB82WEST12345698765432"
    found = _by_field(text)
    assert found["payee"] == "grey harbor supplies gmbh"
    assert "iban" in found


def test_account_number_inside_iban_is_not_a_second_field():
    text = f"IBAN: {IBAN}"
    fields = {item.field for item in extract_findings(text)}
    assert fields == {"iban"}
