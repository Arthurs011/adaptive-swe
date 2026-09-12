from invoicing.invoice import calculate_total


def test_single_item():
    assert calculate_total([(9.99, 2)]) == 21.98


def test_exact_dollar_item_is_taxed():
    assert calculate_total([(1.00, 1)]) == 1.10


def test_item_under_one_dollar_is_taxed():
    assert calculate_total([(0.50, 2)]) == 1.10


def test_mixed_items():
    assert calculate_total([(0.50, 1), (2.00, 1)]) == 2.75


def test_empty_invoice():
    assert calculate_total([]) == 0.0


def test_custom_rate():
    assert calculate_total([(10.00, 1)], tax_rate=0.20) == 12.00