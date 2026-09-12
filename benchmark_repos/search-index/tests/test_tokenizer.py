from searchidx.tokenizer import tokenize


def test_basic_split():
    assert tokenize("simple text") == ["simple", "text"]


def test_punctuation_removed():
    assert tokenize("Hello, world!") == ["hello", "world"]


def test_lowercased():
    assert tokenize("HELLO WORLD") == ["hello", "world"]


def test_mixed_punctuation():
    assert tokenize("A: B; C?") == ["a", "b", "c"]


def test_numbers_kept():
    assert tokenize("item123") == ["item123"]


def test_contractions():
    assert tokenize("don't") == ["dont"]