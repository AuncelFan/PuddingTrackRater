import pandas as pd

if __name__ == "__main__":
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
    df = pd.read_csv("result.csv", dtype=str)
    df = df.astype(dtype_spec)

    missing_cluster_mask = df["cluster_id"].str.strip() == "nan"
    missing_count = missing_cluster_mask.sum()
    df.loc[missing_cluster_mask, "cluster_id"] = [
        f"u{i+1}" for i in range(missing_count)
    ]

    agg_dict = {
        "file": lambda x: ",".join(x.astype(str)),
        "distance_km": "mean",
        "elevation_m": "mean",
        "tired_score": "mean",
        "tired_level": "mean",
        "elev_score": "mean",
        "elev_level": "mean",
    }

    grouped = df.groupby("cluster_id", as_index=False).agg(agg_dict)

    grouped.to_csv("result_grouped.csv", index=False)