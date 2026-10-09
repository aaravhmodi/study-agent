import pytest
from app.services.learn_links import topic_key, viewer_url


def test_download_links_open_the_learn_viewer() -> None:
    url = "https://learn.uwaterloo.ca/d2l/api/le/1.82/1318237/content/topics/6725573/file"

    assert viewer_url(url) == (
        "https://learn.uwaterloo.ca/d2l/le/content/1318237/viewContent/6725573/View"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://outline.uwaterloo.ca/viewer/view/nzh9rx",
        "https://learn.uwaterloo.ca/d2l/le/content/1318237/viewContent/6725573/View",
        "https://learn.uwaterloo.ca/d2l/le/news/1318237",
    ],
)
def test_other_pages_are_kept(url: str) -> None:
    assert viewer_url(url) == url


@pytest.mark.parametrize(
    "url", [None, "", "javascript:alert(1)", "file:///C:/notes.pdf", "/relative"]
)
def test_missing_or_unsafe_links_are_dropped(url: str | None) -> None:
    assert viewer_url(url) is None


def test_viewer_and_download_links_name_the_same_topic() -> None:
    view = "https://learn.uwaterloo.ca/d2l/le/content/1299242/viewContent/6617316/View"
    download = "https://learn.uwaterloo.ca/d2l/api/le/1.82/1299242/content/topics/6617316/file"

    assert topic_key(view) == topic_key(download) == ("1299242", "6617316")
    assert topic_key("https://outline.uwaterloo.ca/viewer/view/x") is None
    assert topic_key(None) is None
