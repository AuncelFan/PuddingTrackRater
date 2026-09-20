import numpy as np
import json
import pyproj
from rdp import rdp
from openai import OpenAI
import cv2
import dashscope
import base64
from http import HTTPStatus

from rater import Rater

API_KEY = ""

transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)


def img_embedding(img: np.ndarray) -> np.ndarray:
    """
    计算图片的嵌入向量
    :param img: 图片的numpy数组
    :return: 嵌入向量
    """
    # 将numpy数组转换为Base64字符串
    _, buffer = cv2.imencode(".png", img)
    base64_image = base64.b64encode(buffer).decode("utf-8")
    image_data = f"data:image/png;base64,{base64_image}"
    input = [{"image": image_data}]

    resp = dashscope.MultiModalEmbedding.call(
        model="tongyi-embedding-vision-plus",
        input=input,
        api_key=API_KEY,
    )
    if resp.status_code == HTTPStatus.OK:
        result = {
            "status_code": resp.status_code,
            "request_id": getattr(resp, "request_id", ""),
            "code": getattr(resp, "code", ""),
            "message": getattr(resp, "message", ""),
            "output": resp.output,
            "usage": resp.usage,
        }
        embedding = resp.output["embeddings"][0]["embedding"]
        return np.array(embedding)
    else:
        raise Exception(f"请求失败，状态码: {resp.status_code}, 响应内容: {resp.text}")


def prepare_spares_xy(lat_lons: np.ndarray, eps=10, max_points=1200) -> np.ndarray:
    """
    准备稀疏坐标点，转换为平面坐标系并降采样
    :param lat_lons: numpy数组 (N,2) 经纬度坐标点
    :param eps: RDP算法简化阈值(单位：米)
    :param max_points: 最大允许点数
    :return: numpy数组 (M,2) M ≤ N 降采样后的平面坐标点
    """
    x, y = transformer.transform(lat_lons[:, 1], lat_lons[:, 0])
    xys = np.column_stack([x, y])
    xys = xys[np.isfinite(xys).all(axis=1)]
    xys = rdp(xys, epsilon=eps)
    xys = downsample_xys(xys, max_points)
    return xys


def downsample_xys(xys, max_points):
    """
    对二维坐标数组进行均匀降采样，确保点数 ≤ max_points
    :param xys: numpy数组 (N,2) 坐标点
    :param max_points: 最大允许点数
    :return: numpy数组 (M,2) M ≤ max_points
    """
    n = len(xys)
    if n <= max_points:
        return xys
    indices = np.linspace(0, n - 1, max_points, dtype=int)
    return xys[indices]


def xys_2_img(
    xys: np.ndarray,
    img_size: int = 256,
    line_width: int = 1,
    start_color: tuple = (0, 255, 255),  # 青色 (B,G,R) OpenCV格式
    end_color: tuple = (0, 165, 255),  # 橙色 (B,G,R)
    gradient_start: tuple = (255, 0, 0),  # 渐变起点（深蓝 BGR）
    gradient_end: tuple = (0, 0, 255),  # 渐变终点（深红 BGR）
) -> np.ndarray:
    """
    精细化渲染：抗锯齿+超采样+插值，生成高清轨迹图像
    :param upsample_ratio: 超采样比例（2=先渲染512x512，再缩放到256x256）
    :param interpolate_points: 插值后轨迹总点数（如100，稀疏轨迹必设）
    """
    # -------------------------- 1. 输入校验与预处理 --------------------------
    if xys.ndim != 2 or xys.shape[1] != 2:
        raise ValueError(f"xys必须是shape=[N,2]的数组，当前shape={xys.shape}")
    if len(xys) == 0:
        raise ValueError("xys不能为空数组")
    if len(xys) == 1:
        # 单点轨迹：超采样+抗锯齿绘制
        img = np.ones((img_size, img_size, 3), dtype=np.uint8) * 255
        center = (img_size // 2, img_size // 2)
        # 抗锯齿绘制圆点
        cv2.circle(img, center, 5, start_color, -1, cv2.LINE_AA)
        # 降采样到目标尺寸（抗锯齿）
        return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # -------------------------- 3. 坐标归一化（高精度+Y轴反转） --------------------------
    x, y = xys[:, 0], xys[:, 1]
    x_min, x_max = x.min(), x.max()
    y_min, y_max = y.min(), y.max()

    # 处理范围为0的情况（避免除0）
    x_range = x_max - x_min if x_max != x_min else 1e-6
    y_range = y_max - y_min if y_max != y_min else 1e-6

    # 归一化到[0.05, 0.95]（留边，避免贴边模糊）
    x_norm = 0.05 + 0.9 * (x - x_min) / x_range
    y_norm = 0.05 + 0.9 * (y - y_min) / y_range
    # 反转Y轴（解决上下颠倒）
    y_norm = 1.0 - y_norm

    # 超采样尺寸的像素坐标（高精度）
    high_size = img_size
    x_pix = (x_norm * high_size).astype(np.float32)  # 保留浮点精度，避免像素偏移
    y_pix = (y_norm * high_size).astype(np.float32)

    # 限制坐标在图像范围内
    x_pix = np.clip(x_pix, 0, high_size - 1)
    y_pix = np.clip(y_pix, 0, high_size - 1)

    # -------------------------- 4. 生成渐变颜色（伽马校正，过渡更自然） --------------------------
    num_segments = len(xys) - 1
    # 伽马校正（γ=0.8，让低亮度部分过渡更平滑）
    gamma = 0.8
    grad_b = np.linspace(gradient_start[0], gradient_end[0], num_segments)
    grad_g = np.linspace(gradient_start[1], gradient_end[1], num_segments)
    grad_r = np.linspace(gradient_start[2], gradient_end[2], num_segments)
    # 伽马校正后转回uint8
    grad_b = (255 * ((grad_b / 255) ** gamma)).astype(np.uint8)
    grad_g = (255 * ((grad_g / 255) ** gamma)).astype(np.uint8)
    grad_r = (255 * ((grad_r / 255) ** gamma)).astype(np.uint8)
    gradient_colors = np.column_stack([grad_b, grad_g, grad_r])

    # -------------------------- 5. OpenCV超采样绘制（核心抗锯齿） --------------------------
    # 创建高分辨率白色背景
    img = np.ones((high_size, high_size, 3), dtype=np.uint8) * 255

    # 逐段绘制抗锯齿轨迹
    for i in range(num_segments):
        p1 = (int(round(x_pix[i])), int(round(y_pix[i])))
        p2 = (int(round(x_pix[i + 1])), int(round(y_pix[i + 1])))
        color = gradient_colors[i].tolist()
        # OpenCV抗锯齿线（LINE_AA是关键，消除锯齿）
        cv2.line(img, p1, p2, color, thickness=line_width, lineType=cv2.LINE_AA)  # 核心：抗锯齿渲染

    # -------------------------- 6. 绘制高精度起点/终点（抗锯齿） --------------------------
    # 起点（青色）
    start_r = line_width + 1
    start_center = (int(round(x_pix[0])), int(round(y_pix[0])))
    cv2.circle(img, start_center, start_r, start_color, -1, cv2.LINE_AA)
    # 终点（橙色）
    end_r = line_width + 1
    end_center = (int(round(x_pix[-1])), int(round(y_pix[-1])))
    cv2.circle(img, end_center, end_r, end_color, -1, cv2.LINE_AA)

    # 转换为RGB格式返回
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return img_rgb


def xys_2_delta_str(xys: np.ndarray) -> str:
    """
    将xy坐标numpy数组，转换为【起点+逐点偏移】的字符串数组
    :param xys: np.ndarray，shape=[轨迹点数量, 2]，每行是(x, y)
    :return: 字符串数组，第一个元素为"start=x,y"，后续为"delta_x,delta_y"
    """
    if not isinstance(xys, np.ndarray):
        raise ValueError("输入必须是numpy数组")
    if xys.ndim != 2 or xys.shape[1] != 2:
        raise ValueError(f"输入数组shape必须是[n,2]，当前为{xys.shape}")
    if xys.shape[0] < 1:
        return []

    str_list = []

    x0, y0 = xys[0]
    start_str = f"start={int(x0)},{int(y0)}"
    str_list.append(start_str)

    deltas = xys[1:] - xys[:-1]
    for dx, dy in deltas:
        delta_str = f"{int(dx):+}{int(dy):+}"
        str_list.append(delta_str)

    return "".join(str_list)


if __name__ == "__main__":
    from pathlib import Path

    base_dir = Path("Routes")
    files_list = list(base_dir.rglob("*.kml"))

    for file_path in files_list:
        rel_path = file_path.relative_to(base_dir).as_posix()
        print(rel_path)

    # # 处理img_map.json
    # img_map_path = Path("img_map.json")
    # if not img_map_path.exists():
    #     img_map_path.write_text(json.dumps({}, ensure_ascii=False, indent=4), encoding="utf-8")

    # with img_map_path.open("r", encoding="utf-8") as f:
    #     map_data = json.load(f)

    # count = 0
    # for file_path in files_list:
    #     rel_path = file_path.relative_to(base_dir).as_posix()
    #     if rel_path in map_data:
    #         print(f"已存在嵌入向量，跳过: {rel_path}")
    #         continue
    #     rater = Rater.from_kml(str(file_path))
    #     lat_lons = rater.get_lat_lon()
    #     xys = prepare_spares_xy(lat_lons, eps=10, max_points=1200)
    #     img = xys_2_img(xys)
    #     embedding = img_embedding(img)
    #     map_data[rel_path] = embedding.tolist()
    #     print(f"已处理并保存嵌入向量: {rel_path}")
    #     count += 1
    #     if count % 10 == 0:
    #         with img_map_path.open("w", encoding="utf-8") as f:
    #             json.dump(map_data, f, ensure_ascii=False, indent=4)

    # with img_map_path.open("w", encoding="utf-8") as f:
    #     json.dump(map_data, f, ensure_ascii=False, indent=4)

    # # 处理info_map.json
    # info_map_path = Path("info_map.json")
    # if not info_map_path.exists():
    #     info_map_path.write_text(json.dumps({}, ensure_ascii=False, indent=4), encoding="utf-8")

    # with info_map_path.open("r", encoding="utf-8") as f:
    #     info_map = json.load(f)

    # for file_path in files_list:
    #     rel_path = file_path.relative_to(base_dir).as_posix()
    #     if rel_path in info_map:
    #         print(f"已存在信息，跳过: {rel_path}")
    #         continue
    #     rater = Rater.from_kml(str(file_path))
    #     lat_lons = rater.get_lat_lon()
    #     centroid_lat = float(np.mean(lat_lons[:, 0]))
    #     centroid_lon = float(np.mean(lat_lons[:, 1]))
    #     total_distance = float(rater.get_total_distance())
    #     info_map[rel_path] = {
    #         "centroid_lat": centroid_lat,
    #         "centroid_lon": centroid_lon,
    #         "total_distance": total_distance
    #     }
    #     print(f"已处理并保存信息: {rel_path}")

    # with info_map_path.open("w", encoding="utf-8") as f:
    #     json.dump(info_map, f, ensure_ascii=False, indent=4)
