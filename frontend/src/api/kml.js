import { formatHourToHM } from '../utils/format';
import { setDifficulty } from '../ui/difficulty';
import { createMap } from '../ui/map';
import {
  getCachedRating,
  isCacheMatch,
  saveCachedRating,
} from '../storage/kml-cache';

function setStatus(message, className) {
  const statusText = document.getElementById('statusText');
  statusText.className = className;
  statusText.textContent = message;
}

function metricNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

export function renderKmlResult(data, kmlBlob) {
  document.getElementById('time-info').hidden = true;
  document.getElementById('total_distance_km').textContent =
    metricNumber(data.total_distance_km).toFixed(1) + ' km';
  document.getElementById('total_elevation_m').textContent =
    Math.round(metricNumber(data.total_elevation_m)) + ' m';
  document.getElementById('total_time_h').textContent =
    formatHourToHM(metricNumber(data.total_time_h));
  document.getElementById('speed_mean_km_h').textContent =
    metricNumber(data.speed_mean_km_h).toFixed(1) + ' km/h';
  document.getElementById('tired_level').textContent =
    metricNumber(data.tired_level, 1).toFixed(2);
  document.getElementById('elev_level').textContent =
    metricNumber(data.elev_level, 1).toFixed(2);

  setDifficulty(metricNumber(data.tired_level, 1));
  createMap(kmlBlob);
  document.getElementById('resultArea').style.display = 'block';
}

export async function parseKmlFile(file) {
  const resultArea = document.getElementById('resultArea');
  if (!file) {
    setStatus('请先选择一个KML文件', 'error');
    return { success: false };
  }

  if (!file.name.toLowerCase().endsWith('.kml')) {
    setStatus('仅支持 .kml 文件', 'error');
    return { success: false };
  }

  try {
    const cachedRecord = await getCachedRating(file.name);
    if (cachedRecord && isCacheMatch(cachedRecord, file)) {
      renderKmlResult(cachedRecord.metrics, cachedRecord.kmlBlob);
      setStatus('已从本地记录加载', 'success');
      return { success: true, fromCache: true, cacheChanged: false };
    }
  } catch (error) {
    console.warn('Unable to read the local KML cache:', error);
  }

  try {
    setStatus('解析中...', 'loading');
    resultArea.style.display = 'none';
    document.getElementById('time-info').hidden = true;

    const formData = new FormData();
    formData.append('kml_file', file);
    const res = await fetch('/api/parse_kml', {
      method: 'POST',
      body: formData
    });
    const payload = await res.json().catch(() => null);

    if (!res.ok) {
      throw new Error(payload?.msg || `请求失败 (${res.status})`);
    }

    const data = payload?.data;
    if (!data || typeof data !== 'object') {
      throw new Error('服务返回了无效的评测结果');
    }

    renderKmlResult(data, file);

    let cacheChanged = false;
    let cacheSaveFailed = false;
    try {
      await saveCachedRating(file, data);
      cacheChanged = true;
    } catch (error) {
      console.warn('Unable to save the local KML cache:', error);
      cacheSaveFailed = true;
    }

    setStatus(
      cacheSaveFailed ? '解析完成，但无法保存本地记录' : '解析完成',
      cacheSaveFailed ? 'warning' : 'success'
    );
    return { success: true, fromCache: false, cacheChanged };
  } catch (e) {
    setStatus(`解析失败：${e.message}`, 'error');
    return { success: false };
  }
}
