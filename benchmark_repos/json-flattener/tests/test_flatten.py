from flattener.flatten import flatten


def test_flat_dict():
    assert flatten({"a": 1, "b": "x"}) == {"a": 1, "b": "x"}


def test_nested_dict():
    assert flatten({"a": {"b": {"c": 1}}}) == {"a.b.c": 1}


def test_scalars_kept():
    assert flatten({"n": None, "f": 1.5, "s": "hi"}) == {"n": None, "f": 1.5, "s": "hi"}


def test_lists_are_indexed():
    result = flatten({"a": [1, 2]})
    assert result["a.0"] == 1
    assert result["a.1"] == 2


def test_list_containing_dict():
    result = flatten({"a": [1, {"b": 3}]})
    assert result["a.1.b"] == 3