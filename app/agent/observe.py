"""Page observation for the agent loop: a bounded, LLM-friendly element list.

Text is extracted from the DOM/accessibility attributes only (no screenshots);
secret values are redacted before they leave this module.
"""

from __future__ import annotations

from playwright.async_api import Page

OBSERVE_JS = """
() => {
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' &&
           style.display !== 'none' && style.opacity !== '0';
  };
  const labelOf = (el) => {
    const aria = el.getAttribute('aria-label');
    if (aria) return aria.trim();
    if (el.id) {
      const target = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (target) return target.textContent.trim();
    }
    const wrapped = el.closest('label');
    if (wrapped) return wrapped.textContent.trim();
    if (el.placeholder) return el.placeholder.trim();
    if (el.tagName === 'INPUT' && (el.type === 'submit' || el.type === 'button')) return (el.value || '').trim();
    return (el.textContent || el.value || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
  };
  const nodes = Array.from(document.querySelectorAll('a, button, input, select, textarea')).filter(visible);
  const elements = nodes.slice(0, 60).map((el, index) => {
    el.setAttribute('data-agent-id', String(index + 1));
    let value = '';
    if (el.tagName === 'SELECT') {
      value = el.options[el.selectedIndex] ? el.options[el.selectedIndex].text.trim() : '';
    } else if (el.type === 'checkbox' || el.type === 'radio') {
      value = el.checked ? 'checked' : 'unchecked';
    } else {
      value = (el.value || '').toString();
    }
    const label = labelOf(el).slice(0, 60);
    if (el.type === 'password' || /otp/i.test(label)) value = value ? '[REDACTED]' : '';
    return {
      id: index + 1,
      tag: el.tagName.toLowerCase(),
      type: el.type || '',
      role: el.getAttribute('role') || el.tagName.toLowerCase(),
      label,
      value: value.slice(0, 60),
      disabled: !!el.disabled,
    };
  }).filter((el) => !el.disabled);
  const headingEl = document.querySelector('h1');
  return {
    path: location.pathname,
    heading: headingEl ? headingEl.textContent.trim().slice(0, 80) : '',
    elements,
  };
}
"""


async def observe_page(page: Page) -> dict:
    data = await page.evaluate(OBSERVE_JS)
    return {
        "path": data.get("path", ""),
        "heading": data.get("heading", ""),
        "elements": data.get("elements", []),
    }
