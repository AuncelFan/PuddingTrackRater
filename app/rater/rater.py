import numpy as np
import pandas as pd
from typing import List, Tuple
from datetime import datetime
import io

from fastkml import KML
from fastkml.utils import find_all, find
from fastkml.kml import Placemark
from fastkml.gx import Track
from fastkml.geometry import LineString

from scipy.signal import savgol_filter
from scipy.interpolate import UnivariateSpline, make_interp_spline
from haversine import haversine_vector, Unit


# -------------------------- 配置参数 --------------------------
KML_NS = "http://www.opengis.net/kml/2.2"
GX_NS = "http://www.google.com/kml/ext/2.2"
NSMAP = {"kml": KML_NS, "gx": GX_NS}

DIV_EPS = 1e-6  # 避免除零错误的最小值


class Rater:
    """
    KML轨迹解析、预处理与难度评分器
    """

    config = {
        # preprocess
        "min_dist": 1.0,  # 最小距离去重阈值（米）
        "max_elev_rate": 1.0,  # 最大高程变化速率（米/秒）
        "interp_interval": 5.0,  # 距离重插值间隔（米）
        "elev_smooth_window": 15,  # 高程平滑窗口大小（奇数）
        "fill_nan_method": "spline",  # NaN填充方法：spline / linear
        # tired difficulty
        "window_size_tired_difficulty_short": 25,  # 短窗口体能难度计算窗口大小（米）
        "short_window_weight": 1.5,  # 短窗口体能难度权重指数
        "window_size_tired_difficulty_long": 200,  # 长窗口体能难度计算窗口大小（米）
        "long_window_weight": 1.0,  # 长窗口体能难度权重指数
        "base_tired_difficulty": 0.3,  # 基础体能难度
        "uphill_max_diff": 1.5,  # 最大上坡体能难度增量
        "downhill_max_diff": 0.1,  # 最大下坡体能难度增量
        "uphill_max_slope": 0.4,  # 上坡极大难度坡度阈值
        "downhill_max_slope": 0.10,  # 下坡极大难度坡度阈值
        # elevation difficulty
        "base_elev_difficulty": 0.0,  # 基础爬升难度
        "uphill_elev_sensitivity": 1.5,  # 爬升难度上坡灵敏度
        "downhill_elev_sensitivity": 1.6,  # 爬升难度下坡灵敏度
        # speed
        "window_size_speed": 5,  # 瞬时速度计算滑动窗口大小
        "high_speed_sensitivity": 0.45,  # 高速修正灵敏度
        "low_speed_sensitivity": 0.75,  # 低速修正灵敏度
        # score remap
        "tired_score_remap_a": 3.6,
        "tired_score_remap_b": 1500,
        "tired_score_remap_c": 1000,
        "elev_score_remap_a": 1.5,
        "elev_score_remap_b": 22,
        "elev_score_remap_c": 50,
    }

    def __init__(self):
        self.coords: np.ndarray | None = None  # (lat, lng, elev)
        self.times: List[datetime] | None = None

        self.has_metrics: bool = False

        self.delta_dists: np.ndarray | None = None  # n-1, 每段距离
        self.cum_dists: np.ndarray | None = None  # n, 累计距离
        self.delta_elevs: np.ndarray | None = None  # n-1, 每段高程变化
        self.slopes: np.ndarray | None = None  # n-1, 每段坡度
        self.total_distance: float | None = None  # 总距离
        self.total_elevation: float | None = None  # 总爬升

        self.timestamps: np.ndarray | None = None  # n, 每点时间戳
        self.delta_times: np.ndarray | None = None  # n-1, 每段时间差
        self.cum_times: np.ndarray | None = None  # n, 累计时间
        self.total_time: float | None = None  # 总用时
        self.speeds_km_h: np.ndarray | None = None  # n, 每点速度
        self.speed_mean: float | None = None  # 平均速度
        self.speed_std: float | None = None  # 速度标准差
        self.norm_speeds: np.ndarray | None = None  # n, 归一化速度
        self.speed_correction: np.ndarray | None = None  # n, 速度修正系数

        self.tired_score: float | None = None  # 体能难度积分
        self.elev_score: float | None = None  # 爬升难度积分

    @classmethod
    def from_kml(cls, kml_file: str | io.BytesIO) -> "Rater":
        rater = cls()
        coords, times = rater._parse_kml(kml_file)
        if coords is None:
            raise ValueError("无法解析KML文件或未找到有效轨迹数据")
        coords, times = rater._preprocess_trajectory(
            coords,
            times,
            min_dist=cls.config["min_dist"],
            max_elev_rate=cls.config["max_elev_rate"],
            elev_smooth_window=cls.config["elev_smooth_window"],
            fill_nan_method=cls.config["fill_nan_method"],
            interp_interval=cls.config["interp_interval"],
        )
        rater.coords = coords
        rater.times = times
        return rater

    @staticmethod
    def score_remap(x, a, b, c):
        """
        总分数重映射函数
        """
        if x <= c:  # 0-1 线性区间
            y = x / c
        else:  # 1+ 对数区间
            y = a * np.log((x - c) / b + 1) + 1
        return y

    def get_lat_lon(self) -> np.ndarray:
        """获取经纬度坐标数组: (lat, lon)"""
        if self.coords is None:
            raise ValueError("轨迹坐标数据未初始化")
        return self.coords[:, :2]

    def get_total_distance(self) -> float:
        """获取总距离（千米）"""
        if self.total_distance is None:
            self._compute_distance()
        return self.total_distance

    def _parse_kml(self, kml_file: str | io.BytesIO) -> Tuple[
        List[Tuple[float, float, float]] | None,
        List[datetime] | None,
    ]:
        coordinates = []
        times = []
        kml = KML.parse(kml_file, strict=False)

        # gx:Track
        tracks = list(find_all(kml, of_type=Track))
        if tracks:
            for track in tracks:
                for c in track.coords:
                    coordinates.append((c[1], c[0], c[2]))
                for w in track.whens:
                    times.append(w.dt)
            return self._check_coords_times(coordinates, times)

        # COROS Track Points
        folder = find(kml, name="Track Points")
        if folder:
            placemarks = list(find_all(folder, of_type=Placemark))
            for pm in placemarks:
                c = pm.geometry.coords[0]
                coordinates.append((c[1], c[0], c[2]))
                times.append(pm.times.begin.dt)
            return self._check_coords_times(coordinates, times)

        # LineString fallback
        linestrings = list(find_all(kml, of_type=LineString))
        for ls in linestrings:
            for c in ls.geometry.coords:
                coordinates.append((c[1], c[0], c[2]))
        return self._check_coords_times(coordinates, times)

    def _check_coords_times(
        self,
        coords: List[Tuple[float, float, float]] | None,
        times: List[datetime] | None,
    ) -> Tuple[
        List[Tuple[float, float, float]] | None,
        List[datetime] | None,
    ]:
        """修正坐标和时间戳"""

        if coords is None or len(coords) == 0:
            # print("No coordinates found")
            return None, None

        res_coords = coords
        res_times = times

        if len(times) == 0:
            # print("No timestamps found")
            res_times = None

        if res_times is not None:
            for t in times:
                if not isinstance(t, datetime):
                    res_times = None
                    # print(f"Invalid timestamp found, discarding all timestamps: {type(t)}: {t}")
                    break

        if res_times is not None and len(coords) != len(times):
            res_times = None
            # print(
            #     f"Mismatched number of coordinates and timestamps, discarding all timestamps: {len(coords)} coords vs {len(times)} times"
            # )

        for c in coords:
            if len(c) != 3:  # 经度、纬度、高度
                res_coords = None
                res_times = None
                # print(f"Invalid coordinate found, discarding all coordinates and timestamps: {c}")
                break

        return res_coords, res_times

    def _preprocess_trajectory(
        self,
        coords: List[Tuple[float, float, float]],
        times: List[datetime] | None,
        min_dist,  # 去重最小距离（米）
        max_elev_rate,  # 最大高程变化率（米/秒）
        elev_smooth_window,  # 滤波窗口（奇数）
        fill_nan_method,  # NaN填充方法：spline / linear
        interp_interval,  # 插值距离间隔（米）
    ) -> Tuple[np.ndarray, List[datetime] | None]:
        """
        轨迹预处理流程（距离参数化）：

        1. 基础校验
        2. 轻量空间去重（按距离）
        3. 高程全链路清洗（不插值）
        4. 按累计距离进行空间插值
        5. 时间戳后置插值
        """

        coords_arr = np.asarray(coords, dtype=np.float64)
        is_ts_none = times is None

        if len(coords_arr) < 2:
            return coords_arr, None if is_ts_none else times

        # 获取时间戳
        if not is_ts_none:
            ts_arr = np.asarray([t.timestamp() for t in times])
        else:
            ts_arr = None

        # 空间去重（距离小于min_dist）
        d = haversine_vector(
            coords_arr[:-1, :2],  # 前n-1个点
            coords_arr[1:, :2],  # 后n-1个点
            unit=Unit.METERS,
        )
        keep_idx = np.insert(d >= min_dist, 0, True)  # 保留第一个点
        coords_f = coords_arr[keep_idx]  # 过滤后的坐标
        ts_f = ts_arr[keep_idx] if ts_arr is not None else None  # 过滤后的时间戳

        if len(coords_f) < 2:
            return coords_f, (None if is_ts_none else [datetime.fromtimestamp(t) for t in ts_f])

        lat_lon = coords_f[:, :2]
        elev = coords_f[:, 2].copy()

        # NaN / Inf 填充
        bad = np.isnan(elev) | np.isinf(elev)
        if np.any(bad):
            idx = np.arange(len(elev))
            if np.sum(~bad) >= 2:
                if fill_nan_method == "spline":
                    spl = UnivariateSpline(idx[~bad], elev[~bad], k=2, s=1)
                    elev[bad] = spl(idx[bad])
                else:
                    elev[bad] = np.interp(idx[bad], idx[~bad], elev[~bad])
            else:
                elev[bad] = np.nanmean(elev)

        # 处理高程异常跳变
        if ts_f is not None and len(ts_f) >= 2:
            de = np.diff(elev)
            dt = np.diff(ts_f)
            dt[dt == 0] = 1e-3
            rate = np.abs(de) / dt
            abnormal = rate > max_elev_rate
            idxs = np.where(abnormal)[0] + 1
            lat_lon = np.delete(lat_lon, idxs, axis=0)
            elev = np.delete(elev, idxs)
            ts_f = np.delete(ts_f, idxs)

        cleaned_coords = np.column_stack([lat_lon, elev])

        # 按“累计距离”进行空间插值
        if interp_interval > 0 and len(cleaned_coords) >= 3:  # 至少3点才能插值
            cum_dist = self.cumulative_distance(lat_lon)
            total_dist = cum_dist[-1]

            if total_dist > 0:  # 距离有效才插值
                interp_dist = np.arange(0, total_dist, interp_interval)

                lat_spl = make_interp_spline(cum_dist, lat_lon[:, 0], k=3)
                lon_spl = make_interp_spline(cum_dist, lat_lon[:, 1], k=3)

                lat_i = lat_spl(interp_dist)
                lon_i = lon_spl(interp_dist)
                elev_i = np.interp(interp_dist, cum_dist, elev)

                cleaned_coords = np.column_stack([lat_i, lon_i, elev_i])

                if ts_f is not None:
                    ts_i = np.interp(interp_dist, cum_dist, ts_f)
                    final_ts = [datetime.fromtimestamp(t) for t in ts_i]
                else:
                    final_ts = None
            else:
                cleaned_coords = cleaned_coords
                final_ts = None if is_ts_none else [datetime.fromtimestamp(t) for t in ts_f]
        else:
            cleaned_coords = cleaned_coords
            final_ts = None if is_ts_none else [datetime.fromtimestamp(t) for t in ts_f]

        # 高程平滑滤波
        lat_lon = cleaned_coords[:, :2]
        elev = cleaned_coords[:, 2]
        max_smooth_window = len(elev) if len(elev) % 2 == 1 else len(elev) - 1
        elev_smooth_window = min(elev_smooth_window, max_smooth_window)
        elev = savgol_filter(elev, elev_smooth_window, polyorder=2)
        cleaned_coords = np.column_stack([lat_lon, elev])

        return cleaned_coords, final_ts

    def cumulative_distance(self, lat_lon: np.ndarray) -> np.ndarray:
        """计算累计路径长度（米）"""
        dists = haversine_vector(lat_lon[:-1], lat_lon[1:], unit=Unit.METERS)
        dists = np.insert(np.cumsum(dists), 0, 0.0)
        return dists

    def _compute_distance(self):
        """计算轨迹的距离信息"""
        if self.delta_dists is not None and self.cum_dists is not None and self.total_distance is not None:
            return
        if self.coords is None:
            raise ValueError("轨迹坐标数据未初始化")
        coords: np.ndarray = self.coords
        delta_dists = haversine_vector(coords[:-1, :2], coords[1:, :2], unit=Unit.METERS)
        self.delta_dists = delta_dists  # n-1, 米
        cum_dists = np.insert(np.cumsum(delta_dists), 0, 0.0)
        self.cum_dists = cum_dists  # n, 米
        total_distance = cum_dists[-1] / 1000.0
        self.total_distance = total_distance  # 千米

    def _compute_elevation(self):
        """计算轨迹的高程信息"""
        if self.delta_elevs is not None and self.total_elevation is not None:
            return
        if self.coords is None:
            raise ValueError("轨迹坐标数据未初始化")
        coords: np.ndarray = self.coords
        delta_elevs = coords[1:, 2] - coords[:-1, 2]
        self.delta_elevs = delta_elevs  # n-1, 米
        total_elevation = np.sum(delta_elevs, where=delta_elevs > 0)
        self.total_elevation = total_elevation  # 米

    def _compute_slope(self):
        """计算轨迹的坡度信息"""
        if self.slopes is not None:
            return
        if self.delta_dists is None:
            raise ValueError("必须先计算距离信息")
        if self.delta_elevs is None:
            raise ValueError("必须先计算高程信息")
        slopes = np.divide(
            self.delta_elevs,
            self.delta_dists,
            out=np.zeros_like(self.delta_elevs, dtype=np.float64),
            where=self.delta_dists > DIV_EPS,
        )
        self.slopes = slopes  # n-1, 无量纲

    def _compute_time(self):
        """计算轨迹的时间信息"""
        if self.times is None:
            raise ValueError("轨迹时间数据未初始化")
        times: List[datetime] = self.times
        timestamps = np.array([t.timestamp() for t in times])
        self.timestamps = timestamps  # n, 秒

        delta_times = timestamps[1:] - timestamps[:-1]
        self.delta_times = delta_times  # n-1, 秒

        cum_times = np.insert(np.cumsum(delta_times), 0, 0.0)
        self.cum_times = cum_times  # n, 秒

        total_time = cum_times[-1] / 3600.0
        self.total_time = total_time  # 小时

    def _compute_speed(self, window_size):
        """
        滑动窗口平均速度计算（平滑速度波动）
        window_size: int, 滑动窗口大小（计算前N个点的平均速度）
        边缘处理：用两端点的距离和时间信息填充
        计算平均速度, 标准差, 归一化速度
        """
        if self.speeds_km_h is not None:
            return
        if window_size < 1:
            raise ValueError("窗口大小必须大于等于1")
        if self.cum_dists is None:
            raise ValueError("必须先计算累计距离")
        if self.cum_times is None:
            raise ValueError("必须先计算累计时间")

        # 两端点填充：保证滑动窗口能覆盖原始数组所有位置
        pad_left = (window_size - 1) // 2
        pad_right = window_size - 1 - pad_left
        cum_dist_padded = np.pad(self.cum_dists, (pad_left, pad_right), mode="edge")
        cum_time_padded = np.pad(self.cum_times, (pad_left, pad_right), mode="edge")

        # 生成滑动窗口的索引矩阵，一次性获取所有窗口的切片
        dist_shape = cum_dist_padded.shape[0]
        idx = np.arange(window_size) + np.arange(dist_shape - window_size + 1)[:, np.newaxis]

        # 按窗口切片取值，计算每个窗口的 窗口终点-窗口起点 → 窗口内的距离差、时间差
        window_dists = cum_dist_padded[idx]
        window_times = cum_time_padded[idx]
        delta_dist = window_dists[:, -1] - window_dists[:, 0]
        delta_time = window_times[:, -1] - window_times[:, 0]

        # 时间差为0/负数 → 速度置0；距离差为负也置0
        speeds_m_s = np.divide(
            delta_dist,
            delta_time,
            out=np.zeros_like(delta_dist, dtype=np.float64),
            where=delta_time > DIV_EPS,
        )
        # 过滤负数速度，置0
        speeds_m_s = np.clip(speeds_m_s, a_min=0, a_max=None)
        # 单位转换：m/s → km/h
        speeds_km_h = speeds_m_s * 3.6
        self.speeds_km_h = speeds_km_h  # n, km/h

        # 计算速度均值和标准差并归一化
        if self.total_time is None:
            raise ValueError("必须先计算总时间")
        speed_mean = self.total_distance / self.total_time if self.total_time > 0 else 0.0
        self.speed_mean = speed_mean  # km/h

        speed_std = np.std(speeds_km_h)
        self.speed_std = speed_std  # km/h

        norm_speeds = (speeds_km_h - speed_mean) / (speed_std or 1e-6)
        self.norm_speeds = norm_speeds  # n, 无量纲

    def _compute_speed_correction(self, high_speed_sensitivity, low_speed_sensitivity):
        """计算速度修正系数"""
        if self.speed_correction is not None:
            return
        if self.norm_speeds is None:
            raise ValueError("必须先计算归一化速度")
        speed_correction = np.ones(len(self.norm_speeds), dtype=np.float64)
        high_speed_mask = self.norm_speeds > 0
        low_speed_mask = ~high_speed_mask
        speed_correction[high_speed_mask] = 1 - (high_speed_sensitivity * self.norm_speeds[high_speed_mask])
        speed_correction[low_speed_mask] = 1 + (low_speed_sensitivity * -self.norm_speeds[low_speed_mask])
        speed_correction = np.clip(speed_correction, a_min=0, a_max=None)
        self.speed_correction = speed_correction  # n, 无量纲

    def _slope_tired_difficulty(
        self,
        slope: np.ndarray,
        base_difficulty,
        uphill_max_slope,
        uphill_max_diff,
        downhill_max_slope,
        downhill_max_diff,
    ):
        """
        用余弦函数描述体能难度
        """
        uphill_a = uphill_max_diff + base_difficulty
        downhill_a = downhill_max_diff + base_difficulty

        conditions = [
            slope > uphill_max_slope,
            (slope <= uphill_max_slope) & (slope >= 0),
            (slope < 0) & (slope >= -downhill_max_slope),
            slope < -downhill_max_slope,
        ]
        functions = [
            lambda s: uphill_max_diff,
            lambda s: base_difficulty + uphill_a * 0.5 * (1 - np.cos(np.pi * s / uphill_max_slope)),
            lambda s: base_difficulty + downhill_a * 0.5 * (1 - np.cos(np.pi * s / downhill_max_slope)),
            lambda s: downhill_max_diff,
        ]
        result = np.piecewise(slope, conditions, functions)
        return result

    def _slope_elev_difficulty(
        self,
        slope: np.ndarray,
        base_difficulty,
        uphill_sensitivity,
        downhill_sensitivity,
    ):
        """
        用二次函数描述爬升难度
        """
        technical_diff = np.where(
            slope >= 0,
            base_difficulty + uphill_sensitivity * slope**2,
            base_difficulty + downhill_sensitivity * (-slope) ** 2,
        )
        return technical_diff

    def _compute_route_score(
        self,
        short_window_dist,
        short_window_weight,
        long_window_dist,
        long_window_weight,
    ):
        """ """
        if self.slopes is None:
            raise ValueError("必须先计算坡度信息")
        if self.cum_dists is None:
            raise ValueError("必须先计算累计距离信息")

        # 瞬时难度
        inst_tired_difficulty = self._slope_tired_difficulty(
            self.slopes,
            base_difficulty=Rater.config["base_tired_difficulty"],
            uphill_max_diff=Rater.config["uphill_max_diff"],
            downhill_max_diff=Rater.config["downhill_max_diff"],
            uphill_max_slope=Rater.config["uphill_max_slope"],
            downhill_max_slope=Rater.config["downhill_max_slope"],
        )  # n-1

        # ---------------------- 体能难度积分 ----------------------
        weighted_difficulty = inst_tired_difficulty * self.delta_dists

        # 前缀和计算 + 补0对齐
        ws_sum = np.concatenate([[0.0], np.cumsum(weighted_difficulty)])  # n, 加权难度前缀和

        # 短窗口体能难度积分计算
        # 计算所有窗口左边界
        window_left_dists = self.cum_dists[1:] - short_window_dist
        js = np.searchsorted(self.cum_dists, window_left_dists, side="left")
        # 计算窗口内的难度和、距离和
        difficulty_sum = ws_sum[:-1] - ws_sum[np.maximum(js - 1, 0)]
        dist_sum = self.cum_dists[:-1] - self.cum_dists[np.maximum(js - 1, 0)]
        # 计算疲劳度
        fatigue_difficulty = np.divide(
            difficulty_sum,
            dist_sum,
            out=np.zeros_like(difficulty_sum, dtype=np.float64),
            where=dist_sum > DIV_EPS,
        )
        fatigue_difficulty = np.power(fatigue_difficulty, short_window_weight)

        # 长窗口体能难度积分计算
        window_left_dists_long = self.cum_dists[1:] - long_window_dist
        js_long = np.searchsorted(self.cum_dists, window_left_dists_long, side="left")
        difficulty_sum_long = ws_sum[:-1] - ws_sum[np.maximum(js_long - 1, 0)]
        dist_sum_long = self.cum_dists[:-1] - self.cum_dists[np.maximum(js_long - 1, 0)]
        fatigue_difficulty_long = np.divide(
            difficulty_sum_long,
            dist_sum_long,
            out=np.zeros_like(difficulty_sum_long, dtype=np.float64),
            where=dist_sum_long > DIV_EPS,
        )
        fatigue_difficulty_long = np.power(fatigue_difficulty_long, long_window_weight)

        # 计算积分项
        score_items = fatigue_difficulty * fatigue_difficulty_long * self.delta_dists
        tired_score = np.sum(score_items)

        # ------------------- 爬升难度积分 -------------------
        inst_elev_difficulty = self._slope_elev_difficulty(
            self.slopes,
            base_difficulty=Rater.config["base_elev_difficulty"],
            uphill_sensitivity=Rater.config["uphill_elev_sensitivity"],
            downhill_sensitivity=Rater.config["downhill_elev_sensitivity"],
        )  # n-1
        # 爬升难度积分积分：瞬时爬升难度 * 当前段距离
        elev_score = np.sum(inst_elev_difficulty * self.delta_dists)

        self.tired_score = tired_score
        self.elev_score = elev_score

    def compute_metrics(self):
        """计算轨迹的各项指标"""
        if self.has_metrics:
            return
        self._compute_distance()
        self._compute_elevation()
        self._compute_slope()
        if self.times is not None:
            self._compute_time()
            self._compute_speed(window_size=Rater.config["window_size_speed"])
            # self._compute_speed_correction(
            #     high_speed_sensitivity=Rater.config["high_speed_sensitivity"],
            #     low_speed_sensitivity=Rater.config["low_speed_sensitivity"],
            # )
        self._compute_route_score(
            short_window_dist=Rater.config["window_size_tired_difficulty_short"],
            short_window_weight=Rater.config["short_window_weight"],
            long_window_dist=Rater.config["window_size_tired_difficulty_long"],
            long_window_weight=Rater.config["long_window_weight"],
        )
        self.tired_level = self.score_remap(
            self.tired_score,
            Rater.config["tired_score_remap_a"],
            Rater.config["tired_score_remap_b"],
            Rater.config["tired_score_remap_c"],
        )
        self.elev_level = self.score_remap(
            self.elev_score,
            Rater.config["elev_score_remap_a"],
            Rater.config["elev_score_remap_b"],
            Rater.config["elev_score_remap_c"],
        )
        self.has_metrics = True

    def get_metrics(self):
        """获取计算后的各项指标"""
        if not self.has_metrics:
            self.compute_metrics()
        return {
            "total_distance_km": self.total_distance,
            "total_elevation_m": self.total_elevation,
            "total_time_h": self.total_time,
            "speed_mean_km_h": self.speed_mean,
            "speed_std_km_h": self.speed_std,
            "tired_score": self.tired_score,
            "tired_level": self.tired_level,
            "elev_score": self.elev_score,
            "elev_level": self.elev_level,
        }


if __name__ == "__main__":
    from pathlib import Path
    from tqdm import tqdm
    import json

    file_list: list[str] = []
    base_path = Path("./Routes").resolve()
    if base_path.exists():
        for p in base_path.rglob("*.kml"):
            file_list.append(p.resolve().as_posix())
    else:
        file_list = []

    with open("clusters.json", "r", encoding="utf-8") as f:
        clusters = json.load(f)

    cluster_of_file = {}
    for cluster_id, files in clusters.items():
        for f in files:
            cluster_of_file[f] = cluster_id

    dtype_spec = {
        "file": str,
        "distance_km": float,
        "elevation_m": float,
        "tired_score": float,
        "tired_level": float,
        "elev_score": float,
        "elev_level": float,
        "cluster_id": str,
    }
    data = pd.DataFrame(columns=dtype_spec.keys()).astype(dtype_spec)

    for file_path in tqdm(file_list):
        rater = Rater.from_kml(file_path)
        result = rater.get_metrics()
        file_key = Path(file_path).relative_to(base_path).as_posix()
        new_row = pd.DataFrame(
            {
                "file": [file_key],
                "distance_km": [result["total_distance_km"]],
                "elevation_m": [result["total_elevation_m"]],
                "tired_score": [result["tired_score"]],
                "tired_level": [result["tired_level"]],
                "elev_score": [result["elev_score"]],
                "elev_level": [result["elev_level"]],
                "cluster_id": [cluster_of_file.get(file_key, "")],
            }
        ).astype(dtype_spec)
        data = pd.concat([data, new_row], ignore_index=True)

    data.to_csv("result.csv", index=False)
