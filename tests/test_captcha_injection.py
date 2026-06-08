"""CAPTCHA injection strategies — form / callback / click."""

import pytest

from ariadne.captcha import (
    CallbackInjection,
    ClickInjection,
    FormSubmitInjection,
    InjectionConfig,
    StubCaptchaSolver,
    inject_and_click_element,
    inject_and_submit_form,
    inject_and_trigger_callback,
    solve_and_inject,
)


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    async def count(self):
        return 1 if self.selector in self.page.fields else 0

    async def fill(self, value):
        self.page.fields[self.selector] = value


class FakePage:
    def __init__(self):
        self.fields: dict[str, str] = {
            'textarea[name="g-recaptcha-response"]': "",
            "form": "present",
            "#submit-btn": "present",
        }
        self.submitted = False
        self.clicked = None
        self.callbacks: list[tuple] = []

    def locator(self, selector):
        return FakeLocator(self, selector)

    async def fill(self, selector, value):
        self.fields[selector] = value

    async def eval_on_selector(self, selector, script):
        assert selector
        self.submitted = True

    async def evaluate(self, script, arg=None):
        if isinstance(arg, list) and len(arg) == 2:
            self.callbacks.append((arg[0], arg[1]))
            return None
        self.callbacks.append((script, arg))
        return None

    async def click(self, selector):
        self.clicked = selector


@pytest.mark.asyncio
async def test_form_submit_injection():
    page = FakePage()
    await inject_and_submit_form(
        page, "tok123", 'textarea[name="g-recaptcha-response"]', "form"
    )
    assert page.fields['textarea[name="g-recaptcha-response"]'] == "tok123"
    assert page.submitted is True


@pytest.mark.asyncio
async def test_callback_injection_requires_name():
    page = FakePage()
    with pytest.raises(RuntimeError, match="callback_name"):
        await CallbackInjection().apply(
            page, "tok", InjectionConfig(kind="callback", callback_name=None)
        )


@pytest.mark.asyncio
async def test_callback_injection_triggers():
    page = FakePage()
    await inject_and_trigger_callback(page, "tok456", "window.onCaptchaSuccess")
    assert page.callbacks
    assert page.callbacks[0][0] == "window.onCaptchaSuccess"
    assert page.callbacks[0][1] == "tok456"


@pytest.mark.asyncio
async def test_click_injection():
    page = FakePage()
    await inject_and_click_element(
        page, "tok789", 'textarea[name="g-recaptcha-response"]', "#submit-btn"
    )
    assert page.clicked == "#submit-btn"


@pytest.mark.asyncio
async def test_solve_and_inject_stub():
    page = FakePage()
    result = await solve_and_inject(
        page,
        site_key="6LeTestKeyXXXX",
        page_url="https://example.com",
        challenge_type="recaptcha",
        injection=InjectionConfig(kind="form", form_selector="form"),
        provider="stub",
    )
    assert result.provider == "stub"
    assert "stub-token" in result.token
    assert page.submitted is True


@pytest.mark.asyncio
async def test_stub_solver_token():
    r = await StubCaptchaSolver().solve(
        site_key="abcdefghij", page_url="https://x", challenge_type="turnstile"
    )
    assert r.token.startswith("stub-token:turnstile:abcdefgh")
