// 只解析分享入口，不向粘贴链接的主机发送请求。
export function parseShareLink(value) {
  const raw = String(value || '').trim();
  let path = raw;
  if (!raw.startsWith('#/')) {
    let url;
    try { url = new URL(raw, 'http://localhost/'); } catch { throw new Error('请输入完整题目或题库分享链接。'); }
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error('分享链接格式无效。');
    path = url.hash || url.pathname;
  }
  const match = path.match(/^(?:#\/shared-(question|bank)\/|\/shared\/(questions|banks)\/)([A-Za-z0-9_-]{8,200})$/);
  if (!match) throw new Error('请输入题目或题库分享链接。');
  return {kind: match[1] || (match[2] === 'questions' ? 'question' : 'bank'), token: match[3]};
}
