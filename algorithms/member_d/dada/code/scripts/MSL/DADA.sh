python -u run.py --metric affiliation --t $(seq 0.230 0.001 0.240) --norm 0 --use_gpu True --gpu 0 --root_path ./dataset/evaluation_dataset --data MSL --model ./DADA --des 'zero_shot' --batch_size 128
python -u run.py --metric auc --norm 0 --use_gpu True --gpu 0 --root_path ./dataset/evaluation_dataset --data MSL --model ./DADA --des 'zero_shot' --batch_size 128
