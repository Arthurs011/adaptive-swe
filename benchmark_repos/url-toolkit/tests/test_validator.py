from urltool.validator import is_valid_url, domain_of


def test_valid_https():
    assert is_valid_url("https://example.com/path?q=1") is True


def test_valid_http():
    assert is_valid_url("http://example.com") is True


def test_no_scheme():
    assert is_valid_url("localhost:8080") is False


def test_whitespace_rejected():
    assert is_valid_url("http://example.com/a b") is False


def test_empty_rejected():
    assert is_valid_url("") is False


def test_unknown_fake_scheme():
    assert is_valid_url("notaurl://thing") is False


def test_domain_extraction():
    assert domain_of("https://sub.example.com/x/y") == "sub.example.com"