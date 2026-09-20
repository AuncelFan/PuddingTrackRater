import { parseKmlFile, renderKmlResult } from '../api/kml';
import { exportResultImage } from '../export/image';
import { destroyMap } from './map';
import {
  clearCachedRatings,
  deleteCachedRating,
  listCachedRatings,
} from '../storage/kml-cache';

function formatCacheDate(timestamp) {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(timestamp));
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function bindEvents() {
  const dropZone = document.getElementById('kmlDropZone');
  const selectedFileBox = document.getElementById('selectedFileBox');
  const fileInput = document.getElementById('kmlFileInput');
  const fileNameText = document.getElementById('fileNameText');
  const clearFileButton = document.getElementById('clearFileBtn');
  const parseButton = document.getElementById('parseBtn');
  const statusText = document.getElementById('statusText');
  const resultArea = document.getElementById('resultArea');
  const historyPanel = document.getElementById('historyPanel');
  const historyList = document.getElementById('historyList');
  const clearHistoryButton = document.getElementById('clearHistoryBtn');
  let selectedFile = null;
  let activeCacheFileName = null;
  let historyRecords = [];
  let dragDepth = 0;

  const showStatus = (message, className = 'tip') => {
    statusText.className = className;
    statusText.textContent = message;
  };

  const updateHistoryVisibility = () => {
    historyPanel.hidden = Boolean(selectedFile) || historyRecords.length === 0;
  };

  const renderHistory = records => {
    historyRecords = records;
    historyList.replaceChildren();

    for (const record of records) {
      const item = document.createElement('li');
      item.className = 'history-item';

      const openButton = document.createElement('button');
      openButton.type = 'button';
      openButton.className = 'history-open-btn';
      openButton.setAttribute('aria-label', `打开本地记录 ${record.fileName}`);

      const name = document.createElement('span');
      name.className = 'history-file-name';
      name.textContent = record.fileName;

      const meta = document.createElement('span');
      meta.className = 'history-meta';
      meta.textContent = `${formatCacheDate(record.cachedAt)} · ${formatFileSize(record.fileSize)}`;

      openButton.append(name, meta);

      const deleteButton = document.createElement('button');
      deleteButton.type = 'button';
      deleteButton.className = 'history-delete-btn';
      deleteButton.textContent = '删除';
      deleteButton.setAttribute('aria-label', `删除本地记录 ${record.fileName}`);

      item.append(openButton, deleteButton);
      historyList.append(item);

      openButton.addEventListener('click', () => restoreHistoryRecord(record));
      deleteButton.addEventListener('click', () => removeHistoryRecord(record.fileName));
    }

    updateHistoryVisibility();
  };

  const refreshHistory = async () => {
    try {
      renderHistory(await listCachedRatings());
    } catch (error) {
      console.warn('Unable to list the local KML cache:', error);
      renderHistory([]);
      showStatus('无法读取本地记录，仍可正常解析文件', 'warning');
    }
  };

  const clearSelection = () => {
    selectedFile = null;
    activeCacheFileName = null;
    fileInput.value = '';
    fileNameText.textContent = '未选择文件';
    dropZone.hidden = false;
    selectedFileBox.hidden = true;
    parseButton.disabled = true;
    dropZone.setAttribute('aria-label', '选择或拖放 KML 文件');
    resultArea.style.display = 'none';
    destroyMap();
    updateHistoryVisibility();
    showStatus('');
  };

  const selectFile = (file, cacheFileName = null) => {
    if (!file?.name.toLowerCase().endsWith('.kml')) {
      clearSelection();
      showStatus('仅支持 .kml 文件', 'error');
      return;
    }

    selectedFile = file;
    activeCacheFileName = cacheFileName;
    fileInput.value = '';
    fileNameText.textContent = file.name;
    dropZone.hidden = true;
    selectedFileBox.hidden = false;
    parseButton.disabled = false;
    updateHistoryVisibility();
    showStatus('');
  };

  async function restoreHistoryRecord(record) {
    try {
      const file = new File([record.kmlBlob], record.fileName, {
        type: record.kmlBlob.type || 'application/vnd.google-earth.kml+xml',
        lastModified: record.lastModified,
      });
      selectFile(file, record.fileName);
      renderKmlResult(record.metrics, record.kmlBlob);
      showStatus('已从本地记录加载', 'success');
    } catch (error) {
      console.warn('Unable to restore the local KML cache:', error);
      await deleteCachedRating(record.fileName).catch(() => undefined);
      clearSelection();
      await refreshHistory();
      showStatus('本地记录已损坏，请重新选择原文件', 'error');
    }
  }

  async function removeHistoryRecord(fileName) {
    try {
      await deleteCachedRating(fileName);
      if (activeCacheFileName === fileName) clearSelection();
      await refreshHistory();
      showStatus('已删除本地记录', 'success');
    } catch (error) {
      console.warn('Unable to delete the local KML cache:', error);
      showStatus('删除本地记录失败', 'error');
    }
  }

  const openFilePicker = event => {
    if (event.target !== fileInput) fileInput.click();
  };

  dropZone?.addEventListener('click', openFilePicker);
  dropZone?.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      fileInput.click();
    }
  });

  fileInput?.addEventListener('change', event => {
    const file = event.target.files?.[0];
    if (file) selectFile(file);
  });

  clearFileButton?.addEventListener('click', clearSelection);

  dropZone?.addEventListener('dragenter', event => {
    event.preventDefault();
    dragDepth += 1;
    dropZone.classList.add('is-dragging');
  });

  dropZone?.addEventListener('dragover', event => {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
  });

  dropZone?.addEventListener('dragleave', event => {
    event.preventDefault();
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) dropZone.classList.remove('is-dragging');
  });

  dropZone?.addEventListener('drop', event => {
    event.preventDefault();
    dragDepth = 0;
    dropZone.classList.remove('is-dragging');
    selectFile(event.dataTransfer.files?.[0]);
  });

  document.addEventListener('dragover', event => {
    if (Array.from(event.dataTransfer?.types || []).includes('Files')) {
      event.preventDefault();
    }
  });

  document.addEventListener('drop', event => {
    if (event.dataTransfer?.files.length) event.preventDefault();
  });

  parseButton?.addEventListener('click', async () => {
    const fileToParse = selectedFile;
    parseButton.disabled = true;
    parseButton.setAttribute('aria-busy', 'true');
    clearFileButton.disabled = true;

    try {
      const parsed = await parseKmlFile(fileToParse);
      if (parsed.success) {
        activeCacheFileName = parsed.fromCache || parsed.cacheChanged
          ? fileToParse.name
          : null;
        if (parsed.cacheChanged) await refreshHistory();
      }
    } finally {
      parseButton.disabled = !selectedFile;
      parseButton.removeAttribute('aria-busy');
      clearFileButton.disabled = false;
    }
  });

  clearHistoryButton?.addEventListener('click', async () => {
    if (!window.confirm('确定清空全部本地记录吗？')) return;

    try {
      await clearCachedRatings();
      if (activeCacheFileName) clearSelection();
      renderHistory([]);
      showStatus('已清空本地记录', 'success');
    } catch (error) {
      console.warn('Unable to clear the local KML cache:', error);
      showStatus('清空本地记录失败', 'error');
    }
  });

  // 显示/关闭时间信息按钮
  document.getElementById('show-speed-btn')?.addEventListener('click', () => {
    const timeInfo = document.getElementById('time-info');
    timeInfo.hidden = !timeInfo.hidden;
  });

  // 保存结果按钮
  document.getElementById('save-result-btn')?.addEventListener('click', () => {
    exportResultImage('result-info');
  });

  refreshHistory();
}
