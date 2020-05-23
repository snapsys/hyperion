"""
 Copyright 2019 Johns Hopkins University  (Author: Jesus Villalba)
 Apache 2.0  (http://www.apache.org/licenses/LICENSE-2.0)
"""
from __future__ import absolute_import

import math

import torch
import torch.nn as nn
from torch.nn import Linear, Dropout

from ..layers import ActivationFactory as AF
from ..layer_blocks import MBConvBlock, MBConvInOutBlock
from .net_arch import NetArch

class EfficientNet(NetArch):
    params_dict = {
        # (width_coefficient, depth_coefficient, resolution, dropout_rate)
        'efficientnet-b0': (1.0, 1.0, 224, 0.2),
        'efficientnet-b1': (1.0, 1.1, 240, 0.2),
        'efficientnet-b2': (1.1, 1.2, 260, 0.3),
        'efficientnet-b3': (1.2, 1.4, 300, 0.3),
        'efficientnet-b4': (1.4, 1.8, 380, 0.4),
        'efficientnet-b5': (1.6, 2.2, 456, 0.4),
        'efficientnet-b6': (1.8, 2.6, 528, 0.5),
        'efficientnet-b7': (2.0, 3.1, 600, 0.5),
        'efficientnet-b8': (2.2, 3.6, 672, 0.5),
        'efficientnet-l2': (4.3, 5.3, 800, 0.5)}


    def __init__(self, effnet_type='efficientnet-b0', 
                 in_channels=1, in_conv_channels=32, in_kernel_size=3, in_stride=2,
                 mbconv_repeats=[1, 2, 2, 3, 3, 4, 1], 
                 mbconv_channels=[16, 24, 40, 80, 112, 192, 320], 
                 mbconv_kernel_sizes=[3, 3, 5, 3, 5, 5, 3], 
                 mbconv_strides=[1, 2, 2, 2, 1, 2, 1], 
                 mbconv_expansions=[1, 6, 6, 6, 6, 6, 6],
                 head_channels=1280, 
                 width_scale=None, depth_scale=None,
                 fix_stem_head=False,
                 out_units=0,
                 hid_act='swish', out_act=None,
                 drop_connect_rate=0.2, dropout_rate=0,
                 se_r=4, time_se=False, in_feats=None):

        super(EfficientNet, self).__init__()

        assert len(mbconv_repeats) == len(mbconv_channels)
        assert len(mbconv_repeats) == len(mbconv_kernel_sizes)
        assert len(mbconv_repeats) == len(mbconv_strides)
        assert len(mbconv_repeats) == len(mbconv_expansions)

        self.effnet_type = effnet_type

        self.in_channels = in_channels
        self.b0_in_conv_channels = in_conv_channels
        self.in_kernel_size = in_kernel_size
        self.in_stride = in_stride

        self.b0_mbconv_repeats = mbconv_repeats
        self.b0_mbconv_channels = mbconv_channels
        self.mbconv_kernel_sizes = mbconv_kernel_sizes
        self.mbconv_strides = mbconv_strides
        self.mbconv_expansions = mbconv_expansions

        self.b0_head_channels = head_channels
        self.out_units = out_units
        self.hid_act = hid_act
        
        self.drop_connect_rate = drop_connect_rate
        self.dropout_rate = dropout_rate

        self.se_r = se_r
        self.time_se = time_se
        self.in_feats = in_feats

        #set depth/width scales from net name
        self.cfg_width_scale = width_scale
        self.cfg_depth_scale = depth_scale
        if width_scale is None or dept_scale is None:
            width_scale, depth_scale = self.efficientnet_params(effnet_type)[:2]
        self.width_scale = width_scale
        self.depth_scale = depth_scale
        self.fix_stem_head = fix_stem_head
        
        self.in_conv_channels = self._round_channels(in_conv_channels, fix_stem_head)
        self.in_block = MBConvInOutBlock(
            in_channels, self.in_conv_channels, kernel_size=in_kernel_size, stride=in_stride)

        self._context = self.in_block.context
        self._downsample_factor = self.in_block.downsample_factor

        cur_in_channels = self.in_conv_channels
        cur_feats = None
        if self.time_se:
            cur_feats = (in_feats+in_stride-1)//in_stride

        num_superblocks = len(self.b0_mbconv_repeats)
        self.mbconv_channels = [0]*num_superblocks
        self.mbconv_repeats = [0]*num_superblocks
        total_blocks = 0
        for i in range(num_superblocks):
            self.mbconv_channels[i] = self._round_channels(
                self.b0_mbconv_channels[i])
            self.mbconv_repeats[i] = self._round_repeats(
                self.b0_mbconv_repeats[i])
            total_blocks += self.mbconv_repeats[i]

        self.blocks = nn.ModuleList([])
        k=0
        for i in range(num_superblocks):
            repeats_i = self.mbconv_repeats[i]
            channels_i = self.mbconv_channels[i]
            stride_i = self.mbconv_strides[i]
            kernel_size_i = self.mbconv_kernel_sizes[i]
            expansion_i = self.mbconv_expansions[i]
            drop_i = drop_connect_rate*k/(total_blocks-1)
            block_i = MBConvBlock(cur_in_channels, channels_i, expansion_i,
                                  kernel_size_i, stride_i, hid_act,
                                  drop_connect_rate=drop_i,
                                  se_r=se_r, time_se=time_se, 
                                  num_feats=cur_feats)
            self.blocks.append(block_i)
            k += 1
            self._context += block_i.context * self._downsample_factor
            self._downsample_factor *= block_i.downsample_factor
            if self.time_se:
                cur_feats = (cur_feats+stride_i-1)//stride_i 

            for j in range(repeats_i-1):
                drop_i = drop_connect_rate*k/(total_blocks-1)
                block_i = MBConvBlock(channels_i, channels_i, expansion_i,
                                      kernel_size_i, 1, hid_act,
                                      drop_connect_rate=drop_i,
                                      se_r=se_r, time_se=time_se, num_feats=cur_feats)
                self.blocks.append(block_i)
                k += 1
                self._context += block_i.context * self._downsample_factor

            cur_in_channels = channels_i
                
            
        #head feature block
        self.head_channels = self._round_channels(head_channels, fix_stem_head) 
        self.head_block = MBConvInOutBlock(
            cur_in_channels, self.head_channels, kernel_size=1, stride=1)

        self.with_output = False
        self.out_act = None
        if out_units > 0:
            self.with_output = True
            self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
            self.dropout = nn.Dropout(dropout_rate)
            self.output = nn.Linear(self.head_channels, out_units)
            self.out_act = AF.create(out_act)

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                act_name = 'relu'
                if isinstance(hid_act, str):
                    act_name = hid_act
                if isinstance(hid_act, dict):
                    act_name = hid_act['name']
                if act_name == 'swish':
                    act_name = 'relu'
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity=act_name)
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)



    @staticmethod
    def efficientnet_params(model_name):
        """Get efficientnet params based on model name."""
        return EfficientNet.params_dict[model_name]

    
    def _round_channels(self, channels, fix=False):
        """ Calculate and round number of channels based on depth multiplier. 
            It will make the number of channel multiple of 8
        """
        if fix:
            return channels
        divisor = 8 #this makes the number of channels a multiple of 8
        channels = channels * self.width_scale
        new_channels = max(divisor, int(channels + divisor / 2) // divisor * divisor)
        if new_channels < 0.9 * channels:  # prevent rounding by more than 10%
            new_channels += divisor
        return int(new_channels)


    def _round_repeats(self, repeats):
        """ Round number of block repeats based on depth multiplier. """
        return int(math.ceil(self.depth_scale * repeats))


    def _compute_out_size(self, in_size):
        out_size = int((in_size - 1)//self.in_stride+1)

        for stride in self.mbconv_strides:
            out_size = int((out_size - 1)//stride+1)

        return out_size


    def in_context(self):
        return (self._context, self._context)


    def in_shape(self):
        return (None, self.in_channels, None, None)
            

    def out_shape(self, in_shape=None):
        if self.with_output:
            return (None, self.out_units)

        if in_shape is None:
            return (None, self.head_block.out_channels, None, None)

        assert len(in_shape) == 4
        if in_shape[2] is None:
            H = None
        else:
            H = self._compute_out_size(in_shape[2])

        if in_shape[3] is None:
            W = None
        else:
            W = self._compute_out_size(in_shape[3])
            
        return (in_shape[0], self.head_block.out_channels, H, W)



    def forward(self, x):

        x = self.in_block(x)
        for idx, block in enumerate(self.blocks):
            x = block(x)

        x = self.head_block(x)

        if self.with_output:
            x = self.avgpool(x)
            x = torch.flatten(x, 1)
            x = self.dropout(x)
            x = self.output(x)
            if self.out_act is not None:
                x = self.out_act(x)

        return x


    def forward_hid_feats(self, x, layers=None, return_output=False):

        assert layers is not None or return_output
        if layers is None:
            layers = []
        
        if return_output:
            last_layer = len(self.blocks)+1
        else:
            last_layer = max(layers)
            
        h = []
        x = self.in_block(x)
        if 0 in layers:
            h.append(x)

        for idx, block in enumerate(self.blocks):
            x = block(x)
            if idx+1 in layers:
                h.append(x)
            if last_layer == idx+1:
                return h

        x = self.head_block(x)
        if len(self.blocks)+1 in layers:
            h.append(x)
            
        if return_output:
            return h, x
        
        return h
        

    def get_config(self):
        
        out_act = AF.get_config(self.out_act)
        hid_act = self.hid_act

        config = {'effnet_type': self.effnet_type,
                  'in_channels': self.in_channels,
                  'in_conv_channels': self.b0_in_conv_channels,
                  'in_kernel_size': self.in_kernel_size,
                  'in_stride': self.in_stride,
                  'mbconv_repeats': self.b0_mbconv_repeats,
                  'mbconv_channels': self.b0_mbconv_channels,
                  'mbconv_kernel_sizes': self.mbconv_kernel_sizes,
                  'mbconv_strides': self.mbconv_strides,
                  'mbconv_expansions': self.mbconv_expansions,
                  'head_channels': self.head_channels,
                  'width_scale': self.cfg_width_scale,
                  'depth_scale': self.cfg_width_scale,
                  'fix_stem_head': self.fix_stem_head,
                  'out_units': self.out_units,
                  'drop_connect_rate': self.drop_connect_rate,
                  'dropout_rate': self.dropout_rate,
                  'out_act': out_act,
                  'hid_act': hid_act,
                  'se_r' : self.se_r,
                  'time_se': self.time_se,
                  'in_feats': self.in_feats
              }
        
        base_config = super(EfficientNet, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))



    @staticmethod
    def filter_args(prefix=None, **kwargs):
        if prefix is None:
            p = ''
        else:
            p = prefix + '_'


        valid_args = ('effnet_type', 'in_channels',
                      'in_conv_channels', 'in_kernel_size', 'in_stride',
                      'mbconv_repeats', 'mbconv_channels', 'mbconv_kernel_sizes', 
                      'mbconv_strides', 'mbconv_expansions', 
                      'head_channels', 'width_scale', 'depth_scale',
                      'fix_stem_head', 'out_units',
                      'hid_act', 'out_act', 
                      'drop_connect_rate', 'dropout_rate',
                      'se_r', 'time_se')

        args = dict((k, kwargs[p+k])
                    for k in valid_args if p+k in kwargs)

        return args



    @staticmethod
    def add_argparse_args(parser, prefix=None):
        
        if prefix is None:
            p1 = '--'
        else:
            p1 = '--' + prefix + '-'

        net_types = list(EfficientNet.params_dict.keys())

        parser.add_argument(
            p1+'effnet-type', type=str.lower, default=net_types[0],
            choices=net_types, help=('EfficientNet type'))

        parser.add_argument(
            p1+'in-channels', default=1, type=int,
            help=('number of input channels'))

        parser.add_argument(
            p1+'in-conv-channels', default=32, type=int,
            help=('number of output channels in input convolution'))

        parser.add_argument(
            p1+'in-kernel-size', default=3, type=int,
            help=('kernel size of input convolution'))

        parser.add_argument(p1+'in-stride', default=2, type=int,
                            help=('stride of input convolution'))


        parser.add_argument(
            p1+'mbconv-repeasts', default=[1, 2, 2, 3, 3, 4, 1], type=int,
            nargs='+', help=('mbconv-mbconvs repeats for efficientnet-b0'))

        parser.add_argument(
            p1+'mbconv-channels', default=[16, 24, 40, 80, 112, 192, 320], 
            type=int, nargs='+',
            help=('mbconv-blocks channels for efficientnet-b0'))

        parser.add_argument(
            p1+'mbconv-kernel-sizes', default=[3, 3, 5, 3, 5, 5, 3], 
            nargs='+', type=int, help=('mbconv-size kernels for efficientnet-b0'))

        parser.add_argument(
            p1+'mbconv-strides', default=[1, 2, 2, 2, 1, 2, 1], 
            nargs='+', type=int, help=('mbconv-blocks strides for efficientnet-b0'))

        parser.add_argument(
            p1+'mbconv-expansions', default=[1, 6, 6, 6, 6, 6, 6],
            nargs='+', type=int, help=('mbconv-blocks expansions for efficientnet-b0'))

        parser.add_argument(
            p1+'head-channels', default=1280, type=int,
            help=('channels in the last conv block for efficientnet-b0'))

        parser.add_argument(
            p1+'width-scale', default=None, type=int,
            help=('width multiplicative factor wrt efficientnet-b0, if None inferred from effnet-type'))

        parser.add_argument(
            p1+'depth-scale', default=None, type=int,
            help=('depth multiplicative factor wrt efficientnet-b0, if None inferred from effnet-type'))

        parser.add_argument(
            p1+'fix-stem-head', default=False, action='store_true',
            help=('if True, the input and head conv blocks are not affected by the width-scale factor'))

        parser.add_argument(
            p1+'se-r', default=4, type=int,
            help=('squeeze ratio in squeeze-excitation blocks'))

        parser.add_argument(
            p1+'time_se', default=False, action='store_true',
            help=('squeeze-excitation pooling operation in time-dimension only'))

        try:
            parser.add_argument(p1+'hid_act', default='swish', 
                                help='hidden activation')
        except:
            pass
        
        parser.add_argument(p1+'drop-connect-rate', default=0.2, type=float,
                            help='layer drop probability')
        
        try:
            parser.add_argument(p1+'dropout-rate', default=0, type=float,
                                help='dropout probability')
        except:
            pass

