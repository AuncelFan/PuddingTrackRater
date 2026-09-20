const DATABASE_NAME = 'pudding-track-rater';
const DATABASE_VERSION = 1;
const STORE_NAME = 'kml-ratings';
const CACHE_SCHEMA_VERSION = 1;

function openDatabase() {
  if (!window.indexedDB) {
    return Promise.reject(new Error('当前浏览器不支持 IndexedDB'));
  }

  return new Promise((resolve, reject) => {
    const request = window.indexedDB.open(DATABASE_NAME, DATABASE_VERSION);

    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        database.createObjectStore(STORE_NAME, { keyPath: 'fileName' });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error('无法打开本地记录'));
    request.onblocked = () => reject(new Error('本地记录正在被其他页面占用'));
  });
}

async function runTransaction(mode, operation) {
  const database = await openDatabase();

  try {
    return await new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, mode);
      const request = operation(transaction.objectStore(STORE_NAME));
      let result;

      if (request) {
        request.onsuccess = () => {
          result = request.result;
        };
      }

      transaction.oncomplete = () => resolve(result);
      transaction.onerror = () => reject(
        transaction.error || request?.error || new Error('本地记录操作失败')
      );
      transaction.onabort = () => reject(
        transaction.error || request?.error || new Error('本地记录操作已中止')
      );
    });
  } finally {
    database.close();
  }
}

function hasValidMetrics(metrics) {
  if (!metrics || typeof metrics !== 'object') return false;

  return [
    'total_distance_km',
    'total_elevation_m',
    'tired_level',
    'elev_level',
  ].every(key => metrics[key] != null && Number.isFinite(Number(metrics[key])));
}

function isValidRecord(record) {
  return record?.schemaVersion === CACHE_SCHEMA_VERSION
    && typeof record.fileName === 'string'
    && record.fileName.length > 0
    && record.kmlBlob instanceof Blob
    && record.kmlBlob.size === record.fileSize
    && Number.isFinite(record.fileSize)
    && Number.isFinite(record.lastModified)
    && Number.isFinite(record.cachedAt)
    && hasValidMetrics(record.metrics);
}

export function isCacheMatch(record, file) {
  return isValidRecord(record)
    && record.fileName === file?.name
    && record.fileSize === file.size
    && record.lastModified === file.lastModified;
}

export async function getCachedRating(fileName) {
  const record = await runTransaction('readonly', store => store.get(fileName));
  if (!record) return null;

  if (!isValidRecord(record)) {
    await deleteCachedRating(fileName);
    return null;
  }

  return record;
}

export async function listCachedRatings() {
  const records = await runTransaction('readonly', store => store.getAll());
  const validRecords = [];
  const invalidNames = [];

  for (const record of records || []) {
    if (isValidRecord(record)) {
      validRecords.push(record);
    } else if (typeof record?.fileName === 'string') {
      invalidNames.push(record.fileName);
    }
  }

  await Promise.all(invalidNames.map(fileName => (
    deleteCachedRating(fileName).catch(() => undefined)
  )));

  return validRecords.sort((first, second) => second.cachedAt - first.cachedAt);
}

export async function saveCachedRating(file, metrics) {
  const record = {
    fileName: file.name,
    kmlBlob: file.slice(0, file.size, file.type || 'application/vnd.google-earth.kml+xml'),
    metrics,
    fileSize: file.size,
    lastModified: file.lastModified,
    cachedAt: Date.now(),
    schemaVersion: CACHE_SCHEMA_VERSION,
  };

  await runTransaction('readwrite', store => store.put(record));
  return record;
}

export function deleteCachedRating(fileName) {
  return runTransaction('readwrite', store => store.delete(fileName));
}

export function clearCachedRatings() {
  return runTransaction('readwrite', store => store.clear());
}
