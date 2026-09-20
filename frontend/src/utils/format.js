export function formatHourToHM(hours) {
  const totalMinutes = Math.round(hours * 60);
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  return `${h}时${m}分`;
}

/**
 * 适配中文字符的填充函数（中文字符计2个长度，英文/数字计1个）
 * @param {string} str - 原字符串
 * @param {number} targetWidth - 目标视觉宽度（按英文字符数计）
 * @returns {string} 填充后的字符串
 */
export function padEndWithCharWidth(str, targetWidth) {
  const strVal = String(str);
  // 计算字符串的"视觉长度"（中文=2，英文/数字=1）
  let visualLength = 0;
  for (const char of strVal) {
    // 匹配中文字符（包括中文、全角符号等）
    visualLength += /[\u4e00-\u9fa5\u3000-\u303f\uff00-\uffef]/.test(char) ? 2 : 1;
  }

  // 超出则截断（简单截断，如需精准截断可扩展）
  if (visualLength >= targetWidth) {
    return strVal.slice(0, targetWidth);
  }

  // 计算需要填充的空格数（非断行空格）
  const padLength = targetWidth - visualLength;
  return strVal + '\u00A0'.repeat(padLength);
}