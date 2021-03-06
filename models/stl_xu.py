'''It is a modified version of the unofficial implementaion of 
'Wide Residual Networks'
Paper: https://arxiv.org/abs/1605.07146
Code: https://github.com/xternalz/WideResNet-pytorch

MIT License
Copyright (c) 2020 Ivan Sosnovik, Michał Szmaja
Copyright (c) 2019 xternalz
'''
import torch
import torch.nn as nn
import torch.nn.init as init
import torch.nn.functional as F
import math

from .impl.scale_modules import XU_SIConv2d


class BasicBlock(nn.Module):
    def __init__(self, in_planes, out_planes, stride, dropRate=0.0, scales=[1]):
        super(BasicBlock, self).__init__()
        self.bn1 = nn.BatchNorm2d(in_planes * len(scales))
        self.relu1 = nn.ReLU(inplace=True)
        self.conv1 = XU_SIConv2d(in_planes, out_planes, kernel_size=3,
                                 stride=stride, scales=scales, num_input_scales=len(scales))
        self.bn2 = nn.BatchNorm2d(out_planes * len(scales))
        self.relu2 = nn.ReLU(inplace=True)
        self.conv2 = XU_SIConv2d(out_planes, out_planes, kernel_size=3,
                                 stride=1, scales=scales, num_input_scales=len(scales))
        self.droprate = dropRate
        self.equalInOut = (in_planes == out_planes)
        self.convShortcut = (not self.equalInOut) and XU_SIConv2d(
            in_planes, out_planes, kernel_size=1, stride=stride, scales=scales, num_input_scales=len(scales)) or None

    def forward(self, x):
        if not self.equalInOut:
            x = self.relu1(self.bn1(x))
        else:
            out = self.relu1(self.bn1(x))
        out = self.relu2(self.bn2(self.conv1(out if self.equalInOut else x)))
        if self.droprate > 0:
            out = F.dropout(out, p=self.droprate, training=self.training)
        out = self.conv2(out)
        return torch.add(x if self.equalInOut else self.convShortcut(x), out)


class NetworkBlock(nn.Module):
    def __init__(self, nb_layers, in_planes, out_planes, block, stride, dropRate=0.0, scales=[1]):
        super(NetworkBlock, self).__init__()
        self.layer = self._make_layer(block, in_planes, out_planes,
                                      nb_layers, stride, dropRate, scales)

    def _make_layer(self, block, in_planes, out_planes, nb_layers, stride, dropRate, scales=[1]):
        layers = []
        for i in range(nb_layers):
            layers.append(block(i == 0 and in_planes or out_planes,
                                out_planes, i == 0 and stride or 1, dropRate, scales=scales))
        return nn.Sequential(*layers)

    def forward(self, x):
        return self.layer(x)


class WideResNet(nn.Module):
    def __init__(self, depth, num_classes, widen_factor=1, dropRate=0.0, scales=[1]):
        super(WideResNet, self).__init__()
        nChannels = [16, 16 * widen_factor, 32 * widen_factor, 64 * widen_factor]
        assert((depth - 4) % 6 == 0)
        n = (depth - 4) // 6
        block = BasicBlock
        self.num_scales = len(scales)
        # 1st conv before any network block
        self.conv1 = XU_SIConv2d(3, nChannels[0], kernel_size=3,
                                 stride=1, scales=scales, num_input_scales=1)
        # 1st block
        self.block1 = NetworkBlock(n, nChannels[0], nChannels[1], block, 1, dropRate, scales=scales)
        # 2nd block
        self.block2 = NetworkBlock(n, nChannels[1], nChannels[2], block, 2, dropRate, scales=scales)
        # 3rd block
        self.block3 = NetworkBlock(n, nChannels[2], nChannels[3], block, 2, dropRate, scales=scales)
        # global average pooling and classifier
        self.bn1 = nn.BatchNorm2d(nChannels[3] * len(scales))
        self.relu = nn.ReLU(inplace=True)
        self.fc = nn.Linear(nChannels[3], num_classes)
        self.nChannels = nChannels[3]

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()
            elif isinstance(m, nn.Linear):
                m.bias.data.zero_()

    def forward(self, x):
        out = self.conv1(x)
        out = self.block1(out)
        out = self.block2(out)
        out = self.block3(out)
        out = self.relu(self.bn1(out))

        out = F.avg_pool2d(out, 24)

        # pool from groups
        B, C, H, W = out.shape
        out = out.view(B, self.num_scales, C // self.num_scales, H, W)
        out = out.max(1)[0]

        out = out.view(-1, self.nChannels)
        out = self.fc(out)
        return out


def wrn_16_8_xu(num_classes, **kwargs):
    scales = [0.67, 1.0, 1.5]
    return WideResNet(depth=16, num_classes=10, widen_factor=8, dropRate=0.3, scales=scales)
