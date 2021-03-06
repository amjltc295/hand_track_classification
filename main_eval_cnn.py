# -*- coding: utf-8 -*-
"""
Created on Thu Nov 15 14:24:00 2018

main_eval.py 

Used for evaluation of a model and outputs a confusion matrix, top1, top5 and per class accuracy metrics

for resnet models

@author: Γιώργος
"""

import os
import numpy as np
import cv2

import torch
import torch.utils.data
import torch.backends.cudnn as cudnn
import torchvision.transforms as transforms

from models.resnet_zoo import resnet_loader
from utils.dataset_loader import ImageDatasetLoader
from utils.dataset_loader_utils import WidthCrop, Resize, ResizePadFirst, To01Range
from utils.calc_utils import AverageMeter, accuracy, analyze_preds_labels
from utils.argparse_utils import parse_args
from utils.file_utils import print_and_save

np.set_printoptions(linewidth=np.inf, threshold=np.inf)
torch.set_printoptions(linewidth=1000000, threshold=1000000)

meanRGB=[0.485, 0.456, 0.406]
stdRGB=[0.229, 0.224, 0.225]
meanG = [0.5]
stdG = [1.]

interpolation_methods = {'linear':cv2.INTER_LINEAR, 'cubic':cv2.INTER_CUBIC,
                         'nn':cv2.INTER_NEAREST, 'area':cv2.INTER_AREA,
                         'lanc':cv2.INTER_LANCZOS4, 'linext':cv2.INTER_LINEAR_EXACT}

def validate_resnet(model, criterion, test_iterator, cur_epoch, dataset, log_file):
    losses, top1, top5 = AverageMeter(), AverageMeter(), AverageMeter()
    outputs = []
    
    print_and_save('Evaluating after epoch: {} on {} set'.format(cur_epoch, dataset), log_file)
    with torch.no_grad():
        model.eval()
        for batch_idx, (inputs, targets, video_names) in enumerate(test_iterator):
            inputs = torch.tensor(inputs).cuda()
            targets = torch.tensor(targets).cuda()
            
            output = model(inputs)            
            loss = criterion(output, targets)
            
            batch_preds = []
            for j in range(output.size(0)):
                res = np.argmax(output[j].detach().cpu().numpy())
                label = targets[j].cpu().numpy()
                outputs.append([res, label])
                batch_preds.append("{}, P-L:{}-{}".format(video_names[j], res, label))
                
            t1, t5 = accuracy(output.detach().cpu(), targets.cpu(), topk=(1,5))
            top1.update(t1.item(), output.size(0))
            top5.update(t5.item(), output.size(0))
            losses.update(loss.item(), output.size(0))

            print_and_save('[Batch {}/{}][Top1 {:.3f}[avg:{:.3f}], Top5 {:.3f}[avg:{:.3f}]]\n\t{}'.format(
                    batch_idx, len(test_iterator), top1.val, top1.avg, top5.val, top5.avg, batch_preds), log_file)
        print_and_save('{} Results: Loss {:.3f}, Top1 {:.3f}, Top5 {:.3f}'.format(dataset, losses.avg, top1.avg, top5.avg), log_file)
    return top1.avg, outputs


def main():
    args = parse_args('resnet', val=True)
    
    output_dir = os.path.dirname(args.ckpt_path)
    log_file = os.path.join(output_dir, "results-accuracy-validation.txt") if args.logging else None
    print_and_save(args, log_file)
    cudnn.benchmark = True

    model_ft = resnet_loader(args.verb_classes, 0, False, False, args.resnet_version, 
                         1 if args.channels == 'G' else 3, args.no_resize)
    model_ft = torch.nn.DataParallel(model_ft).cuda()
    checkpoint = torch.load(args.ckpt_path)
    # below line is needed if network is trained with DataParallel and now the model is not initiated with dataparallel
#    base_dict = {'.'.join(k.split('.')[1:]): v for k,v in list(checkpoint['state_dict'].items())}
#    model_ft.load_state_dict(base_dict) 
    model_ft.load_state_dict(checkpoint['state_dict'])
    print_and_save("Model loaded to gpu", log_file)

    mean = meanRGB if args.channels == 'RGB' else meanG
    std = stdRGB if args.channels == 'RGB' else stdG
    normalize = transforms.Normalize(mean=mean, std=std)
    if args.no_resize:
        resize = WidthCrop()
    else:
        if args.pad:
            resize = ResizePadFirst(224, False, interpolation_methods[args.inter]) # currently set this binarize to False, because it is false duh
        else:
            resize = Resize((224,224), False, interpolation_methods[args.inter])
    test_transforms = transforms.Compose([resize, To01Range(args.bin_img),
                                      transforms.ToTensor(), normalize])
    dataset_loader = ImageDatasetLoader(args.val_list, num_classes=args.verb_classes, 
                                        batch_transform=test_transforms, channels=args.channels,
                                        validation=True)
    collate_fn = torch.utils.data.dataloader.default_collate
    dataset_iterator = torch.utils.data.DataLoader(dataset_loader, 
                                                   batch_size=args.batch_size, 
                                                   num_workers=args.num_workers, 
                                                   collate_fn=collate_fn, 
                                                   pin_memory=True)

    ce_loss = torch.nn.CrossEntropyLoss().cuda()
    
    validate = validate_resnet
    top1, outputs = validate(model_ft, ce_loss, dataset_iterator, checkpoint['epoch'], args.val_list.split("\\")[-1], log_file)

    #video_pred = [np.argmax(x[0].detach().cpu().numpy()) for x in outputs]
    #video_labels = [x[1].cpu().numpy() for x in outputs]
    video_preds = [x[0] for x in outputs]
    video_labels = [x[1] for x in outputs]

    cf, recall, precision, cls_acc, mean_cls_acc, top1_acc = analyze_preds_labels(video_preds, video_labels)

    print_and_save(cf, log_file)
    print_and_save("Cls Rec {}".format(recall), log_file)
    print_and_save("Cls Pre {}".format(precision), log_file)
    print_and_save("Cls Acc {}".format(cls_acc), log_file)
    print_and_save("Mean Cls Acc {:.02f}%".format(mean_cls_acc), log_file)
    print_and_save("Dataset Acc {}".format(top1_acc), log_file)

if __name__ == '__main__':
    main()