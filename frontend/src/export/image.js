import { toCanvas } from 'html-to-image';
import { showPop } from '../utils/pop';

export function exportResultImage(domId, name = '路线解析结果') {
  const node = document.getElementById(domId);
  if (!node) return;

  toCanvas(node, { cacheBust: true, pixelRatio: window.devicePixelRatio })
    .then(canvas => {
      // 复制图片到剪贴板
      copyImageToClipboard(canvas, name);
    });
}

/**
 * 辅助函数：将Canvas图片复制到系统剪贴板
 * @param {HTMLCanvasElement} canvas - 图片画布
 * @param {string} name - 图片名称（用于剪贴板标识）
 */
function copyImageToClipboard(canvas, name) {
  try {
    // 将Canvas转为Blob（剪贴板更推荐Blob格式）
    canvas.toBlob(async (blob) => {
      // 创建剪贴板项（支持多格式，这里只传图片）
      const clipboardItem = new ClipboardItem({
        'image/png': blob
      });
      // 写入剪贴板
      await navigator.clipboard.write([clipboardItem]);
      showPop('图片已复制到剪贴板！');
    }, 'image/png');
  } catch (err) {
    console.error('复制到剪贴板失败：', err);
    alert('❌ 复制图片到剪贴板失败，请手动下载图片');
  }
}