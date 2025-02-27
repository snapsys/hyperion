#!/usr/bin/env python
"""
Trains Backend for SRE18 tel condition
"""

import sys
import os
import argparse
import time

import numpy as np

from hyperion.helpers import VectorClassReader as VCR
from hyperion.helpers import VectorReader as VR
from hyperion.transforms import TransformList, LDA, LNorm
from hyperion.helpers import PLDAFactory as F
from hyperion.clustering import AHC
from hyperion.utils.utt2info import Utt2Info


def train_be(iv_file, train_list,
             adapt_iv_file, adapt_list,
             lda_dim,
             plda_type, y_dim, z_dim,
             epochs, ml_md, md_epochs,
             w_mu1, w_B1, w_W1,
             w_mu2, w_B2, w_W2, num_spks, do_ahc,
             output_path, **kwargs):

    # Read data
    vcr_args = VCR.filter_args(**kwargs)
    vcr = VCR(iv_file, train_list, None, **vcr_args)
    x, class_ids = vcr.read()

    # Train LDA
    t1 = time.time()

    lda = LDA(lda_dim=lda_dim, name='lda')
    lda.fit(x, class_ids)

    x_lda = lda.predict(x)
    print('LDA Elapsed time: %.2f s.' % (time.time()-t1))

    # Train centering and whitening
    t1 = time.time()
    lnorm = LNorm(name='lnorm')    
    lnorm.fit(x_lda)

    x_ln = lnorm.predict(x_lda)
    print('LNorm Elapsed time: %.2f s.' % (time.time()-t1))
    
    # Train PLDA
    t1 = time.time()

    plda = F.create_plda(plda_type, y_dim=y_dim, z_dim=z_dim,
                         name='plda')
    elbo = plda.fit(x_ln, class_ids, 
                    epochs=epochs, ml_md=ml_md, md_epochs=md_epochs)

    print('PLDA Elapsed time: %.2f s.' % (time.time()-t1))

    # Save models
    preproc = TransformList(lda)
    preproc.append(lnorm)

    if not os.path.exists(output_path):
        os.makedirs(ouput_path)

    preproc.save(output_path + '/lda_lnorm.h5')
    plda.save(output_path + '/plda.h5')

    num = np.arange(epochs)
    elbo = np.vstack((num, elbo)).T
    np.savetxt(output_path + '/elbo.csv', elbo, delimiter=',')
 
    # Compute mean for adapted data
    vcr = VCR(adapt_iv_file, adapt_list, None)
    x, class_ids = vcr.read()
    x_lda = lda.predict(x)
    lnorm.update_T = False
    lnorm.fit(x_lda)

    preproc = TransformList(lda)
    preproc.append(lnorm)

    preproc.save(output_path + '/lda_lnorm_adapt.h5')
    
    x_ln = lnorm.predict(x_lda)

    plda_adapt1 = plda.copy()
    plda_adapt2 = plda.copy()
    
    elbo = plda.fit(x_ln, class_ids, epochs=20)
    plda_adapt1.weighted_avg_model(plda, w_mu1, w_B1, w_W1)
    plda_adapt1.save(output_path + '/plda_adapt1.h5')

    num = np.arange(20)
    elbo = np.vstack((num, elbo)).T
    np.savetxt(output_path + '/elbo_adapt1.csv', elbo, delimiter=',')

    if not do_ahc:
        return
    
    scores = plda_adapt1.llr_1vs1(x_ln, x_ln)

    ahc = AHC(method='average', metric='llr')
    ahc.fit(scores)
    class_ids2 = ahc.get_flat_clusters(num_spks, criterion='num_clusters')

    elbo = plda_adapt1.fit(x_ln, class_ids2, epochs=20)
    plda_adapt2.weighted_avg_model(plda_adapt1, w_mu2, w_B2, w_W2)
    plda_adapt2.save(output_path + '/plda_adapt2.h5')
    
    num = np.arange(20)
    elbo = np.vstack((num, elbo)).T
    np.savetxt(output_path + '/elbo_adapt2.csv', elbo, delimiter=',')

    u2c_out = Utt2Info.create(vcr.u2c.key, class_ids2.astype('U'))
    u2c_out.save(output_path + '/output_adapt_spk2utt.scp', sep=' ')
    
    
if __name__ == "__main__":

    parser=argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        fromfile_prefix_chars='@',
        description='Train Back-end for SRE18 telephone condition')

    parser.add_argument('--iv-file', dest='iv_file', required=True)
    parser.add_argument('--train-list', dest='train_list', required=True)
    parser.add_argument('--adapt-iv-file', dest='adapt_iv_file', required=True)
    parser.add_argument('--adapt-list', dest='adapt_list', required=True)
    parser.add_argument('--do-ahc', dest='do_ahc', default=False, action='store_true')
    
    VCR.add_argparse_args(parser)
    F.add_argparse_train_args(parser)
    
    parser.add_argument('--output-path', dest='output_path', required=True)
    parser.add_argument('--lda-dim', dest='lda_dim', type=int,
                        default=150)
    parser.add_argument('--w-mu1', dest='w_mu1', type=float,
                        default=1)
    parser.add_argument('--w-b1', dest='w_B1', type=float,
                        default=1)
    parser.add_argument('--w-w1', dest='w_W1', type=float,
                        default=1)
    parser.add_argument('--w-mu2', dest='w_mu2', type=float,
                        default=1)
    parser.add_argument('--w-b2', dest='w_B2', type=float,
                        default=1)
    parser.add_argument('--w-w2', dest='w_W2', type=float,
                        default=1)
    parser.add_argument('--num-spks', dest='num_spks', type=int,
                        default=1000)
    
    args=parser.parse_args()
    
    train_be(**vars(args))

            
