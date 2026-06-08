"""CAPTCHA solver plugins with target-specific InjectionStrategy.

Token fetch is ~20% of the work; submission via form / JS callback / click is the rest.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

InjectionKind = Literal["form", "callback", "click"]


@dataclass
class SolveResult:
    token: str
    provider: str
    challenge_type: str  # turnstile | recaptcha | hcaptcha | unknown


@dataclass
class InjectionConfig:
    kind: InjectionKind
    token_field_selector: str = 'textarea[name="g-recaptcha-response"], input[name="cf-turnstile-response"]'
    form_selector: str | None = "form"
    callback_name: str | None = None  # e.g. explicit callback; or leave null to resolve
    click_selector: str | None = None


class InjectionStrategy(abc.ABC):
    @abc.abstractmethod
    async def apply(self, page: Any, token: str, config: InjectionConfig) -> None: ...


class FormSubmitInjection(InjectionStrategy):
    async def apply(self, page: Any, token: str, config: InjectionConfig) -> None:
        await page.fill(config.token_field_selector, token)
        form = config.form_selector or "form"
        await page.eval_on_selector(form, "f => f.submit()")


class CallbackInjection(InjectionStrategy):
    async def apply(self, page: Any, token: str, config: InjectionConfig) -> None:
        # Set common hidden fields first (best-effort; sites vary)
        for sel in {
            'textarea[name="g-recaptcha-response"]',
            'input[name="g-recaptcha-response"]',
            'input[name="cf-turnstile-response"]',
            config.token_field_selector,
        }:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.fill(token)
            except Exception:
                pass

        if not config.callback_name:
            raise RuntimeError(
                "CallbackInjection requires injection.callback_name for this target "
                "(dynamic ___grecaptcha_cfg paths are site-specific; do not guess)"
            )
        # callback_name is a JS expression that evaluates to a function, e.g.
        # "___grecaptcha_cfg.clients[0].X.X" or "window.onCaptchaSuccess"
        await page.evaluate(
            """([expr, tok]) => {
                const fn = (0, eval)('(' + expr + ')');
                if (typeof fn !== 'function') throw new Error('callback is not a function: ' + expr);
                return fn(tok);
            }""",
            [config.callback_name, token],
        )


class ClickInjection(InjectionStrategy):
    async def apply(self, page: Any, token: str, config: InjectionConfig) -> None:
        await page.fill(config.token_field_selector, token)
        if not config.click_selector:
            raise RuntimeError("ClickInjection requires injection.click_selector")
        await page.click(config.click_selector)


STRATEGIES: dict[InjectionKind, InjectionStrategy] = {
    "form": FormSubmitInjection(),
    "callback": CallbackInjection(),
    "click": ClickInjection(),
}


async def inject_and_submit_form(page: Any, token: str, field_selector: str, form_selector: str) -> None:
    await FormSubmitInjection().apply(
        page, token, InjectionConfig(kind="form", token_field_selector=field_selector, form_selector=form_selector)
    )


async def inject_and_trigger_callback(page: Any, token: str, callback_name: str) -> None:
    await CallbackInjection().apply(
        page, token, InjectionConfig(kind="callback", callback_name=callback_name)
    )


async def inject_and_click_element(
    page: Any, token: str, field_selector: str, click_selector: str
) -> None:
    await ClickInjection().apply(
        page,
        token,
        InjectionConfig(
            kind="click", token_field_selector=field_selector, click_selector=click_selector
        ),
    )


class CaptchaSolver(abc.ABC):
    @abc.abstractmethod
    async def solve(self, *, site_key: str, page_url: str, challenge_type: str) -> SolveResult: ...


class NullCaptchaSolver(CaptchaSolver):
    """Placeholder when no provider configured — tests / dry-run."""

    async def solve(self, *, site_key: str, page_url: str, challenge_type: str) -> SolveResult:
        raise RuntimeError("No CAPTCHA provider configured (set ARIADNE_CAPTCHA_PROVIDER)")


class StubCaptchaSolver(CaptchaSolver):
    """Returns a deterministic token for unit/integration tests."""

    async def solve(self, *, site_key: str, page_url: str, challenge_type: str) -> SolveResult:
        return SolveResult(
            token=f"stub-token:{challenge_type}:{site_key[:8]}",
            provider="stub",
            challenge_type=challenge_type,
        )


def get_solver(provider: str | None) -> CaptchaSolver:
    if provider in {None, "", "null"}:
        return NullCaptchaSolver()
    if provider == "stub":
        return StubCaptchaSolver()
    # Real 2captcha/capsolver adapters land as thin HTTP clients; stub for structure.
    logger.warning("CAPTCHA provider %r not fully implemented; using stub token path", provider)
    return StubCaptchaSolver()


async def solve_and_inject(
    page: Any,
    *,
    site_key: str,
    page_url: str,
    challenge_type: str,
    injection: InjectionConfig,
    provider: str | None = "stub",
) -> SolveResult:
    solver = get_solver(provider)
    result = await solver.solve(site_key=site_key, page_url=page_url, challenge_type=challenge_type)
    strategy = STRATEGIES[injection.kind]
    await strategy.apply(page, result.token, injection)
    return result
