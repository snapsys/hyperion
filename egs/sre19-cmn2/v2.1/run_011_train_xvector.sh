#!/bin/bash
# Copyright
#                2019   Johns Hopkins University (Author: Jesus Villalba)
# Apache 2.0.
#
. ./cmd.sh
. ./path.sh
set -e

stage=1
ngpu=4
config_file=default_config.sh
resume=false
interactive=false
num_workers=4

. parse_options.sh || exit 1;
. $config_file
. datapath.sh

batch_size=$(($batch_size_1gpu*$ngpu))
grad_acc_steps=$(echo $batch_size $eff_batch_size | awk '{ print int($2/$1+0.5)}')
log_interval=$(echo 100*$grad_acc_steps | bc)
list_dir=data/${nnet_data}_proc_audio_no_sil

args=""
if [ "$resume" == "true" ];then
    args="--resume"
fi

if [ "$interactive" == "true" ];then
    export cuda_cmd=run.pl
fi

# Network Training
if [ $stage -le 1 ]; then

    if [[ ${nnet_type} =~ resnet ]] || [[ ${nnet_type} =~ resnext ]]; then
	train_exec=torch-train-resnet-xvec-from-wav.py
    elif [[ ${nnet_type} =~ efficientnet ]]; then
	train_exec=torch-train-efficientnet-xvec-from-wav.py
    else
	echo "$nnet_type not supported"
	exit 1
    fi

    mkdir -p $nnet_dir/log
    $cuda_cmd --gpu $ngpu $nnet_dir/log/train.log \
	hyp_utils/conda_env.sh --conda-env $HYP_ENV --num-gpus $ngpu \
	$train_exec  --feats $feat_config $aug_opt \
	--audio-path $list_dir/wav.scp \
	--time-durs-file $list_dir/utt2dur \
	--train-list $list_dir/lists_xvec/train.scp \
	--val-list $list_dir/lists_xvec/val.scp \
	--class-file $list_dir/lists_xvec/class2int \
	--min-chunk-length $min_chunk --max-chunk-length $max_chunk \
	--iters-per-epoch $ipe \
	--batch-size $batch_size \
	--num-workers $num_workers \
	--grad-acc-steps $grad_acc_steps \
	--embed-dim $embed_dim $nnet_opt $opt_opt $lrs_opt \
	--epochs $nnet_num_epochs \
	--s $s --margin $margin --margin-warmup-epochs $margin_warmup \
	--dropout-rate $dropout \
	--num-gpus $ngpu \
	--log-interval $log_interval \
	--exp-path $nnet_dir $args

fi


exit
