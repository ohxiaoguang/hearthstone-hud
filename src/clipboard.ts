/** Decky SDK exposes file copying, but no supported text clipboard wrapper.
 * Returns a stable code ('clipboard' or 'fallback') so callers can localize the status. */
export async function copyText(text: string, clipboard = globalThis.navigator?.clipboard, doc = globalThis.document): Promise<string> {
  const errors: string[] = [];
  if (clipboard?.writeText) {
    try { await clipboard.writeText(text); return 'clipboard'; }
    catch (e) { errors.push(String(e)); }
  }
  if (doc?.body) {
    const focus = doc.activeElement as HTMLElement | null;
    const input = doc.createElement('textarea');
    input.value = text; input.readOnly = true;
    input.style.cssText = 'position:fixed;left:-10000px;top:0';
    doc.body.appendChild(input);
    try {
      input.focus(); input.select();
      if (doc.execCommand?.('copy')) return 'fallback';
      errors.push('compat copy API returned false');
    } catch (e) { errors.push(String(e)); }
    finally { input.remove(); focus?.focus?.(); }
  }
  throw new Error(errors.join('; ') || 'no text clipboard API available');
}
