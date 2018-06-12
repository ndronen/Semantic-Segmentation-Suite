from __future__ import print_function
import os,time,cv2, sys, math
import tensorflow as tf
import tensorflow.contrib.slim as slim
import numpy as np
import pandas as pd
import time, datetime
import argparse
import random
import os, sys

from modelutil.metrics import confusion_matrix, prfs, \
    convert_prfs_to_data_frame

import helpers 
import utils 

sys.path.append('models')
from FC_DenseNet_Tiramisu import build_fc_densenet
from Encoder_Decoder import build_encoder_decoder
from RefineNet import build_refinenet
from FRRN import build_frrn
from MobileUNet import build_mobile_unet
from PSPNet import build_pspnet
from GCN import build_gcn
from DeepLabV3 import build_deeplabv3
from DeepLabV3_plus import build_deeplabv3_plus
from AdapNet import build_adaptnet


def str2bool(v):
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')


parser = argparse.ArgumentParser()
parser.add_argument('--num_epochs', type=int, default=300, help='Number of epochs to train for')
parser.add_argument('--mode', type=str, default='train', help='Select "train", "test", or "predict" mode. \
    Note that for prediction mode you have to specify an image to run the model on.')
parser.add_argument('--checkpoint_step', type=int, default=10, help='How often to save checkpoints (epochs)')
parser.add_argument('--validation_step', type=int, default=1, help='How often to perform validation (epochs)')
parser.add_argument('--class_balancing', type=str2bool, default=False, help='Whether to use median frequency class weights to balance the classes in the loss')
parser.add_argument(
    '--loss_func', type=str, default='cross_entropy',
    choices=['cross_entropy', 'lovasz'],
    help='Which loss function to use (cross_entropy or lovasz)')
parser.add_argument('--image', type=str, default=None, help='The image you want to predict on. Only valid in "predict" mode.')
parser.add_argument('--continue_training', type=str2bool, default=False, help='Whether to continue training from a checkpoint')
parser.add_argument('--dataset', type=str, default='CamVid', help='Dataset you are using.')
parser.add_argument('--crop_height', type=int, default=512, help='Height of cropped input image to network')
parser.add_argument('--crop_width', type=int, default=512, help='Width of cropped input image to network')
parser.add_argument('--crop', type=str2bool, default=False, help='Whether to crop')
parser.add_argument('--batch_size', type=int, default=1, help='Number of images in each batch')
parser.add_argument('--num_val_images', type=int, default=-1, help='The number of images to used for validations; default is -1 (all images in validation set)')
parser.add_argument('--h_flip', type=str2bool, default=False, help='Whether to randomly flip the image horizontally for data augmentation')
parser.add_argument('--v_flip', type=str2bool, default=False, help='Whether to randomly flip the image vertically for data augmentation')
parser.add_argument('--brightness', type=float, default=None, help='Whether to randomly change the image brightness for data augmentation. Specifies the max bightness change.')
parser.add_argument('--rotation', type=float, default=None, help='Whether to randomly rotate the image for data augmentation. Specifies the max rotation angle.')
parser.add_argument('--model', type=str, default='FC-DenseNet56', help='The model you are using. Currently supports:\
    FC-DenseNet56, FC-DenseNet67, FC-DenseNet103, Encoder-Decoder, Encoder-Decoder-Skip, RefineNet-Res50, RefineNet-Res101, RefineNet-Res152, \
    FRRN-A, FRRN-B, MobileUNet, MobileUNet-Skip, PSPNet-Res50, PSPNet-Res101, PSPNet-Res152, GCN-Res50, GCN-Res101, GCN-Res152, DeepLabV3-Res50 \
    DeepLabV3-Res101, DeepLabV3-Res152, DeepLabV3_plus-Res50, DeepLabV3_plus-Res101, DeepLabV3_plus-Res152, AdapNet, custom')
parser.add_argument('--learning_rate', type=float, default=0.0001, help='The learning rate')
parser.add_argument('--score_averaging', type=str, default='macro', help='The score weighting type (see e.g. `sklearn.metrics.accuracy_score`); default is "macro".')

args = parser.parse_args()

# Get the names of the classes so we can record the evaluation results
label_info = helpers.get_label_info(
    os.path.join(args.dataset, 'class_dict.csv'))

config = tf.ConfigProto()
config.gpu_options.allow_growth = True
sess=tf.Session(config=config)

# Get the selected model. 
# Some of them require pre-trained ResNet

if 'Res50' in args.model and not os.path.isfile('models/resnet_v2_50.ckpt'):
    utils.download_checkpoints('Res50')
if 'Res101' in args.model and not os.path.isfile('models/resnet_v2_101.ckpt'):
    utils.download_checkpoints('Res101')
if 'Res152' in args.model and not os.path.isfile('models/resnet_v2_152.ckpt'):
    utils.download_checkpoints('Res152')

# Compute your softmax cross entropy loss
print('Preparing the model ...')
net_input = tf.placeholder(
    tf.float32,shape=[None,None,None,3])
net_output = tf.placeholder(
    tf.float32,shape=[None,None,None,label_info['num_classes']]) 

network = None
init_fn = None
if args.model == 'FC-DenseNet56' or args.model == 'FC-DenseNet67' or args.model == 'FC-DenseNet103':
    network = build_fc_densenet(net_input, preset_model = args.model, num_classes=label_info['num_classes'])
elif args.model == 'RefineNet-Res50' or args.model == 'RefineNet-Res101' or args.model == 'RefineNet-Res152':
    # RefineNet requires pre-trained ResNet weights
    network, init_fn = build_refinenet(net_input, preset_model = args.model, num_classes=label_info['num_classes'])
elif args.model == 'FRRN-A' or args.model == 'FRRN-B':
    network = build_frrn(net_input, preset_model = args.model, num_classes=label_info['num_classes'])
elif args.model == 'Encoder-Decoder' or args.model == 'Encoder-Decoder-Skip':
    network = build_encoder_decoder(net_input, preset_model = args.model, num_classes=label_info['num_classes'])
elif args.model == 'MobileUNet' or args.model == 'MobileUNet-Skip':
    network = build_mobile_unet(net_input, preset_model = args.model, num_classes=label_info['num_classes'])
elif args.model == 'PSPNet-Res50' or args.model == 'PSPNet-Res101' or args.model == 'PSPNet-Res152':
    # Image size is required for PSPNet
    # PSPNet requires pre-trained ResNet weights
    network, init_fn = build_pspnet(net_input, label_size=[args.crop_height, args.crop_width], preset_model = args.model, num_classes=label_info['num_classes'])
elif args.model == 'GCN-Res50' or args.model == 'GCN-Res101' or args.model == 'GCN-Res152':
    # GCN requires pre-trained ResNet weights
    network, init_fn = build_gcn(net_input, preset_model = args.model, num_classes=label_info['num_classes'])
elif args.model == 'DeepLabV3-Res50' or args.model == 'DeepLabV3-Res101' or args.model == 'DeepLabV3-Res152':
    # DeepLabV requires pre-trained ResNet weights
    network, init_fn = build_deeplabv3(net_input, preset_model = args.model, num_classes=label_info['num_classes'])
elif args.model == 'DeepLabV3_plus-Res50' or args.model == 'DeepLabV3_plus-Res101' or args.model == 'DeepLabV3_plus-Res152':
    # DeepLabV3+ requires pre-trained ResNet weights
    network, init_fn = build_deeplabv3_plus(net_input, preset_model = args.model, num_classes=label_info['num_classes'])
elif args.model == 'AdapNet':
    network = build_adaptnet(net_input, num_classes=label_info['num_classes'])
elif args.model == 'custom':
    network = build_custom(net_input, label_info['num_classes'])
else:
    raise ValueError('Error: the model %d is not available. Try checking which models are available using the command python main.py --help')


losses = None
if args.class_balancing:
    print('Computing class weights for', args.dataset, '...')
    class_weights = utils.compute_class_weights(labels_dir=args.dataset +
            '/train_labels', label_values=label_info['label_values'])
    unweighted_loss = None
    if args.loss_func == 'cross_entropy':
        unweighted_loss = tf.nn.softmax_cross_entropy_with_logits(logits=network, labels=net_output)
    elif args.loss_func == 'lovasz':
        unweighted_loss = utils.lovasz_softmax(probas=network, labels=net_output)
    losses = unweighted_loss * class_weights
else:
    if args.loss_func == 'cross_entropy':
        losses = tf.nn.softmax_cross_entropy_with_logits(logits=network, labels=net_output)
    elif args.loss_func == 'lovasz':
        losses = utils.lovasz_softmax(probas=network, labels=net_output)
loss = tf.reduce_mean(losses)


learning_rate = tf.placeholder(tf.float32, shape=[])
opt = tf.train.AdamOptimizer(learning_rate).minimize(loss, var_list=[var for var in tf.trainable_variables()])

saver=tf.train.Saver(max_to_keep=1000, save_relative_paths=True)
sess.run(tf.global_variables_initializer())

utils.count_params()

# If a pre-trained ResNet is required, load the weights.
# This must be done AFTER the variables are initialized with sess.run(tf.global_variables_initializer())
if init_fn is not None:
    init_fn(sess)


# Load a previous checkpoint if desired
model_ckpt_name = utils.make_model_ckpt_name(args)
if args.continue_training or not args.mode == 'train':
    print('Loading model checkpoint {}'.format(model_ckpt_name))
    saver.restore(sess, model_ckpt_name)
    print('Loaded model checkpoint {}'.format(model_ckpt_name))

avg_scores_per_epoch = []

# Load the data
print('Loading the data ...')
train_input_names, train_output_names, \
    val_input_names, val_output_names, \
    test_input_names, test_output_names = utils.prepare_data(args.dataset)

if args.mode == 'train':

    print('\n***** Begin training *****')
    print('Dataset -->', args.dataset)
    print('Model -->', args.model)
    print('Crop Height -->', args.crop_height)
    print('Crop Width -->', args.crop_width)
    print('Num Epochs -->', args.num_epochs)
    print('Batch Size -->', args.batch_size)
    print('Num Classes -->', label_info['num_classes'])

    print('Data Augmentation:')
    print('\tVertical Flip -->', args.v_flip)
    print('\tHorizontal Flip -->', args.h_flip)
    print('\tBrightness Alteration -->', args.brightness)
    print('\tRotation -->', args.rotation)
    print('')

    avg_loss_per_epoch = []

    # Which validation images do we want
    val_indices = []
    num_vals = min(args.num_val_images, len(val_input_names))
    if num_vals == -1:
        num_vals = len(val_input_names)

    # Set random seed to make sure models are validated on the same validation images.
    # So you can compare the results of different models more intuitively.
    random.seed(16)
    val_indices = random.sample(range(0, len(val_input_names)), num_vals)

    lr = args.learning_rate

    best_f1 = 0.
    best_f1_epoch = 0
    best_f1_checkpoint = ''

    # Do the training here
    for epoch in range(0, args.num_epochs):
        if epoch - best_f1_epoch > 5:
            print('Early stopping best epoch {:d}, current {:d}'.format(
                best_f1_epoch, epoch))
            break

        if epoch - best_f1_epoch > 2:
            lr = lr * 0.1

        print('Epoch {:04d} learning rate: {}'.format(epoch, lr))

        current_losses = []

        cnt=0

        # Equivalent to shuffling
        id_list = np.random.permutation(len(train_input_names))

        num_iters = int(np.floor(len(id_list) / args.batch_size))
        st = time.time()
        epoch_st=time.time()
        for i in range(num_iters):
            input_image_batch = []
            output_image_batch = [] 

            # Collect a batch of images
            for j in range(args.batch_size):
                index = i*args.batch_size + j
                id = id_list[index]
                input_image = utils.load_image(train_input_names[id])
                output_image = utils.load_image(train_output_names[id])

                with tf.device('/cpu:0'):
                    input_image, output_image = utils.data_augmentation(
                        input_image, output_image, args)

                    # Prep the data. Make sure the labels are in one-hot format
                    input_image = np.float32(input_image) / 255.0
                    output_image = np.float32(helpers.one_hot_it(label=output_image, label_values=label_info['label_values']))
                    
                    input_image_batch.append(np.expand_dims(input_image, axis=0))
                    output_image_batch.append(np.expand_dims(output_image, axis=0))

            if args.batch_size == 1:
                input_image_batch = input_image_batch[0]
                output_image_batch = output_image_batch[0]
            else:
                input_image_batch = np.squeeze(np.stack(input_image_batch, axis=1))
                output_image_batch = np.squeeze(np.stack(output_image_batch, axis=1))

            # Do the training
            _,current=sess.run([opt,loss],feed_dict={
                net_input:input_image_batch,
                net_output:output_image_batch,
                learning_rate: lr
                })
            current_losses.append(current)
            cnt = cnt + args.batch_size
            if cnt % 20 == 0:
                string_print = 'Epoch = %d Count = %d Current_Loss = %.4f Time = %.2f'%(epoch,cnt,current,time.time()-st)
                utils.LOG(string_print)
                st = time.time()

        mean_loss = np.mean(current_losses)
        avg_loss_per_epoch.append(mean_loss)
        
        # Create directories if needed
        if not os.path.isdir('%s/%04d'%('checkpoints',epoch)):
            os.makedirs('%s/%04d'%('checkpoints',epoch))

        if epoch % args.validation_step == 0:
            print('Performing validation')
            target=open('%s/%04d/val_scores.csv'%('checkpoints',epoch),'w')
            target.write('name, avg_accuracy, precision, recall, f1 score, mean iou, %s\n' % (label_info['class_names_string']))

            scores_list = []
            class_scores_list = []
            precision_list = []
            recall_list = []
            f1_list = []
            iou_list = []

            cm = np.zeros((label_info['num_classes'], label_info['num_classes']))

            # Do the validation on a small set of validation images
            for ind in val_indices:
                
                input_image = np.expand_dims(np.float32(utils.load_image(val_input_names[ind])[:args.crop_height, :args.crop_width]),axis=0)/255.0
                gt = utils.load_image(val_output_names[ind])[:args.crop_height, :args.crop_width]
                gt = helpers.reverse_one_hot(helpers.one_hot_it(gt, label_info['label_values']))

                # st = time.time()

                output_image = sess.run(network,feed_dict={net_input:input_image})
                

                output_image = np.array(output_image[0,:,:,:])
                output_image = helpers.reverse_one_hot(output_image)
                out_vis_image = helpers.colour_code_segmentation(output_image, label_info['label_values'])

                cm += confusion_matrix(
                    gt.ravel(), output_image.ravel(), labels=range(label_info['num_classes']))

                accuracy, class_accuracies, prec, rec, f1, iou = utils.evaluate_segmentation(
                    pred=output_image, label=gt,
                    num_classes=label_info['num_classes'], score_averaging=args.score_averaging)
            
                file_name = utils.filepath_to_name(val_input_names[ind])
                target.write('%s, %f, %f, %f, %f, %f'%(file_name, accuracy, prec, rec, f1, iou))
                for item in class_accuracies:
                    target.write(', %f'%(item))
                target.write('\n')

                scores_list.append(accuracy)
                class_scores_list.append(class_accuracies)
                precision_list.append(prec)
                recall_list.append(rec)
                f1_list.append(f1)
                iou_list.append(iou)
                
                gt = helpers.colour_code_segmentation(
                    gt, label_info['label_values'])
     
                file_name = os.path.basename(val_input_names[ind])
                file_name = os.path.splitext(file_name)[0]
                cv2.imwrite('%s/%04d/%s_pred.png'%('checkpoints',epoch, file_name),cv2.cvtColor(np.uint8(out_vis_image), cv2.COLOR_RGB2BGR))
                cv2.imwrite('%s/%04d/%s_gt.png'%('checkpoints',epoch, file_name),cv2.cvtColor(np.uint8(gt), cv2.COLOR_RGB2BGR))


            target.close()

            prfs_df = convert_prfs_to_data_frame(prfs(cm), label_info['class_names'])
            prfs_df['Mode'] = 'Val'
            prfs_df['Epoch'] = epoch + 1
            print(prfs_df)
            new_f1 = prfs_df[prfs_df.Class == 'Average/Total'].F1.values[0]

            if os.path.exists('prfs.json'):
                df = pd.read_json('prfs.json')
                df = pd.concat((df, prfs_df))
                prfs_df = df
            prfs_df.to_json('prfs.json', orient='records')

            avg_score = np.mean(scores_list)
            class_avg_scores = np.mean(class_scores_list, axis=0)
            avg_scores_per_epoch.append(avg_score)
            avg_precision = np.mean(precision_list)
            avg_recall = np.mean(recall_list)
            avg_f1 = np.mean(f1_list)
            avg_iou = np.mean(iou_list)

            print('\nAverage validation accuracy for epoch # %04d = %f'% (epoch, avg_score))
            print('Average per class validation accuracies for epoch # %04d:'% (epoch))
            for index, item in enumerate(class_avg_scores):
                print('%s = %f' % (label_info['class_names'][index], item))
            print('Validation precision = ', avg_precision)
            print('Validation recall = ', avg_recall)
            print('Validation F1 score = ', avg_f1)
            print('Validation F1 score (overall) = ', new_f1)
            print('Validation IoU score = ', avg_iou)

            if new_f1 > best_f1:
                print('New best F1 ({:.04f} > {:.04f})'.format(
                    new_f1, best_f1))
                print('Saving checkpoint')
                best_f1 = new_f1
                best_f1_epoch = epoch
                saver.save(sess, model_ckpt_name)

        epoch_time=time.time()-epoch_st
        remain_time=epoch_time*(args.num_epochs-1-epoch)
        m, s = divmod(remain_time, 60)
        h, m = divmod(m, 60)
        if s!=0:
            train_time='Remaining training time = %d hours %d minutes %d seconds\n'%(h,m,s)
        else:
            train_time='Remaining training time : Training completed.\n'
        utils.LOG(train_time)
        scores_list = []

elif args.mode == 'val':
    runner = lambda input_image: sess.run(network, feed_dict={net_input:input_image})
    utils.run_dataset(
        args, 'val', val_input_names, val_output_names, label_info, runner)
elif args.mode == 'test':
    runner = lambda input_image: sess.run(network, feed_dict={net_input:input_image})
    utils.run_dataset(
        args, 'test', test_input_names, test_output_names, label_info, runner)
elif args.mode == 'predict':
    raise ValueError('Only implemented for CamVid')

    if args.image is None:
        ValueError('You must pass an image path when using prediction mode.')

    print('\n***** Begin prediction *****')
    print('Dataset -->', args.dataset)
    print('Model -->', args.model)
    print('Crop Height -->', args.crop_height)
    print('Crop Width -->', args.crop_width)
    print('Num Classes -->', label_info['num_classes'])
    print('Image -->', args.image)
    print('')
    
    sys.stdout.write('Testing image ' + args.image)
    sys.stdout.flush()

    # to get the right aspect ratio of the output
    loaded_image = utils.load_image(args.image)
    height, width, channels = loaded_image.shape
    resize_height = int(height / (width / args.crop_width))

    resized_image =cv2.resize(loaded_image, (args.crop_width, resize_height))
    input_image = np.expand_dims(np.float32(resized_image[:args.crop_height, :args.crop_width]),axis=0)/255.0

    st = time.time()
    output_image = sess.run(network,feed_dict={net_input:input_image})

    run_time = time.time()-st

    output_image = np.array(output_image[0,:,:,:])
    output_image = helpers.reverse_one_hot(output_image)

    # this needs to get generalized
    label_info = helpers.get_label_info(os.path.join('CamVid', 'class_dict.csv'))

    out_vis_image = helpers.colour_code_segmentation(output_image, label_info['label_values'])
    file_name = utils.filepath_to_name(args.image)
    cv2.imwrite('%s/%s_pred.png'%('Predict', file_name),cv2.cvtColor(np.uint8(out_vis_image), cv2.COLOR_RGB2BGR))

    print('')
    print('Finished!')
    print('Wrote image ' + '%s/%s_pred.png'%('Test', file_name))

else:
    ValueError('Invalid mode selected.')
