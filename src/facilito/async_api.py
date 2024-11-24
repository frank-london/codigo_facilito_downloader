from pathlib import Path

from playwright.async_api import BrowserContext, Page, async_playwright
from playwright_stealth import Stealth

from . import collectors
from .constants import BASE_URL, LOGIN_URL, SESSION_FILE
from .errors import LoginError
from .helpers import read_json
from .logger import logger
from .utils import (
    load_state,
    login_required,
    normalize_cookies,
    save_state,
    try_except_request,
)


class AsyncFacilito:
    def __init__(self, headless=False):
        self.headless = headless
        self.authenticated = False

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.firefox.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            is_mobile=True,
            java_script_enabled=True,
        )

        stealth = Stealth(init_scripts_only=True)

        await stealth.apply_stealth_async(self._context)

        await load_state(self._context, SESSION_FILE)

        await self._set_profile()

        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._context.close()
        await self._browser.close()
        await self._playwright.stop()

    @property
    def context(self) -> BrowserContext:
        return self._context

    @property
    async def page(self) -> Page:
        return await self._context.new_page()

    @try_except_request
    async def login(self):
        logger.info("Please login, in the opened browser")
        logger.info("You have to login manually, you have 2 minutes to do it")

        SELECTOR = "h1.h1.f-text-34"

        try:
            page = await self.page
            await page.goto(LOGIN_URL)

            welcome_message = await page.wait_for_selector(
                SELECTOR,
                timeout=2 * 60 * 1000,
            )

            if not welcome_message:
                raise LoginError()

            self.authenticated = True
            await save_state(self.context, SESSION_FILE)
            logger.info("Logged in successfully")

        except Exception:
            raise LoginError()

        finally:
            await page.close()

    @try_except_request
    async def logout(self):
        SESSION_FILE.unlink(missing_ok=True)
        logger.info("Logged out successfully")

    @try_except_request
    @login_required
    async def fetch_unit(self, url: str):
        return await collectors.fetch_unit(self.context, url)

    @try_except_request
    @login_required
    async def fetch_course(self, url: str):
        return await collectors.fetch_course(self.context, url)

    @try_except_request
    @login_required
    async def download(self, url: str, **kwargs):
        from pathlib import Path

        from .downloaders import download_course, download_unit
        from .models import TypeUnit
        from .utils import is_course, is_lecture, is_quiz, is_video

        if is_video(url) or is_lecture(url) or is_quiz(url):
            unit = await self.fetch_unit(url)
            extension = ".mp4" if unit.type == TypeUnit.VIDEO else ".mhtml"
            await download_unit(
                self.context,
                unit,
                Path(unit.slug + extension),
                **kwargs,
            )

        elif is_course(url):
            course = await self.fetch_course(url)
            await download_course(self.context, course, **kwargs)

        else:
            raise Exception(
                "Please provide a valid URL, either a video, lecture or course."
            )

    @try_except_request
    async def set_cookies(self, path: Path):
        cookies = normalize_cookies(read_json(path))  # type: ignore
        await self.context.add_cookies(cookies)  # type: ignore
        await self._set_profile()
        await save_state(self.context, SESSION_FILE)

    @try_except_request
    async def _set_profile(self):
        SELECTOR = "h1.h1.f-text-34"
        TIMEOUT = 5 * 1000

        try:
            page = await self.page
            await page.goto(BASE_URL)

            welcome_message = await page.locator(SELECTOR).first.text_content(
                timeout=TIMEOUT
            )

            if welcome_message:
                self.authenticated = True
                logger.info(welcome_message)

        except Exception:
            pass

        finally:
            await page.close()
