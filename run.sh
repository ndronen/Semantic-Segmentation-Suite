#!/bin/bash -e

input_dir=$1
output_dir=$2
params=$3

dataset_name=$(echo $params | json dataset-name)
if [ ! -d ${dataset_name}/train ]
then
    ./prep-data.sh ${dataset_name} ${input_dir}
fi

model_name=$(echo $params | json model-name)

function update_extra_args {
    params=$1
    extra_args=$2
    keyword=$3
    echo $params | grep -q $keyword
    if [ $? -eq 0 ]
    then
        value=$(echo $params | json $keyword)
        command_line_arg=$(echo $keyword | tr '-' '_')
        extra_args="$extra_args --${command_line_arg} $value"
    fi
    echo $extra_args
}

extra_args=""
extra_args=$(update_extra_args "$params" "$extra_args" class-balancing)
extra_args=$(update_extra_args "$params" "$extra_args" loss-func)
extra_args=$(update_extra_args "$params" "$extra_args" learning-rate)

python main.py --mode train --dataset ${dataset_name} --h_flip True --model ${model_name} $extra_args --crop_height 360 --crop_width 480 | tee ${model_name}-Train.txt
python main.py --mode val --dataset ${dataset_name} --model ${model_name} 2>&1 | tee ${model_name}-Val.txt
python main.py --mode test --dataset ${dataset_name} --model ${model_name} 2>&1 | tee ${model_name}-Test.txt
