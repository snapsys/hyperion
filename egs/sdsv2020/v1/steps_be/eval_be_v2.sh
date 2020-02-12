#!/bin/bash
# Copyright 2020 Johns Hopkins University (Jesus Villalba)  
# Apache 2.0.
#

cmd=run.pl
num_parts=8

if [ -f path.sh ]; then . ./path.sh; fi
. parse_options.sh || exit 1;
set -e

if [ $# -ne 5 ]; then
  echo "Usage: $0 <ndx> <enroll-file> <vector-file> <preproc-file> <output-scores>"
  exit 1;
fi

ndx_file=$1
enroll_file=$2
vector_file=$3
preproc_file=$4
output_file=$5

output_dir=$(dirname $output_file)

mkdir -p $output_dir/log
name=$(basename $output_file)

echo "$0 score $ndx_file"


for((i=1;i<=$num_parts;i++));
do
    for((j=1;j<=$num_parts;j++));
    do
	$cmd $output_dir/log/${name}_${i}_${j}.log \
	    python steps_be/eval-be-v2.py \
	    --iv-file scp:$vector_file \
	    --ndx-file $ndx_file \
	    --enroll-file $enroll_file \
	    --preproc-file $preproc_file \
	    --score-file $output_file \
	    --model-part-idx $i --num-model-parts $num_parts \
	    --seg-part-idx $j --num-seg-parts $num_parts &
    done
done
wait


for((i=1;i<=$num_parts;i++));
do
    for((j=1;j<=$num_parts;j++));
    do
	cat $output_file-$(printf "%03d" $i)-$(printf "%03d" $j)
    done
done | sort -u > $output_file



