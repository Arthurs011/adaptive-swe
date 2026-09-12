from src.discount import calculate_discount


def test_bulk_discount_ten_plus():
    assert calculate_discount(10, 10.0) == 95.0


def test_coupon_flat5():
    assert calculate_discount(5, 10.0, "FLAT5") == 45.0


def test_coupon_save10():
    assert calculate_discount(2, 10.0, "SAVE10") == 18.0


def test_no_discount_single_item():
    assert calculate_discount(1, 7.5) == 7.5