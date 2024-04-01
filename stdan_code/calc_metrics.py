import numpy as np
import argparse
import glob
import os
import math
from skimage.metrics import structural_similarity as ssim
import cv2
import pandas as pd
from tqdm import tqdm
import lpips
import torch

'''
calculating SSIMs of all test video sequences

[Input]: Result Images

 230213_release_V2/
  ├ BasicSR/
  │  └ results/ 
  │     └ [Result Images]
  └ SSIM_graph/


[Output]: SSIM .csv files of each video sequence  (./SSIM_csv/xxx.csv)
'''

metric_type_list = ['PSNR', 'SSIM', 'LPIPS']

parser = argparse.ArgumentParser(description='make ssim.csv file from test results.')
parser.add_argument('--output_path', required = True, help="e.g., ./exp_log/WO_Motion_small_2024-02-08T161225_STDAN_Stack_BSD_3ms24ms_GOPRO/visualization/epoch-0200")
parser.add_argument('--save_dir', required = True, help="e.g., ./exp_log/20231129_STDAN_Stack_BSD_3ms24ms_ckpt-epoch-0905")
parser.add_argument('--gt_paths', required = True, nargs='+', help="e.g., ../../dataset/BSD3ms24ms/test ../../dataset/GOPRO_Large/test")
args = parser.parse_args()


# calculate convolution (for LPF)
def valid_convolve(xx, size):
    b = np.ones(size)/size
    xx_mean = np.convolve(xx, b, mode="same")

    n_conv = math.ceil(size/2)

    xx_mean[0] *= size/n_conv
    for i in range(1, n_conv):
        xx_mean[i] *= size/(i+n_conv)
        xx_mean[-i] *= size/(i + n_conv - (size % 2))

    return xx_mean

class Metric():
    def __init__(self, type):
        self.type = type
        if self.type == 'LPIPS':
            self.loss_fn_alex = lpips.LPIPS(net='alex')
        self.value_list = np.empty([0])

    def calc_metric(self, output_image, gt_image):
        if self.type == 'PSNR':
            self.value_list = np.append(self.value_list, cv2.PSNR(output_image, gt_image))
        elif self.type == 'SSIM':
            self.value_list = np.append(self.value_list, ssim(output_image, gt_image))
        elif self.type == 'LPIPS':
            output_tensor = torch.from_numpy(output_image.astype(np.float32)/255).clone()
            gt_tensor = torch.from_numpy(gt_image.astype(np.float32)/255).clone()
            d = self.loss_fn_alex(output_tensor, gt_tensor).detach().numpy()
            self.value_list = np.append(self.value_list, d[0,0,0,0])

    def reset(self):
        self.value_list = np.empty([0])


def calc_metrics(output_path, gt_paths, save_dir):

    seq_list = [f for f in sorted(os.listdir(output_path)) if (os.path.isdir(os.path.join(output_path, f)) and 'metrics_csv' not in f)]
    seq_dict = {} # {key='seq' : value=([output_path_list], [gt_path_list])}
    for seq in seq_list:    # make output_path_list and gt_path_list         
        output_frame_list = [f.split('/')[-1] for f in sorted(glob.glob(os.path.join(output_path, seq, '*.png')))]
        output_path_list = sorted(glob.glob(os.path.join(output_path, seq, '*.png')))
        for gt_path in gt_paths:
            if os.path.isdir(os.path.join(gt_path, seq, 'sharp')): #  GOPRO
                gt_path_list = [os.path.join(gt_path, seq, 'sharp', output_frame) for output_frame in output_frame_list]
            elif os.path.isdir(os.path.join(gt_path, seq, 'Sharp', 'RGB')):  # BSD_3ms24ms
                gt_path_list = [os.path.join(gt_path, seq, 'Sharp', 'RGB', output_frame) for output_frame in output_frame_list]
        assert len(output_path_list) == len(gt_path_list), f'output {len(output_path_list)}, GT {len(gt_path_list)} do not match.'
        seq_dict[seq] = (output_path_list, gt_path_list)

    # stack_df, avg_df initialize
    stack_df = pd.DataFrame(
        columns=['seq', 'frame']
        )
    avg_df = pd.DataFrame(index = seq_list)
    metric_list = []
    # metric instance initialize
    for metric_type in metric_type_list:
        stack_df[metric_type] = 0.0
        avg_df['avg' + metric_type] = 0.0
        metric_list.append(Metric(metric_type))
    # start calc
    for seq, (output_path_list, gt_path_list) in seq_dict.items():
        print(seq)
        for output_path, gt_path in tqdm(zip(output_path_list, gt_path_list)):
            assert os.path.basename(output_path) == os.path.basename(gt_path), f"basenames gt_file={os.path.basename(gt_path)} don't match"
            gt = cv2.cvtColor(cv2.imread(gt_path), cv2.COLOR_BGR2GRAY)
            output = cv2.cvtColor(cv2.imread(output_path), cv2.COLOR_BGR2GRAY)
            for metric in metric_list:  # calc each metric
                metric.calc_metric(output, gt)

        frame = [os.path.splitext(os.path.basename(f))[0] for f in output_path_list]
        data = {'seq':seq, 'frame':frame}
        for metric in metric_list:  # make data
            data[metric.type] = metric.value_list
            avg_df.at[seq, 'avg' + metric.type] = metric.value_list.mean()
            metric.reset()  # reset metric instance for next seq
        df = pd.DataFrame(data=data)
        stack_df = pd.concat([stack_df, df], axis=0)
        # save each dataframe
        save_path = os.path.join(save_dir,'metrics_csv')
        if not os.path.isdir(save_path):
            os.makedirs(save_path, exist_ok=True)
        df.to_csv(os.path.join(save_path, seq + '.csv'), index=False) # save to .csv

    # save avg_df, stack_df
    for metric_type in metric_type_list:
        avg_df.at['Avg.', 'avg' + metric_type] = avg_df['avg' + metric_type].mean()
    avg_df.to_csv(os.path.join(save_dir, 'avg_metrics.csv')) # save to .csv
    stack_df.to_csv(os.path.join(save_dir, 'stack.csv'))


if __name__ == '__main__':
    calc_metrics(args.output_path, args.gt_paths, args.save_dir)