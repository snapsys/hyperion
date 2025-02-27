#!/usr/bin/env python
"""
 Copyright 2020 Johns Hopkins University  (Author: Jesus Villalba)
 Apache 2.0  (http://www.apache.org/licenses/LICENSE-2.0)
"""
import sys
import os
from pathlib import Path
from jsonargparse import ArgumentParser, ActionConfigFile, ActionParser, namespace_to_dict
import time
import logging
import multiprocessing 

import numpy as np

import torch
import torch.nn as nn

from hyperion.hyp_defs import config_logger, set_float_cpu
from hyperion.torch.utils import open_device, ddp
from hyperion.torch.narchs import ResNet2dEncoder as Encoder
from hyperion.torch.narchs import ResNet2dDecoder as Decoder
from hyperion.torch.models import VAE
from hyperion.torch.trainers import VAETrainer as Trainer
from hyperion.torch.data import FeatSeqDataset as SD
from hyperion.torch.data import ClassWeightedSeqSampler as Sampler

def init_data(data_rspec, train_list, val_list, 
              num_workers, num_gpus, rank, **kwargs):
    sd_args = SD.filter_args(**kwargs)
    sampler_args = Sampler.filter_args(**kwargs)
    if rank == 0:
        logging.info('audio dataset args={}'.format(sd_args))
        logging.info('sampler args={}'.format(sampler_args))
        logging.info('init datasets')

    train_data = SD(data_rspec, train_list, **sd_args)
    val_data = SD(data_rspec, val_list, is_val=True, **sd_args)
    if rank == 0:
        logging.info('init samplers')
    train_sampler = Sampler(train_data, **sampler_args)
    val_sampler = Sampler(val_data, **sampler_args)

    num_workers_per_gpu = int((num_workers + num_gpus - 1) / num_gpus)
    largs = {'num_workers': num_workers_per_gpu, 'pin_memory': True} if num_gpus > 0 else {}

    train_loader = torch.utils.data.DataLoader(
        train_data, batch_sampler = train_sampler, **largs)

    test_loader = torch.utils.data.DataLoader(
        val_data, batch_sampler = val_sampler, **largs)

    return train_loader, test_loader


def init_model(rank, **kwargs):
    enc_args = Encoder.filter_args(**kwargs['enc'])
    dec_args = Decoder.filter_args(**kwargs['dec'])
    vae_args = VAE.filter_args(**kwargs)
    if rank == 0:
        logging.info('encoder args={}'.format(enc_args))
        logging.info('decoder args={}'.format(dec_args))
        logging.info('vae args={}'.format(vae_args))

    encoder = Encoder(**enc_args)
    decoder = Decoder(**dec_args)
    model = VAE(encoder, decoder, **vae_args)
    if rank == 0:
        logging.info('vae-model={}'.format(model))
    return model


def train_vae(gpu_id, args):
    config_logger(args.verbose)
    del args.verbose
    logging.debug(args)

    kwargs = namespace_to_dict(args)
    torch.manual_seed(args.seed)
    set_float_cpu('float32')

    ddp_args = ddp.filter_ddp_args(**kwargs)
    device, rank, world_size = ddp.ddp_init(gpu_id, **ddp_args)
    kwargs['rank'] = rank
    train_loader, test_loader = init_data(**kwargs)
    model = init_model(**kwargs)

    trn_args = Trainer.filter_args(**kwargs)
    if rank == 0:
        logging.info('trainer args={}'.format(trn_args))
    metrics = { 'mse': nn.MSELoss(), 'L1': nn.L1Loss() }
    trainer = Trainer(model, 
                      device=device, metrics=metrics, 
                      ddp=world_size>1, **trn_args)
    if args.resume:
        trainer.load_last_checkpoint()
    trainer.fit(train_loader, test_loader)

    ddp.ddp_cleanup()



# (data_rspec, train_list, val_list, 
#               num_gpus, resume, num_workers, **kwargs):

#     set_float_cpu('float32')
#     logging.info('initializing devices num_gpus={}'.format(num_gpus))
#     device = open_device(num_gpus=num_gpus)

#     sd_args = SD.filter_args(**kwargs)
#     sampler_args = Sampler.filter_args(**kwargs)
#     enc_args = Encoder.filter_args(prefix='enc', **kwargs)
#     dec_args = Decoder.filter_args(prefix='dec', **kwargs)
#     vae_args = VAE.filter_args(**kwargs)
#     opt_args = OF.filter_args(prefix='opt', **kwargs)
#     lrsch_args = LRSF.filter_args(prefix='lrsch', **kwargs)
#     trn_args = Trainer.filter_args(**kwargs)
#     logging.info('seq dataset args={}'.format(sd_args))
#     logging.info('sampler args={}'.format(sampler_args))
#     logging.info('encoder args={}'.format(enc_args))
#     logging.info('decoder args={}'.format(dec_args))
#     logging.info('vae args={}'.format(vae_args))
#     logging.info('optimizer args={}'.format(opt_args))
#     logging.info('lr scheduler args={}'.format(lrsch_args))
#     logging.info('trainer args={}'.format(trn_args))

#     logging.info('init datasets')
#     train_data = SD(data_rspec, train_list, 
#                     return_class=False, **sd_args)
#     val_data = SD(data_rspec, val_list, 
#                   return_class=False, is_val=True, **sd_args)

#     logging.info('init samplers')
#     train_sampler = Sampler(train_data, **sampler_args)
#     val_sampler = Sampler(val_data, **sampler_args)

#     largs = {'num_workers': num_workers, 'pin_memory': True} if num_gpus > 0 else {}

#     train_loader = torch.utils.data.DataLoader(
#         train_data, batch_sampler = train_sampler, **largs)

#     test_loader = torch.utils.data.DataLoader(
#         val_data, batch_sampler = val_sampler, **largs)

#     encoder = Encoder(**enc_args)
#     decoder = Decoder(**dec_args)
#     model = VAE(encoder, decoder, **vae_args)
#     logging.info(str(model))

#     optimizer = OF.create(model.parameters(), **opt_args)
#     lr_sch = LRSF.create(optimizer, **lrsch_args)
#     metrics = { 'mse': nn.MSELoss(), 'L1': nn.L1Loss() }

#     trainer = Trainer(model, optimizer,
#                       device=device, metrics=metrics, lr_scheduler=lr_sch,
#                       data_parallel=(num_gpus>1), **trn_args)
#     if resume:
#         trainer.load_last_checkpoint()
#     trainer.fit(train_loader, test_loader)



if __name__ == '__main__':

    parser = ArgumentParser(
        description='Train VAE with ResNet2d Encoder-Decoder')

    parser.add_argument('--cfg', action=ActionConfigFile)
    parser.add_argument('--data-rspec', required=True)
    parser.add_argument('--train-list', required=True)
    parser.add_argument('--val-list', required=True)

    SD.add_argparse_args(parser)
    Sampler.add_argparse_args(parser)

    parser.add_argument('--num-workers', type=int, default=5, 
                        help='num_workers of data loader')

    Encoder.add_class_args(parser, prefix='enc')
    Decoder.add_class_args(parser, prefix='dec')
    VAE.add_class_args(parser)

    Trainer.add_class_args(parser)
    ddp.add_ddp_args(parser)

    # parser.add_argument('--num-gpus', type=int, default=1,
    #                     help='number of gpus, if 0 it uses cpu')
    parser.add_argument('--seed', type=int, default=1123581321, 
                        help='random seed')
    parser.add_argument('--resume', action='store_true', default=False,
                        help='resume training from checkpoint')
    parser.add_argument('-v', '--verbose', dest='verbose', default=1, 
                        choices=[0, 1, 2, 3], type=int)
    parser.add_argument('--local_rank', default=0, type=int)

    args = parser.parse_args()
    gpu_id = args.local_rank
    del args.local_rank

    if gpu_id == 0:
        try:
            config_file = Path(args.exp_path) / 'config.yaml'
            parser.save(args, str(config_file), format='yaml', overwrite=True)
        except:
            pass

    # torch docs recommend using forkserver
    multiprocessing.set_start_method('forkserver')
    train_vae(gpu_id, args)

    # config_logger(args.verbose)
    # del args.verbose
    # logging.debug(args)

    # torch.manual_seed(args.seed)
    # del args.seed

    # train_vae(**vars(args))

