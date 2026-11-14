/** Decky SDK exposes file copying, but no supported text clipboard wrapper. */
export async function copyText(text: string, clipboard = globalThis.navigator?.clipboard, doc = globalThis.document): Promise<string> {
  const errors: string[] = [];
  if (clipboard?.writeText) {
    try { await clipboard.writeText(text); return '系统剪贴板'; }
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
      if (doc.execCommand?.('copy')) return '兼容复制';
      errors.push('兼容复制 API 返回失败');
    } catch (e) { errors.push(String(e)); }
    finally { input.remove(); focus?.focus?.(); }
  }
  throw new Error(errors.join('；') || '当前环境没有可用的文本剪贴板 API');
}
