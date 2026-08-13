

# 98毅行路线难度评分系统

## 环境搭建
```
conda env create -f environment.yml
```
```
conda activate router98
```

## 调试运行
```
python run.py
```

## 部署运行
``` 
gunicorn -w 2 -b 0.0.0.0:5000 run:app
```
