from rater import Rater
import os
import numpy as np
import csv
from collections import defaultdict
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform
from haversine import haversine_vector, Unit
import json

def distance_2_sim(distance, threshold=1.0):
    """
    将距离转换为相似度，距离越大相似度越小
    threshold: 90%相似度对应的距离值(km)
    """
    sim = np.exp(-0.1 *distance / threshold)
    return sim

if __name__ == "__main__":

    with open("img_map.json", "r", encoding="utf-8") as f:
        map_data = json.load(f)

    with open("info_map.json", "r", encoding="utf-8") as f:
        info_map = json.load(f)

    keys = list(map_data.keys())
    keys.sort()
    n = len(keys)

    embedding_list = []
    len_list = []
    centriod_lat_lon_list = []

    for i in range(n):
        key = keys[i]
        info = info_map.get(key, {})
        length = info.get("total_distance", 1.0)
        centriod_lat = info.get("centroid_lat", 1.0)
        centriod_lon = info.get("centroid_lon", 1.0)
        len_list.append(length)
        centriod_lat_lon_list.append( (centriod_lat, centriod_lon) )
        embedding_list.append( map_data[key] )

    len_array = np.array(len_list)
    lat_lon_array = np.array(centriod_lat_lon_list)
    embedding_array = np.array(embedding_list)

    # 计算形状相似度矩阵
    shape_matrix = embedding_array @ embedding_array.T
    shape_matrix = np.clip(shape_matrix, 0.0, 1.0)
    shape_matrix = np.power(shape_matrix, 5) # 相似度缩放
    shape_matrix = np.clip(shape_matrix, 0.0, 1.0)

    # 计算长度相似度矩阵
    len_mat = np.tile(len_array, (n, 1))  # 生成 n×n 的矩阵，每行都是len_array
    len_mat_T = len_mat.T                 # 转置矩阵，每列都是len_array
    # 1. 生成所有两两组合的 较长值矩阵
    max_len_mat = np.maximum(len_mat, len_mat_T)
    # 2. 生成所有两两组合的 绝对差值矩阵
    abs_diff_mat = np.abs(len_mat - len_mat_T)
    # 3. 计算最终的长度相似度矩阵
    len_sim_matrix = 1.0 - (abs_diff_mat / max_len_mat)
    len_sim_matrix = np.clip(len_sim_matrix, 0.0, 1.0)
    len_sim_matrix = np.power(len_sim_matrix, 0.6) # 相似度缩放
    len_sim_matrix = np.clip(len_sim_matrix, 0.0, 1.0)

    # 计算位置相似度矩阵
    # 1. 计算所有轨迹质心两两之间的距离矩阵
    dist_matrix = haversine_vector(lat_lon_array, lat_lon_array, unit=Unit.KILOMETERS, comb=True)
    # 2. 将距离矩阵转换为相似度矩阵
    pos_sim_matrix = distance_2_sim(dist_matrix)
    pos_sim_matrix = np.clip(pos_sim_matrix, 0.0, 1.0)

    # 综合三种相似度
    sim_matrix = shape_matrix * len_sim_matrix * pos_sim_matrix
    np.fill_diagonal(sim_matrix, 1.0)
    sim_matrix = np.clip(sim_matrix, 0.0, 1.0)

    # 保存为CSV文件
    # csv_file = "overall_similarity_matrix.csv"
    # with open(csv_file, "w", newline="", encoding="utf-8") as f:
    #     writer = csv.writer(f)
    #     header = [""] + keys
    #     writer.writerow(header)
    #     for i in range(n):
    #         row = [keys[i]] + sim_matrix[i].tolist()
    #         writer.writerow(row)

    # with open("shape_similarity_matrix.csv", "w", newline="", encoding="utf-8") as f:
    #     writer = csv.writer(f)
    #     header = [""] + keys
    #     writer.writerow(header)
    #     for i in range(n):
    #         row = [keys[i]] + shape_matrix[i].tolist()
    #         writer.writerow(row)

    # with open("length_similarity_matrix.csv", "w", newline="", encoding="utf-8") as f:
    #     writer = csv.writer(f)
    #     header = [""] + keys
    #     writer.writerow(header)
    #     for i in range(n):
    #         row = [keys[i]] + len_sim_matrix[i].tolist()
    #         writer.writerow(row)

    # with open("position_similarity_matrix.csv", "w", newline="", encoding="utf-8") as f:
    #     writer = csv.writer(f)
    #     header = [""] + keys
    #     writer.writerow(header)
    #     for i in range(n):
    #         row = [keys[i]] + pos_sim_matrix[i].tolist()
    #         writer.writerow(row)

    # 层次聚类
    threshold = 0.80 # 聚类阈值
    # 转换为距离矩阵
    dist_matrix = 1.0 - sim_matrix
    threshold = 1.0 - threshold
    condensed_dist = squareform(dist_matrix)
    Z = linkage(condensed_dist, method='average')
    # 根据距离阈值进行聚类
    clusters = fcluster(Z, threshold, criterion='distance')
    cluster_dict = defaultdict(list)
    for i, cluster_id in enumerate(clusters):
        cluster_dict[int(cluster_id)].append(keys[i])
    cluster_dict = dict(sorted(cluster_dict.items(), key=lambda x: x[0]))
    # 保存聚类结果
    with open("clusters.json", "w", encoding="utf-8") as f:
        json.dump(cluster_dict, f, ensure_ascii=False, indent=4)
