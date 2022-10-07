cd ..
cd ..
python run_atari_pretrain.py \
    --group_name baseline \
    --exp_name trajformer_demon_idm \
    --config_name mixed_trajformer_impala \
    --mode test \
    --debug False \
    --num_seeds 1 \
    --num_devices 4 \
    --num_exp_per_device 1 \
    --overrides trainer.dataset_type='demonstration' \
    --overrides trainer.idm_lmbda=1.0 \
    --overrides trainer.num_epochs=5  