#!/usr/bin/env python

import sys
import os
import argparse
import time
import numpy as np
import pandas as pd

frame_shift=0.01

def write_vad(f, file_id, vad):
    f.write('%s [ ' % (file_id))
    for i in range(len(vad)):
        f.write('%d ' % vad[i])
    f.write(']\n')

    
def rttm2vad_file(file_id, rttm, num_frames, fvad, fu2o, min_dur):

    _, spk_ids = np.unique(rttm.name, return_inverse=True)
    num_spks = np.max(spk_ids)+1

    if len(spk_ids) == 1:
        vad = np.zeros((num_frames,), dtype=int)
        tbeg = np.round(rttm.tbeg/frame_shift).astype('int')
        tend = min(np.round((rttm.tbeg+rttm.tdur)/frame_shift).astype('int'), num_frames)
        vad[tbeg:tend+1] = 1
        file_dir_id = '%s-d%03d' % (file_id,0)
        write_vad(fvad, file_dir_id, vad)
        fu2o.write('%s %s\n' % (file_dir_id, file_id))
        return
        
    
    total_dur = np.zeros((num_spks,), dtype=float)
    for i in range(num_spks):
        idx = spk_ids == i
        total_dur[i] = np.sum(rttm.tdur.loc[idx])

    do_all = np.all(total_dur < min_dur)
    for i in range(num_spks):
        if total_dur[i] >= min_dur or do_all:
            vad = np.zeros((num_frames,), dtype=int)
            idx = spk_ids == i
            tbeg = np.round(np.array(rttm.tbeg.loc[idx])/frame_shift).astype('int')
            tend = np.round(np.array(rttm.tbeg.loc[idx]+rttm.tdur.loc[idx])/frame_shift).astype('int')
            for j in range(len(tbeg)):
                vad[tbeg[j]:tend[j]+1] = 1
            file_dir_id = '%s-d%03d' % (file_id,i)
            write_vad(fvad, file_dir_id, vad)
            fu2o.write('%s %s\n' % (file_dir_id, file_id))
    

def rttm2vad(rttm_file, num_frames_file, vad_file, utt2orig, min_dur):

    rttm = pd.read_csv(rttm_file, sep='\s+', header=None,
                       names=['segment_type','file_id','chnl','tbeg','tdur',
                              'ortho','stype','name','conf','slat'])
    rttm.index = rttm.file_id
    
    df_num_frames = pd.read_csv(num_frames_file, sep='\s+', header=None,
                             names=['file_id','num_frames'])

    df_num_frames.index = df_num_frames.file_id


    with open(vad_file, 'w') as fvad:
        with open(utt2orig, 'w') as fu2o:
        
            for file_id in df_num_frames.file_id:
                num_frames_i = int(df_num_frames.num_frames.loc[file_id])
                print(file_id)
                rttm_i = rttm.loc[file_id]
                file_diars_ids=rttm2vad_file(
                    file_id, rttm_i, num_frames_i, fvad, fu2o, min_dur)
        
    

if __name__ == "__main__":

    parser=argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        fromfile_prefix_chars='@',
        description='Converts RTTM to kaldi VAD files')

    parser.add_argument('--rttm',dest='rttm_file', required=True)
    parser.add_argument('--num-frames', dest='num_frames_file', required=True)
    parser.add_argument('--vad-file', dest='vad_file', required=True)
    parser.add_argument('--utt2orig', dest='utt2orig', required=True)
    parser.add_argument('--min-dur', dest='min_dur', type=float, default=10)
    args=parser.parse_args()
    
    rttm2vad(**vars(args))
                            
