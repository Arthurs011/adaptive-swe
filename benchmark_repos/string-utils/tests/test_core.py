from stringutils.core import truncate, word_count, reverse_words


def test_truncate_long_text():
    assert truncate("hello world this is quite long", 16) == "hello world t..."


def test_word_count_basic():
    assert word_count("a b c") == 3


def test_word_count_empty():
    assert word_count("") == 0


def test_reverse_words_basic():
    assert reverse_words("one two three") == "three two one"