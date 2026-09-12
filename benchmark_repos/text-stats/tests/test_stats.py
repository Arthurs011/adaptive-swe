from textstats.stats import count_lines, count_words, average_word_length


def test_empty():
    assert count_lines("") == 0


def test_plain_two_lines():
    assert count_lines("one\ntwo") == 2


def test_trailing_newline():
    assert count_lines("one\ntwo\n") == 2


def test_blank_line_between():
    assert count_lines("a\n\nb") == 3


def test_word_count():
    assert count_words("  hello   world  ") == 2


def test_avg_word_length():
    assert average_word_length("hi there") == 3.5