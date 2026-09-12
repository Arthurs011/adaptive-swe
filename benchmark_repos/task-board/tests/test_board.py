from tasks.board import Task, summarize, tasks_by_owner


def _sample_tasks():
    return [
        Task("a", "todo", "alice"),
        Task("b", "done", "alice"),
        Task("c", "done", "bob"),
    ]


def test_summarize_mixed():
    result = summarize(_sample_tasks())
    assert result["todo"] == 1


def test_summarize_done_count():
    result = summarize(_sample_tasks())
    assert result["done"] == 2


def test_tasks_by_owner():
    result = tasks_by_owner(_sample_tasks(), "alice")
    assert len(result) == 2