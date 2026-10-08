import asyncio
import json
import logging
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel

from app.config import Settings
from app.schemas.browser import BrowserDownloadedResource, BrowserPageSnapshot
from app.schemas.sync import BrowserTestResult

logger = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)


class BrowserClientError(RuntimeError):
    """Raised when the Browser Use harness cannot complete a safe operation."""


class BrowserClient(ABC):
    @abstractmethod
    async def run_task(
        self, objective: str, output_schema: type[ModelT] | None = None
    ) -> ModelT | dict[str, Any]:
        """Run a read-only browser task and validate structured output when requested."""

    @abstractmethod
    async def test_connection(self) -> BrowserTestResult:
        """Verify browser attachment and LEARN reachability without changing page state."""

    @abstractmethod
    async def inspect_page(
        self, url: str | None = None, wait_seconds: int = 3
    ) -> BrowserPageSnapshot:
        """Read the visible page and links without performing a write action."""

    @abstractmethod
    async def inspect_content(self, url: str, wait_seconds: int = 2) -> list[BrowserPageSnapshot]:
        """Open a LEARN content page and read its visible modules/topics."""

    @abstractmethod
    async def download_resource(self, url: str) -> BrowserDownloadedResource:
        """Fetch one resource with the authenticated browser session using GET only."""


class MockBrowserClient(BrowserClient):
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload or {}

    async def run_task(
        self, objective: str, output_schema: type[ModelT] | None = None
    ) -> ModelT | dict[str, Any]:
        del objective
        return output_schema.model_validate(self.payload) if output_schema else self.payload

    async def test_connection(self) -> BrowserTestResult:
        return BrowserTestResult(
            browser_connected=True,
            learn_reachable=True,
            url="https://learn.uwaterloo.ca",
            title="Mock Waterloo LEARN",
            message="Mock browser mode is active.",
        )

    async def inspect_page(
        self, url: str | None = None, wait_seconds: int = 0
    ) -> BrowserPageSnapshot:
        del url, wait_seconds
        return BrowserPageSnapshot.model_validate(self.payload)

    async def inspect_content(self, url: str, wait_seconds: int = 0) -> list[BrowserPageSnapshot]:
        del url, wait_seconds
        pages = self.payload.get("content_pages", [])
        return [BrowserPageSnapshot.model_validate(page) for page in pages]

    async def download_resource(self, url: str) -> BrowserDownloadedResource:
        del url
        payload = self.payload.get("download")
        if not isinstance(payload, dict):
            raise BrowserClientError("Mock browser payload has no download resource")
        return BrowserDownloadedResource.model_validate(payload)


class BrowserUseClient(BrowserClient):
    """Adapter for the current Browser Use CLI local Chrome harness.

    Browser Use CLI is the browser-control layer. Semantic task execution will be
    added in the course-agent milestone; this milestone uses its read-only probe.
    """

    def __init__(self, settings: Settings, executable: str | None = None) -> None:
        self.settings = settings
        local_executable = (
            settings.project_root / ".browser-use-venv" / "Scripts" / "browser-use.exe"
        )
        self.executable = executable or (
            str(local_executable) if local_executable.exists() else settings.browser_use_executable
        )

    def is_installed(self) -> bool:
        return shutil.which(self.executable) is not None

    async def run_task(
        self, objective: str, output_schema: type[ModelT] | None = None
    ) -> ModelT | dict[str, Any]:
        logger.info("Running read-only browser probe for objective: %s", objective[:120])
        result = await self.test_connection()
        if output_schema is None:
            return result.model_dump()
        return output_schema.model_validate(result.model_dump())

    async def test_connection(self) -> BrowserTestResult:
        if not self.is_installed():
            raise BrowserClientError(
                "Browser Use CLI was not found. Install it with uv tool install and run "
                "browser-use skill install."
            )
        completed = await asyncio.to_thread(
            _run_cli, self.executable, _probe_script(self.settings.learn_url)
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "unknown Browser Use error"
            raise BrowserClientError(f"Browser Use failed: {detail[-2000:]}")
        try:
            return BrowserTestResult.model_validate(_extract_result(completed.stdout))
        except Exception as exc:
            raise BrowserClientError(f"Browser Use returned invalid probe output: {exc}") from exc

    async def inspect_page(
        self, url: str | None = None, wait_seconds: int = 3
    ) -> BrowserPageSnapshot:
        if not self.is_installed():
            raise BrowserClientError(
                "Browser Use CLI was not found. Install it with uv venv and uv pip install."
            )
        completed = await asyncio.to_thread(
            _run_cli,
            self.executable,
            _snapshot_script(url, wait_seconds),
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "unknown Browser Use error"
            raise BrowserClientError(f"Browser Use page inspection failed: {detail[-2000:]}")
        try:
            return BrowserPageSnapshot.model_validate(_extract_result(completed.stdout))
        except Exception as exc:
            raise BrowserClientError(f"Browser Use returned invalid page data: {exc}") from exc

    async def inspect_content(self, url: str, wait_seconds: int = 2) -> list[BrowserPageSnapshot]:
        if not self.is_installed():
            raise BrowserClientError(
                "Browser Use CLI was not found. Install it with uv venv and uv pip install."
            )
        # Brightspace exposes the course tree through its authenticated Content
        # API.  Use it first so file topics resolve to the actual file endpoint
        # instead of the HTML viewer shell.  The older DOM traversal below is a
        # compatibility fallback for installations where the API is disabled.
        api_completed = await asyncio.to_thread(
            _run_cli,
            self.executable,
            _api_content_script(url, wait_seconds),
        )
        if api_completed.returncode == 0:
            try:
                api_payload = _extract_result(api_completed.stdout)
                api_pages = api_payload.get("pages")
                if isinstance(api_pages, list) and api_pages:
                    return [BrowserPageSnapshot.model_validate(page) for page in api_pages]
            except Exception:
                # Fall through to the legacy page scraper.  The fallback keeps
                # sync usable on older/custom Brightspace deployments.
                pass
        completed = await asyncio.to_thread(
            _run_cli,
            self.executable,
            _content_script(url, wait_seconds),
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "unknown Browser Use error"
            raise BrowserClientError(f"Browser Use content inspection failed: {detail[-2000:]}")
        try:
            payload = _extract_result(completed.stdout)
            pages = payload.get("pages")
            if not isinstance(pages, list):
                raise BrowserClientError("Browser Use content inspection returned no pages")
            return [BrowserPageSnapshot.model_validate(page) for page in pages]
        except Exception as exc:
            raise BrowserClientError(f"Browser Use returned invalid content data: {exc}") from exc

    async def download_resource(self, url: str) -> BrowserDownloadedResource:
        if not self.is_installed():
            raise BrowserClientError(
                "Browser Use CLI was not found. Install it with uv venv and uv pip install."
            )
        try:
            # Downloads run in their own Browser Use process. Keep a single
            # stalled resource from aborting the rest of a course sync.
            completed = await asyncio.to_thread(
                _run_cli, self.executable, _download_script(url), 30
            )
        except subprocess.TimeoutExpired as exc:
            raise BrowserClientError("Browser Use resource download timed out") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "unknown Browser Use error"
            raise BrowserClientError(f"Browser Use resource download failed: {detail[-2000:]}")
        try:
            return BrowserDownloadedResource.model_validate(_extract_result(completed.stdout))
        except Exception as exc:
            raise BrowserClientError(f"Browser Use returned invalid download data: {exc}") from exc


def _run_cli(
    executable: str, script: str, timeout_seconds: int = 90
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [executable],
        input=script,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _extract_result(stdout: str) -> dict[str, Any]:
    marker = "STUDY_AGENT_RESULT="
    for line in reversed(stdout.splitlines()):
        if line.startswith(marker):
            value = json.loads(line.removeprefix(marker))
            if not isinstance(value, dict):
                raise BrowserClientError("Browser Use probe did not return an object")
            return value
    raise BrowserClientError("Browser Use probe did not return a structured result")


def _probe_script(learn_url: str) -> str:
    encoded_url = json.dumps(learn_url)
    return f"""import json
import time
from urllib.parse import urlsplit, urlunsplit

target_url = {encoded_url}
tabs = list_tabs()
matching = [
    tab for tab in tabs
    if target_url.split('/')[2] in str(tab.get('url', ''))
    and '/d2l/api/' not in urlsplit(str(tab.get('url', ''))).path
    and '/d2l/common/viewFile' not in urlsplit(str(tab.get('url', ''))).path
]
matching.sort(
    key=lambda tab: 0
    if urlsplit(str(tab.get('url', ''))).path in {'/d2l/home', '/d2l/'}
    else 1
)
if matching:
    switch_tab(
        matching[0].get('id')
        or matching[0].get('targetId')
        or matching[0].get('target_id')
        or matching[0].get('index')
        or matching[0]
    )
else:
    new_tab(target_url)
time.sleep(2)
try:
    info = page_info()
except Exception:
    new_tab(target_url)
    time.sleep(2)
    info = page_info()
url = str(info.get('url', ''))
parsed = urlsplit(url)
safe_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
safe_title = ''.join(
    character for character in str(info.get('title') or '') if ord(character) < 128
)
print('STUDY_AGENT_RESULT=' + json.dumps({{
    'browser_connected': True,
    'learn_reachable': (parsed.hostname or '').lower() == 'learn.uwaterloo.ca',
    'url': safe_url or None,
    'title': safe_title or None,
    'message': 'Read-only Browser Use probe completed.'
}}))
"""


def _snapshot_script(url: str | None, wait_seconds: int) -> str:
    encoded_url = json.dumps(url)
    expression = """JSON.stringify({
  text: document.body.innerText.slice(0, 100000),
  links: Array.from(document.querySelectorAll('a')).map(a => {
    const raw = String(a.href || '');
    try {
      const parsed = new URL(raw);
      const params = new URLSearchParams();
      for (const [key, value] of parsed.searchParams.entries()) {
        if (['ou', 'q', 'term', 'id', 'page'].includes(key)) params.set(key, value);
      }
      return {
        text: (a.innerText || a.textContent || '').trim(),
        href: parsed.origin + parsed.pathname + (params.toString() ? '?' + params.toString() : '')
      };
    } catch (_) {
      return {text: (a.innerText || a.textContent || '').trim(), href: raw};
    }
  }).slice(0, 1000)
})"""
    return f"""import json
import time
from urllib.parse import parse_qs, urlsplit, urlunsplit

target_url = {encoded_url}
if target_url:
    target = urlsplit(target_url)
    tabs = list_tabs()
    target_ou = parse_qs(target.query).get('ou', [None])[0]
    matching = []
    for tab in tabs:
        current = urlsplit(str(tab.get('url', '')))
        if current.netloc != target.netloc:
            continue
        if target_ou and current.path == target.path and target_ou in parse_qs(
            current.query
        ).get('ou', []):
            matching.append(tab)
        elif target_ou and current.path.endswith('/' + target_ou):
            matching.append(tab)
        elif target.path in ('', '/') and current.path == '/d2l/home':
            matching.append(tab)
        elif target.path not in ('', '/', '/d2l/home') and current.path.startswith(
            target.path.rstrip('/') + '/'
        ):
            matching.append(tab)
        elif target.path not in ('', '/') and current.path == target.path:
            matching.append(tab)
    matching.sort(key=lambda tab: 0 if urlsplit(str(tab.get('url', ''))).path == target.path else 1)
    if matching:
        switch_tab(
            matching[0].get('id')
            or matching[0].get('targetId')
            or matching[0].get('target_id')
            or matching[0].get('index')
            or matching[0]
        )
    else:
        new_tab(target_url)
    try:
        wait_for_load()
    except Exception:
        pass
time.sleep({max(0, min(wait_seconds, 15))})
try:
    info = page_info()
except Exception:
    recovery_url = target_url or 'https://learn.uwaterloo.ca/d2l/home'
    new_tab(recovery_url)
    time.sleep(2)
    try:
        wait_for_load()
    except Exception:
        pass
    info = page_info()
current_url = str(info.get('url', ''))
parsed = urlsplit(current_url)
safe_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
safe_title = ''.join(
    character for character in str(info.get('title') or '') if ord(character) < 128
)
raw = js({json.dumps(expression)})
payload = json.loads(raw) if isinstance(raw, str) else raw
print('STUDY_AGENT_RESULT=' + json.dumps({{
    'url': safe_url,
    'title': safe_title or None,
    'text': payload.get('text', ''),
    'links': payload.get('links', [])
}}))
"""


def _api_content_script(url: str, wait_seconds: int) -> str:
    encoded_url = json.dumps(url)
    expression = """(async () => {
  const pathParts = window.location.pathname.split('/');
  const offeringId = pathParts[4] || '';
  const apiBase = `/d2l/api/le/1.82/${offeringId}`;
  const getJson = async path => {
    try {
      const response = await fetch(path, {credentials: 'include'});
      if (!response.ok) return null;
      return await response.json();
    } catch (_) {
      return null;
    }
  };
  const asItems = value => {
    if (Array.isArray(value)) return value;
    if (Array.isArray(value?.Items)) return value.Items;
    if (Array.isArray(value?.Structure)) return value.Structure;
    return [];
  };
  const pages = [];
  const seenTopics = new Set();
  const seenModules = new Set();
  const cleanText = value => String(value || '').replace(/<[^>]*>/g, ' ').trim();
  const addTopic = async item => {
    const topicId = item?.Id ?? item?.id;
    if (!topicId || seenTopics.has(String(topicId))) return;
    seenTopics.add(String(topicId));
    const topic = await getJson(`${apiBase}/content/topics/${topicId}`) || item;
    const title = String(topic?.Title || item?.Title || `Content topic ${topicId}`).trim();
    const topicType = Number(topic?.TopicType ?? item?.TopicType ?? 0);
    let href = '';
    if (topicType === 1) {
      href = `${window.location.origin}${apiBase}/content/topics/${topicId}/file`;
    } else if (topic?.Url) {
      try {
        href = new URL(topic.Url, window.location.origin).href;
      } catch (_) {
        href = '';
      }
    }
    if (!href) return;
    const description = topic?.Description?.Text
      || topic?.Description?.Html
      || topic?.Description
      || '';
    pages.push({
      url: href,
      title,
      text: cleanText(description),
      links: [{text: title, href}]
    });
  };
  const walkModule = async module => {
    const moduleId = module?.Id ?? module?.id;
    if (!moduleId || seenModules.has(String(moduleId))) return;
    seenModules.add(String(moduleId));
    const structure = await getJson(`${apiBase}/content/modules/${moduleId}/structure/`);
    const items = asItems(structure);
    const batchSize = 8;
    for (let index = 0; index < items.length; index += batchSize) {
      const batch = items.slice(index, index + batchSize);
      await Promise.all(batch.map(item => {
        const type = Number(item?.Type ?? item?.type ?? 0);
        return type === 0 || item?.ModuleId || item?.Module
          ? walkModule(item)
          : addTopic(item);
      }));
    }
  };
  if (!offeringId) return JSON.stringify({pages: []});
  const roots = await getJson(`${apiBase}/content/root/`);
  await Promise.all(asItems(roots).map(root => walkModule(root)));
  return JSON.stringify({pages});
})()"""
    return f"""import json
import time
from urllib.parse import urlsplit

target_url = {encoded_url}
target = urlsplit(target_url)
tabs = list_tabs()
matching = [
    tab for tab in tabs
    if urlsplit(str(tab.get('url', ''))).netloc == target.netloc
    and urlsplit(str(tab.get('url', ''))).path == target.path
]
if matching:
    switch_tab(
        matching[0].get('id')
        or matching[0].get('targetId')
        or matching[0].get('target_id')
        or matching[0].get('index')
        or matching[0]
    )
else:
    new_tab(target_url)
try:
    wait_for_load()
except Exception:
    pass
time.sleep({max(0, min(wait_seconds, 15))})
raw = js({json.dumps(expression)})
payload = json.loads(raw) if isinstance(raw, str) else raw
print('STUDY_AGENT_RESULT=' + json.dumps({{'pages': payload.get('pages', [])}}))
"""


def _content_script(url: str, wait_seconds: int) -> str:
    encoded_url = json.dumps(url)
    expression = """JSON.stringify({
    url: window.location.href.split('?')[0],
    title: document.title || null,
    text: document.body.innerText.slice(0, 100000),
    links: Array.from(document.querySelectorAll('a')).map(a => {
      const raw = String(a.href || '');
      try {
        const parsed = new URL(raw);
        const params = new URLSearchParams();
        for (const [key, value] of parsed.searchParams.entries()) {
          if (['ou', 'q', 'term', 'id', 'page'].includes(key)) params.set(key, value);
        }
        return {
          text: (a.innerText || a.textContent || '').trim(),
          href: parsed.origin + parsed.pathname + (params.toString() ? '?' + params.toString() : '')
        };
      } catch (_) {
        return {text: (a.innerText || a.textContent || '').trim(), href: raw};
      }
    }).slice(0, 1000)
})"""
    ids_expression = """JSON.stringify(Array.from(document.querySelectorAll('[id^="TreeItem"]'))
  .map(node => node.id)
  .filter(id => /^TreeItem\\d+$/.test(id)))"""
    del expression
    return f"""import json
import time
from urllib.parse import urlsplit

target_url = {encoded_url}
target = urlsplit(target_url)
tabs = list_tabs()
matching = []
for tab in tabs:
    current = urlsplit(str(tab.get('url', '')))
    if current.netloc == target.netloc and current.path == target.path:
        matching.append(tab)
if matching:
    switch_tab(
        matching[0].get('id')
        or matching[0].get('targetId')
        or matching[0].get('target_id')
        or matching[0].get('index')
        or matching[0]
    )
else:
    new_tab(target_url)
try:
    wait_for_load()
except Exception:
    pass
time.sleep({max(0, min(wait_seconds, 15))})
parts = target.path.split('/')
offering_id = parts[4] if len(parts) > 4 else ''
module_ids_raw = js({json.dumps(ids_expression)})
module_ids = json.loads(module_ids_raw) if isinstance(module_ids_raw, str) else []
for module_id in list(module_ids):
    js(f"document.getElementById({{json.dumps(module_id)}})?.click(); 'expanded'")
    time.sleep(0.25)
module_ids_raw = js({json.dumps(ids_expression)})
module_ids = json.loads(module_ids_raw) if isinstance(module_ids_raw, str) else module_ids
pages = []
for request_id, tree_id in enumerate(module_ids[:100], start=1):
    module_id = tree_id.removeprefix('TreeItem')
    module_expression = f'''(async () => {{{{
  try {{{{
    const response = await fetch(
      '/d2l/le/content/{{offering_id}}/ModuleDetailsPartial'
      + '?mId={{module_id}}&writeHistoryEntry=0'
      + '&_d2l_prc%24headingLevel=2&_d2l_prc%24scope='
      + '&_d2l_prc%24hasActiveForm=false&isXhr=true&requestId={{request_id}}',
      {{{{credentials: 'include'}}}}
    );
    if (!response.ok) return JSON.stringify([]);
    const html = await response.text();
    const normalized = html.split(String.fromCharCode(92, 34)).join(String.fromCharCode(34));
    const regex = /href=\"([^\"]*viewContent[^\"]*)\"[^>]*title=\"([^\"]*)\"/g;
    const decode = value => {{{{
      const element = document.createElement('textarea');
      element.innerHTML = value;
      return element.value;
    }}}};
    return JSON.stringify([...normalized.matchAll(regex)].map(match => ({{{{
      text: decode(match[2]),
      href: new URL(decode(match[1]), window.location.origin).href
    }}}})));
  }}}} catch (_) {{{{
    return JSON.stringify([]);
  }}}}
}}}})()'''
    raw = js(module_expression)
    links = json.loads(raw) if isinstance(raw, str) else []
    if links:
        pages.append(
            {{
                'url': target_url,
                'title': f'Module {{module_id}}',
                'text': '',
                'links': links,
            }}
        )
# Brightspace can intermittently reject the partial GET even though the
# rendered Content page is available. Fall back to selecting each module and
# reading the resulting DOM; this remains navigation-only and read-only.
if not pages:
    fallback_expression = '''JSON.stringify({{
  title: document.title || null,
  text: document.body.innerText.slice(0, 100000),
  links: Array.from(document.querySelectorAll('a')).map(a => ({{
    text: (a.innerText || a.textContent || '').trim(),
    href: a.href
  }})).filter(link => link.href.includes('/d2l/le/content/') ||
    link.href.includes('/d2l/common/viewFile'))
}})'''
    for tree_id in module_ids[:100]:
        js(f"document.getElementById({{json.dumps(tree_id)}})?.click(); 'selected'")
        time.sleep(0.35)
        raw = js(fallback_expression)
        detail = json.loads(raw) if isinstance(raw, str) else {{}}
        links = detail.get('links', [])
        if links:
            pages.append({{
                'url': target_url,
                'title': detail.get('title') or f'Module {{tree_id}}',
                'text': detail.get('text', ''),
                'links': links,
            }})
# Read every discovered Content item in the same authenticated browser context.
# This is intentionally a GET-only traversal: no buttons, forms, submissions, or
# other write actions are invoked.  HTML pages expose their instructions and
# Dropbox wording; binary files remain represented as resources for later parsing.
resource_urls = []
seen_urls = set()
for page in pages:
    for link in page.get('links', []):
        href = str(link.get('href', ''))
        if href and href not in seen_urls:
            seen_urls.add(href)
            resource_urls.append(href)
for resource_url in resource_urls[:200]:
    resource_expression = f'''(async () => {{{{
  try {{{{
    const response = await fetch({{json.dumps(resource_url)}}, {{{{credentials: 'include'}}}});
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('text/html')) return JSON.stringify({{{{text: '', links: []}}}});
    const html = await response.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const links = Array.from(doc.querySelectorAll('a')).map(a => ({{{{
      text: (a.innerText || a.textContent || '').trim(),
      href: new URL(a.href, {{json.dumps(resource_url)}}).href
    }}}}));
    return JSON.stringify({{{{text: (doc.body?.innerText || '').slice(0, 100000), links}}}});
  }}}} catch (_) {{{{
    return JSON.stringify({{{{text: '', links: []}}}});
  }}}}
}}}})()'''
    raw = js(resource_expression)
    detail = json.loads(raw) if isinstance(raw, str) else {{}}
    pages.append({{
        'url': resource_url,
        'title': resource_url.rsplit('/', 1)[-1],
        'text': detail.get('text', ''),
        'links': detail.get('links', []),
    }})
print('STUDY_AGENT_RESULT=' + json.dumps({{'pages': pages}}))
"""


def _download_script(url: str) -> str:
    encoded_url = json.dumps(url)
    chunk_expression = """(() => {
  const state = window.__studyAgentDownload;
  if (!state) return JSON.stringify({error: 'download state is missing'});
  const start = Number(state.offset || 0);
  const chunk = state.content_base64.slice(start, start + 65536);
  state.offset = start + chunk.length;
  return JSON.stringify({chunk, done: state.offset >= state.content_base64.length});
})()"""
    expression = rf'''(async () => {{
  try {{
    let response = await fetch({encoded_url}, {{credentials: 'include'}});
    if (!response.ok) return JSON.stringify({{error: 'HTTP ' + response.status}});
    let contentType = response.headers.get('content-type') || '';
    if (contentType.includes('text/html')) {{
      const html = await response.text();
      const locationMatch = html.match(
        /data-location=["']([^"']+\.(?:pdf|docx?|pptx?|xlsx?)(?:\\?[^"']*)?)["']/i
      );
      if (locationMatch) {{
        const embeddedUrl = new URL(
          locationMatch[1].replaceAll('&amp;', '&'),
          response.url
        ).href;
        response = await fetch(embeddedUrl, {{credentials: 'include'}});
        if (!response.ok) return JSON.stringify({{error: 'HTTP ' + response.status}});
        contentType = response.headers.get('content-type') || '';
      }} else {{
        const encoder = new TextEncoder();
        const bytes = encoder.encode(html);
        let binary = '';
        const chunkSize = 0x8000;
        for (let index = 0; index < bytes.length; index += chunkSize) {{
          binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
        }}
        window.__studyAgentDownload = {{
          content_base64: btoa(binary),
          offset: 0
        }};
        return JSON.stringify({{
          resolved_url: response.url,
          filename: new URL({encoded_url}).pathname.split('/').pop() || 'resource.html',
          content_type: contentType,
          content_base64: '',
          chunked: true
        }});
      }}
    }}
    const contentLength = Number(response.headers.get('content-length') || 0);
    if (/^(audio|video)\//i.test(contentType) || contentLength > 15 * 1024 * 1024) {{
      return JSON.stringify({{
        resolved_url: response.url,
        filename: new URL({encoded_url}).pathname.split('/').pop() || 'media.bin',
        content_type: contentType || 'application/octet-stream',
        content_base64: '',
        skipped: true,
        skip_reason: /^(audio|video)\//i.test(contentType)
          ? 'media resource is not downloaded'
          : 'resource exceeds browser transfer limit'
      }});
    }}
    const buffer = await response.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let binary = '';
    const chunkSize = 0x8000;
    for (let index = 0; index < bytes.length; index += chunkSize) {{
      binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
    }}
    const disposition = response.headers.get('content-disposition') || '';
    const match = disposition.match(/filename[^;=]*=(?:UTF-8''|\"?)([^;\"]+)/i);
    const fallback = new URL({encoded_url}).pathname.split('/').pop() || 'resource.bin';
    window.__studyAgentDownload = {{
      content_base64: btoa(binary),
      offset: 0
    }};
    return JSON.stringify({{
      resolved_url: response.url,
      filename: (match && match[1]
        ? decodeURIComponent(match[1]).replace(/^\"|\"$/g, '')
        : fallback),
      content_type: contentType || 'application/octet-stream',
      content_base64: '',
      chunked: true
    }});
  }} catch (error) {{
    return JSON.stringify({{error: String(error)}});
  }}
}})()'''
    return f"""import json
import time
from urllib.parse import urlsplit, urlunsplit

target_url = {encoded_url}
target = urlsplit(target_url)
tabs = list_tabs()
matching = [
    tab for tab in tabs
    if urlsplit(str(tab.get('url', ''))).netloc == target.netloc
    and '/d2l/api/' not in urlsplit(str(tab.get('url', ''))).path
    and '/d2l/common/viewFile' not in urlsplit(str(tab.get('url', ''))).path
]
matching.sort(
    key=lambda tab: 0
    if urlsplit(str(tab.get('url', ''))).path in {'/d2l/home', '/d2l/'}
    else 1
)
if matching:
    switch_tab(
        matching[0].get('id')
        or matching[0].get('targetId')
        or matching[0].get('target_id')
        or matching[0].get('index')
        or matching[0]
    )
else:
    new_tab('https://learn.uwaterloo.ca/d2l/home')
    time.sleep(1)
raw = js({json.dumps(expression)})
payload = json.loads(raw) if isinstance(raw, str) else raw
if payload.get('error'):
    raise RuntimeError(payload['error'])
if payload.get('chunked'):
    chunks = []
    while True:
        chunk_raw = js({json.dumps(chunk_expression)})
        chunk_payload = json.loads(chunk_raw) if isinstance(chunk_raw, str) else chunk_raw
        if chunk_payload.get('error'):
            raise RuntimeError(chunk_payload['error'])
        chunks.append(chunk_payload.get('chunk', ''))
        if chunk_payload.get('done'):
            break
    payload['content_base64'] = ''.join(chunks)
    payload.pop('chunked', None)
parsed = urlsplit(target_url)
payload['url'] = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ''))
payload['resolved_url'] = payload.get('resolved_url') or payload['url']
print('STUDY_AGENT_RESULT=' + json.dumps(payload))
"""
