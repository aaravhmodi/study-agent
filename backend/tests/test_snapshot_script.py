"""Runs the script the sync hands to the browser tool, with the tool's helpers faked."""

import json
from typing import Any

import pytest
from app.browser.client import _snapshot_script

OU = "1292394"
HOME = f"https://learn.uwaterloo.ca/d2l/home/{OU}"
CALENDAR = f"https://learn.uwaterloo.ca/d2l/le/calendar/{OU}"
NEWS = f"https://learn.uwaterloo.ca/d2l/lms/news/main.d2l?ou={OU}"


class FakeBrowser:
    """The helpers the script calls, recording what it does to which tab."""

    def __init__(self, open_urls: list[str]) -> None:
        self.tabs = [{"targetId": f"tab-{i}", "url": url} for i, url in enumerate(open_urls)]
        self.current = self.tabs[0] if self.tabs else None
        self.opened: list[str] = []
        self.fronted: list[str] = []

    def helpers(self) -> dict[str, Any]:
        return {
            "list_tabs": lambda *args, **kwargs: list(self.tabs),
            "switch_tab": self._switch,
            "new_tab": self._new,
            "current_tab": lambda: self.current,
            "activate_tab": lambda tab: self.fronted.append(tab["url"]),
            "wait_for_load": lambda *args, **kwargs: None,
            "page_info": lambda: {"url": self.current["url"], "title": "LEARN"},
            "js": lambda expression: (
                "1200|false"
                if "'|'" in expression
                else json.dumps({"text": "page text", "links": []})
            ),
        }

    def _switch(self, tab: Any, activate: bool = False) -> None:
        self.current = next(t for t in self.tabs if t["targetId"] == tab or t is tab)

    def _new(self, url: str) -> str:
        self.tabs.append({"targetId": f"tab-{len(self.tabs)}", "url": url})
        self.current = self.tabs[-1]
        self.opened.append(url)
        return str(self.current["targetId"])


def _read(url: str, browser: FakeBrowser, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    script = _snapshot_script(url, 0).replace("time.sleep(1)", "pass")
    exec(compile(script, "snapshot_script", "exec"), browser.helpers())  # noqa: S102
    line = capsys.readouterr().out.strip().splitlines()[-1]
    return dict(json.loads(line.removeprefix("STUDY_AGENT_RESULT=")))


def test_announcements_are_not_read_from_another_page_of_the_same_course(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BU_CDP_URL", raising=False)
    browser = FakeBrowser([HOME, CALENDAR])

    result = _read(NEWS, browser, capsys)

    # Neither open tab is the announcements page, so it is opened, not borrowed.
    assert browser.opened == [NEWS]
    assert result["url"] == "https://learn.uwaterloo.ca/d2l/lms/news/main.d2l"


def test_an_open_page_is_reused_and_a_course_home_is_known_by_either_address(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BU_CDP_URL", raising=False)
    browser = FakeBrowser([HOME, CALENDAR, NEWS])

    _read(NEWS, browser, capsys)
    _read(f"https://learn.uwaterloo.ca/d2l/lp/ouHome/home.d2l?ou={OU}", browser, capsys)

    assert browser.opened == []
    assert browser.current is not None and browser.current["url"] == HOME


def test_the_tab_is_brought_to_the_front_only_in_a_browser_kept_for_the_sync(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # In your own Chrome the script reads quietly and leaves your tab alone.
    monkeypatch.delenv("BU_CDP_URL", raising=False)
    own = FakeBrowser([HOME])
    _read(CALENDAR, own, capsys)
    assert own.fronted == []

    # Outline and a course's home only finish loading in the tab that is showing.
    monkeypatch.setenv("BU_CDP_URL", "http://172.31.57.10:9223")
    kept = FakeBrowser([HOME])
    _read(CALENDAR, kept, capsys)
    assert kept.fronted == [CALENDAR]
