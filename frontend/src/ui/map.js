import 'ol/ol.css';
import { Map, View } from 'ol'
import Feature from 'ol/Feature.js';
import XYZ from 'ol/source/XYZ';
import { fromLonLat } from 'ol/proj';
import TileLayer from 'ol/layer/Tile';
import VectorLayer from 'ol/layer/Vector';
import KML from 'ol/format/KML.js';
import VectorSource from 'ol/source/Vector.js';
import LineString from 'ol/geom/LineString.js';
import Point from 'ol/geom/Point.js';
import { transform } from 'ol/proj';
import CircleStyle from 'ol/style/Circle.js';
import Fill from 'ol/style/Fill.js';
import Stroke from 'ol/style/Stroke.js';
import Style from 'ol/style/Style.js';
import coordtransform from 'coordtransform';

const MARKER_TYPES = {
  START: 'start',
  END: 'end',
  ARROW: 'arrow',
};

const ARROW_SPACING_PIXELS = 96;
const ARROW_DIRECTION_WINDOW_PIXELS = 12;
const ARROW_ICON_LENGTH_PIXELS = 7;
const ARROW_ICON_HALF_WIDTH_PIXELS = 2.25;
const MAX_ARROW_COUNT = 128;

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

function transformGeometryToGcj02(geometry) {
  if (!geometry) return;

  if (geometry.getType() === 'GeometryCollection') {
    // getGeometries() returns clones, so transform the live geometries instead.
    geometry.getGeometriesArray().forEach(transformGeometryToGcj02);
    return;
  }

  const stride = geometry.getStride?.();
  if (!stride) return;

  geometry.applyTransform(coords => {
    for (let i = 0; i < coords.length; i += stride) {
      if (!Number.isFinite(coords[i]) || !Number.isFinite(coords[i + 1])) continue;

      let [lng, lat] = transform(
        [coords[i], coords[i + 1]],
        'EPSG:3857',
        'EPSG:4326'
      );
      [lng, lat] = coordtransform.wgs84togcj02(lng, lat);
      [coords[i], coords[i + 1]] = transform(
        [lng, lat],
        'EPSG:4326',
        'EPSG:3857'
      );
    }
    return coords;
  });
}

function getLineSegments(geometry) {
  if (!geometry) return [];

  switch (geometry.getType()) {
    case 'LineString':
      return [geometry.getCoordinates()];
    case 'MultiLineString':
      return geometry.getCoordinates();
    case 'GeometryCollection':
      return geometry.getGeometriesArray().flatMap(getLineSegments);
    default:
      return [];
  }
}

function getRouteSegments(vectorSource) {
  return vectorSource.getFeatures()
    .flatMap(feature => getLineSegments(feature.getGeometry()))
    .map(segment => segment.filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y)))
    .filter(segment => segment.length >= 2)
    .filter(segment => getSegmentLength(segment) > 0);
}

function getSegmentLength(segment) {
  let length = 0;
  for (let index = 1; index < segment.length; index += 1) {
    length += Math.hypot(
      segment[index][0] - segment[index - 1][0],
      segment[index][1] - segment[index - 1][1]
    );
  }
  return length;
}

function getRouteLength(segments) {
  return segments.reduce((total, segment) => total + getSegmentLength(segment), 0);
}

function getCoordinateAtDistance(segment, distance) {
  let remaining = distance;

  for (let index = 1; index < segment.length; index += 1) {
    const previous = segment[index - 1];
    const current = segment[index];
    const deltaX = current[0] - previous[0];
    const deltaY = current[1] - previous[1];
    const segmentLength = Math.hypot(deltaX, deltaY);
    if (segmentLength === 0) continue;

    if (remaining <= segmentLength) {
      const ratio = remaining / segmentLength;
      return {
        coordinate: [
          previous[0] + deltaX * ratio,
          previous[1] + deltaY * ratio,
        ],
      };
    }
    remaining -= segmentLength;
  }

  const current = segment[segment.length - 1];
  return {
    coordinate: [...current],
  };
}

function getRouteLocationAtDistance(segments, distance) {
  let remaining = distance;
  for (const segment of segments) {
    const segmentLength = getSegmentLength(segment);
    if (remaining <= segmentLength) {
      return { segment, segmentLength, distance: remaining };
    }
    remaining -= segmentLength;
  }
  const lastSegment = segments[segments.length - 1];
  const segmentLength = getSegmentLength(lastSegment);
  return { segment: lastSegment, segmentLength, distance: segmentLength };
}

function getArrowCount(totalLength, resolution) {
  const spacing = Math.max(resolution * ARROW_SPACING_PIXELS, 1);
  return clamp(Math.floor(totalLength / spacing), 1, MAX_ARROW_COUNT);
}

function getDirection(from, to) {
  const deltaX = to[0] - from[0];
  const deltaY = to[1] - from[1];
  const length = Math.hypot(deltaX, deltaY);
  return length > 0 ? [deltaX / length, deltaY / length] : null;
}

function getDirectionAtDistance(segment, distance) {
  let remaining = distance;
  let fallback = null;

  for (let index = 1; index < segment.length; index += 1) {
    const direction = getDirection(segment[index - 1], segment[index]);
    if (!direction) continue;

    const edgeLength = Math.hypot(
      segment[index][0] - segment[index - 1][0],
      segment[index][1] - segment[index - 1][1]
    );
    fallback = direction;
    if (remaining <= edgeLength) return direction;
    remaining -= edgeLength;
  }
  return fallback || [1, 0];
}

function getSmoothedRouteDirection(routeLocation, resolution) {
  const { segment, segmentLength, distance } = routeLocation;
  const windowLength = Math.min(
    resolution * ARROW_DIRECTION_WINDOW_PIXELS,
    segmentLength
  );
  const startDistance = clamp(
    distance - windowLength / 2,
    0,
    segmentLength - windowLength
  );
  const start = getCoordinateAtDistance(segment, startDistance).coordinate;
  const end = getCoordinateAtDistance(segment, startDistance + windowLength).coordinate;
  return getDirection(start, end) || getDirectionAtDistance(segment, distance);
}

function createArrowGeometry(routeLocation, resolution) {
  const { segment, distance } = routeLocation;
  const center = getCoordinateAtDistance(segment, distance).coordinate;
  const [directionX, directionY] = getSmoothedRouteDirection(routeLocation, resolution);
  const normal = [-directionY, directionX];
  const halfLength = resolution * ARROW_ICON_LENGTH_PIXELS / 2;
  const halfWidth = resolution * ARROW_ICON_HALF_WIDTH_PIXELS;
  const tip = [
    center[0] + directionX * halfLength,
    center[1] + directionY * halfLength,
  ];
  const base = [
    center[0] - directionX * halfLength,
    center[1] - directionY * halfLength,
  ];
  const leftWing = [
    base[0] + normal[0] * halfWidth,
    base[1] + normal[1] * halfWidth,
  ];
  const rightWing = [
    base[0] - normal[0] * halfWidth,
    base[1] - normal[1] * halfWidth,
  ];

  return new LineString([leftWing, tip, rightWing]);
}

function createAnnotationFeatures(vectorSource, resolution) {
  const segments = getRouteSegments(vectorSource);
  if (!segments.length) return [];

  const totalLength = getRouteLength(segments);
  const features = [
    new Feature({
      geometry: new Point(segments[0][0]),
      annotationType: MARKER_TYPES.START,
    }),
    new Feature({
      geometry: new Point(segments[segments.length - 1][segments[segments.length - 1].length - 1]),
      annotationType: MARKER_TYPES.END,
    }),
  ];

  const arrowCount = getArrowCount(totalLength, resolution);
  const interval = totalLength / (arrowCount + 1);
  for (let index = 1; index <= arrowCount; index += 1) {
    const routeLocation = getRouteLocationAtDistance(segments, interval * index);
    features.push(new Feature({
      geometry: createArrowGeometry(routeLocation, resolution),
      annotationType: MARKER_TYPES.ARROW,
    }));
  }

  return features;
}

function createAnnotationStyle(feature, resolution) {
  const markerType = feature.get('annotationType');
  const radius = clamp(32 / resolution, 2, 6);
  const strokeWidth = clamp(1.4 / resolution, 1, 2);

  if (markerType === MARKER_TYPES.ARROW) {
    return new Style({
      stroke: new Stroke({
        color: 'rgba(30, 94, 180, 0.86)',
        width: 2,
        lineCap: 'round',
        lineJoin: 'round',
      }),
      zIndex: 2,
    });
  }

  const isStart = markerType === MARKER_TYPES.START;
  return new Style({
    image: new CircleStyle({
      radius,
      fill: new Fill({ color: isStart ? 'rgba(25, 155, 90, 0.88)' : 'rgba(210, 55, 55, 0.88)' }),
      stroke: new Stroke({ color: '#ffffff', width: strokeWidth }),
    }),
    zIndex: 3,
  });
}

let activeKmlObjectUrl = null;

function releaseKmlObjectUrl(objectUrl) {
  URL.revokeObjectURL(objectUrl);
  if (activeKmlObjectUrl === objectUrl) activeKmlObjectUrl = null;
}

export function destroyMap() {
  if (window.mapInstance) {
    window.mapInstance.dispose();
    window.mapInstance = null;
  }

  if (activeKmlObjectUrl) releaseKmlObjectUrl(activeKmlObjectUrl);

  const mapDom = document.getElementById('map');
  if (mapDom) mapDom.style.display = 'none';
}

export function createMap(kmlBlob) {
  destroyMap();

  // OpenStreetMap 瓦片图层
  // const osmLayer = new TileLayer({
  //   source: new XYZ({
  //     url: 'https://{a-c}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  //     maxZoom: 18,
  //     projection: 'EPSG:3857'
  //   })
  // });

  // 高德普通地图瓦片
  const gaodeLayer = new TileLayer({
    source: new XYZ({
      url: 'http://wprd0{1-4}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&style=7&x={x}&y={y}&z={z}',
      subdomains: ['1', '2', '3', '4'],
      maxZoom: 16,
      projection: 'EPSG:3857'
    })
  });

  // KML轨迹图层
  const tempUrl = URL.createObjectURL(kmlBlob);
  activeKmlObjectUrl = tempUrl;
  const vectorSource = new VectorSource({
    url: tempUrl,
    format: new KML({ extractStyles: false }),
  });
  const vector = new VectorLayer({
    source: vectorSource,
    style: {
      'stroke-color': '#FF0000',
      'stroke-width': 3
    }
  });

  const annotationSource = new VectorSource();
  const annotationLayer = new VectorLayer({
    source: annotationSource,
    style: createAnnotationStyle,
    declutter: false,
    updateWhileAnimating: true,
    updateWhileInteracting: true,
  });

  // 初始化地图
  const mapDom = document.getElementById('map');
  const map = new Map({
    target: mapDom,
    layers: [gaodeLayer, vector, annotationLayer],
    view: new View({
      center: fromLonLat([121.4737, 31.2304]),
      zoom: 10
    })
  });

  // 轨迹加载后自动缩放到合适视野
  const updateAnnotations = () => {
    const resolution = map.getView().getResolution();
    if (!resolution) return;
    annotationSource.clear();
    annotationSource.addFeatures(createAnnotationFeatures(vectorSource, resolution));
  };

  vectorSource.on('featuresloadend', function () {

    // 使用国内地图时，转换坐标系从WGS-84到GCJ-02
    try {
      vectorSource.getFeatures().forEach(feature => {
        transformGeometryToGcj02(feature.getGeometry());
      });
    } catch (e) { console.error('Error processing features:', e); }

    updateAnnotations();
    const vectorExtent = vectorSource.getExtent();
    console.log('Vector Extent:', vectorExtent);
    map.getView().fit(vectorExtent, { padding: [50, 50, 50, 50], maxZoom: 15 });
    releaseKmlObjectUrl(tempUrl);
  });

  vectorSource.on('featuresloaderror', () => releaseKmlObjectUrl(tempUrl));

  map.getView().on('change:resolution', updateAnnotations);

  // 将地图实例挂载到全局并显示
  window.mapInstance = map;
  mapDom.style.display = 'block';
}
