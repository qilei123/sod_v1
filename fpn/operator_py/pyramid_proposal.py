# --------------------------------------------------------
# Deformable Convolutional Networks
# Copyright (c) 2017 Microsoft
# Licensed under The MIT License [see LICENSE for details]
# Written by Haozhi Qi
# --------------------------------------------------------

import mxnet as mx
import numpy as np
import numpy.random as npr
from distutils.util import strtobool

from bbox.bbox_transform import bbox_pred, clip_boxes
from rpn.generate_anchor import generate_anchors
from nms.nms import gpu_nms_wrapper

from datetime import datetime

import os

import gc
DEBUG = False

LAYER_NUM = 5
PROPOSAL_LAYER=-2
class PyramidProposalOperator(mx.operator.CustomOp):
    def __init__(self, feat_stride, scales, ratios, output_score,
                 rpn_pre_nms_top_n, rpn_post_nms_top_n, threshold, rpn_min_size):
        super(PyramidProposalOperator, self).__init__()
        self._feat_stride = np.fromstring(feat_stride[1:-1], dtype=int, sep=',')
        self._scales = np.fromstring(scales[1:-1], dtype=float, sep=',')
        self._ratios = np.fromstring(ratios[1:-1], dtype=float, sep=',')
        self._num_anchors = len(self._scales) * len(self._ratios)
        self._output_score = output_score
        self._rpn_pre_nms_top_n = rpn_pre_nms_top_n
        self._rpn_post_nms_top_n = rpn_post_nms_top_n
        self._threshold = threshold
        self._rpn_min_size = rpn_min_size

    def forward(self, is_train, req, in_data, out_data, aux):
        before_pyramid_proposal = datetime.now()
        nms = gpu_nms_wrapper(self._threshold, in_data[0].context.device_id)

        batch_size = in_data[0].shape[0]
        if batch_size > 1:
            raise ValueError("Sorry, multiple images each device is not implemented")

        # for each (H, W) location i
        #   generate A anchor boxes centered on cell i
        #   apply predicted bbox deltas at cell i to each of the A anchors
        # clip predicted boxes to image
        # remove predicted boxes with either height or width < threshold
        # sort all (proposal, score) pairs by score from highest to lowest
        # take top pre_nms_topN proposals before NMS
        # apply NMS with threshold 0.7 to remaining proposals
        # take after_nms_topN proposals after NMS
        # return the top proposals (-> RoIs top, scores top)
        LAYER_NUM = len(in_data)/2
        LAYER_NUM = 11
        if LAYER_NUM==7:
            cls_prob_dict = {
                'stride64': in_data[6],
                'stride32': in_data[5],
                'stride16': in_data[4],
                'stride8': in_data[3],
                'stride4': in_data[2],
                'stride2': in_data[1],
                'stride1': in_data[0],
            }
            bbox_pred_dict = {
                'stride64': in_data[13],
                'stride32': in_data[12],
                'stride16': in_data[11],
                'stride8': in_data[10],
                'stride4': in_data[9],
                'stride2': in_data[8],
                'stride1': in_data[7],
            }
        
        elif LAYER_NUM==6:
            cls_prob_dict = {
                'stride64': in_data[5],
                'stride32': in_data[4],
                'stride16': in_data[3],
                'stride8': in_data[2],
                'stride4': in_data[1],
                'stride2': in_data[0],
            }
            bbox_pred_dict = {
                'stride64': in_data[11],
                'stride32': in_data[10],
                'stride16': in_data[9],
                'stride8': in_data[8],
                'stride4': in_data[7],
                'stride2': in_data[6],
            }        
        
        elif LAYER_NUM==5:
            cls_prob_dict = {
                'stride64': in_data[4],
                'stride32': in_data[3],
                'stride16': in_data[2],
                'stride8': in_data[1],
                'stride4': in_data[0],
            }
            bbox_pred_dict = {
                'stride64': in_data[9],
                'stride32': in_data[8],
                'stride16': in_data[7],
                'stride8': in_data[6],
                'stride4': in_data[5],
            } 
        elif LAYER_NUM==2:
            cls_prob_dict = {
                'stride64': in_data[4],
                'stride32': in_data[3],
            }
            bbox_pred_dict = {
                'stride64': in_data[9],
                'stride32': in_data[8],
            }
        elif LAYER_NUM==11:
            cls_prob_dict = {
                'stride64': in_data[0],
            }
            bbox_pred_dict = {
                'stride64': in_data[1],
            }  
        elif LAYER_NUM==1:
            cls_prob_dict = {
                'stride1': in_data[0],
            }
            bbox_pred_dict = {
                'stride1': in_data[1],
            }
        elif LAYER_NUM==3:
            cls_prob_dict = {
                'stride64': in_data[2],
                'stride32': in_data[1],
                'stride1': in_data[0],
            }
            bbox_pred_dict = {
                'stride64': in_data[5],
                'stride32': in_data[4],
                'stride1': in_data[3],
            }         
        '''
        cls_prob_dict = {
            'stride8': in_data[3],
            'stride4': in_data[2],
            'stride2': in_data[1],
            'stride1': in_data[0],
        }
        bbox_pred_dict = {
            'stride8': in_data[7],
            'stride4': in_data[6],
            'stride2': in_data[5],
            'stride1': in_data[4],
        }
        '''
        '''
        cls_prob_dict = {
            'stride2': in_data[1],
            'stride1': in_data[0],
        }
        bbox_pred_dict = {
            'stride2': in_data[3],
            'stride1': in_data[2],
        }        
        '''
        pre_nms_topN = self._rpn_pre_nms_top_n
        post_nms_topN = self._rpn_post_nms_top_n
        min_size = self._rpn_min_size

        proposal_list = []
        score_list = []

        channel_list = []

        before_feat = datetime.now()
        
        for s in self._feat_stride:
            stride = int(s)
            sub_anchors = generate_anchors(base_size=stride, scales=self._scales, ratios=self._ratios)
            #print "cls_prob_dict['stride' + str(s)].shape:"+str(cls_prob_dict['stride' + str(s)].shape)
            scores = cls_prob_dict['stride' + str(s)].asnumpy()[:, self._num_anchors:, :, :]
            
            if DEBUG:
                scores1 = cls_prob_dict['stride' + str(s)].asnumpy()
                print "scores.shape:"+str(scores.shape)
                print "scores1.shape:"+str(scores1.shape)

            #print "scores.shape:"+str(scores.shape)
            bbox_deltas = bbox_pred_dict['stride' + str(s)].asnumpy()
            #print "bbox_deltas.shape:"+str(bbox_deltas.shape)
            im_info = in_data[-1].asnumpy()[0, :]
            # 1. Generate proposals from bbox_deltas and shifted anchors
            # use real image size instead of padded feature map sizes
            height, width = int(im_info[0] / stride), int(im_info[1] / stride)

            # Enumerate all shifts
            
            shift_x = np.arange(0, width) * stride
            shift_y = np.arange(0, height) * stride
            shift_x, shift_y = np.meshgrid(shift_x, shift_y)
            shifts = np.vstack((shift_x.ravel(), shift_y.ravel(), shift_x.ravel(), shift_y.ravel())).transpose()

            # Enumerate all shifted anchors:
            #
            # add A anchors (1, A, 4) to
            # cell K shifts (K, 1, 4) to get
            # shift anchors (K, A, 4)
            # reshape to (K*A, 4) shifted anchors
            before_enume = datetime.now()
            A = self._num_anchors
            K = shifts.shape[0]
            anchors = sub_anchors.reshape((1, A, 4)) + shifts.reshape((1, K, 4)).transpose((1, 0, 2))
            anchors = anchors.reshape((K * A, 4))
            after_enume = datetime.now()
            #print "enume time:"+str((after_enume-before_enume).seconds)
            # Transpose and reshape predicted bbox transformations to get them
            # into the same order as the anchors:
            #
            # bbox deltas will be (1, 4 * A, H, W) format
            # transpose to (1, H, W, 4 * A)
            # reshape to (1 * H * W * A, 4) where rows are ordered by (h, w, a)
            # in slowest to fastest order

            bbox_deltas = self._clip_pad(bbox_deltas, (height, width))

            bbox_deltas = bbox_deltas.transpose((0, 2, 3, 1)).reshape((-1, 4))

            # Same story for the scores:
            #
            # scores are (1, A, H, W) format
            # transpose to (1, H, W, A)
            # reshape to (1 * H * W * A, 1) where rows are ordered by (h, w, a)
            scores = self._clip_pad(scores, (height, width))
            scores = scores.transpose((0, 2, 3, 1)).reshape((-1, 1))
            if DEBUG:
                print "scores[:100]:"+str(scores[:50])
            channels = np.ones((scores.shape))*stride

            # Convert anchors into proposals via bbox transformations
            before_pred = datetime.now()
            proposals = bbox_pred(anchors, bbox_deltas)
            after_pred = datetime.now()
            #print "pred_time:"
            #print (after_pred-before_pred).seconds
            # 2. clip predicted boxes to image
            proposals = clip_boxes(proposals, im_info[:2])
            # 3. remove predicted boxes with either height or width < threshold
            # (NOTE: convert min_size to input image scale stored in im_info[2])
            if DEBUG:
                print str(min_size)
                print str(im_info[2])
            keep = self._filter_boxes(proposals, min_size * im_info[2])
            proposals = proposals[keep, :]
            if DEBUG:
                print "proposals3:"+str(proposals[0:10])
            scores = scores[keep]

            channels = channels[keep]

            proposal_list.append(proposals)
            score_list.append(scores)
            channel_list.append(channels)
        after_feat = datetime.now()
        #print "feat time:"
        #print (after_feat-before_feat).seconds

        proposals = np.vstack(proposal_list)
        scores = np.vstack(score_list)
        channels = np.vstack(channel_list)
        # 4. sort all (proposal, score) pairs by score from highest to lowest
        # 5. take top pre_nms_topN (e.g. 6000)
        before_sort = datetime.now()
        order = scores.ravel().argsort()[::-1]
        after_sort = datetime.now()
        #print "sort time:"
        #print (after_sort-before_sort).seconds
        if pre_nms_topN > 0:
            order = order[:pre_nms_topN]
        proposals = proposals[order, :]
        scores = scores[order]
        channels = channels[order]
        if DEBUG:
            print '-------1-------'
            print channels.shape
            for s in self._feat_stride:
                print "stride:"+str(s)
                print len(np.where(channels==float(s))[0])
            print "proposals:"+str(proposals[0:20])
        # 6. apply nms (e.g. threshold = 0.7)
        # 7. take after_nms_topN (e.g. 300)
        # 8. return the top proposals (-> RoIs top)
        det = np.hstack((proposals, scores)).astype(np.float32)
         
        keep = nms(det)

        if post_nms_topN > 0:
            keep = keep[:post_nms_topN]
        # pad to ensure output size remains unchanged
        if len(keep) < post_nms_topN:
            pad = npr.choice(keep, size=post_nms_topN - len(keep))
            keep = np.hstack((keep, pad))
        proposals = proposals[keep, :]
        scores = scores[keep]
        channels = channels[keep]
        if DEBUG:
            print '-------2-------'
            print channels.shape
            for s in self._feat_stride:
                print "stride:"+str(s)
                print len(np.where(channels==float(s))[0])
            print "proposals:"+str(proposals[0:20])
            print "scores:"+str(scores[0:20])
        f_chan = open('channels.txt','w')
        for ii in range(channels.shape[0]):
            f_chan.write(str(channels[ii][0])+' ')
        f_chan.close()

        # Output rois array
        # Our RPN implementation only supports a single input image, so all
        # batch inds are 0
        batch_inds = np.zeros((proposals.shape[0], 1), dtype=np.float32)
        blob = np.hstack((batch_inds, proposals.astype(np.float32, copy=False)))
        # if is_train:
        self.assign(out_data[0], req[0], blob)
        #print "out_data[0].shape"+str(out_data[0].shape)
        if self._output_score:
            self.assign(out_data[1], req[1], scores.astype(np.float32, copy=False))
        after_pyramid_proposal = datetime.now()
        #print 'pyramid_proposal times:'
        #print (after_pyramid_proposal-before_pyramid_proposal).seconds
    def backward(self, req, out_grad, in_data, out_data, in_grad, aux):
        for i in range(len(in_grad)):
            self.assign(in_grad[i], req[i], 0)
        gc.collect()

    @staticmethod
    def _filter_boxes(boxes, min_size):
        """ Remove all boxes with any side smaller than min_size """
        ws = boxes[:, 2] - boxes[:, 0] + 1
        hs = boxes[:, 3] - boxes[:, 1] + 1
        keep = np.where((ws >= min_size) & (hs >= min_size))[0]
        return keep

    @staticmethod
    def _clip_pad(tensor, pad_shape):
        """
        Clip boxes of the pad area.
        :param tensor: [n, c, H, W]
        :param pad_shape: [h, w]
        :return: [n, c, h, w]
        """
        H, W = tensor.shape[2:]
        h, w = pad_shape

        if h < H or w < W:
            tensor = tensor[:, :, :h, :w].copy()

        return tensor


@mx.operator.register("pyramid_proposal")
class PyramidProposalProp(mx.operator.CustomOpProp):
    def __init__(self, feat_stride='(64, 32, 16, 8, 4)', scales='(8)', ratios='(0.5, 1, 2)', output_score='False',
                 rpn_pre_nms_top_n='12000', rpn_post_nms_top_n='2000', threshold='0.3', rpn_min_size='16', output_pyramid_rois='False'):
        super(PyramidProposalProp, self).__init__(need_top_grad=False)
        self._feat_stride = feat_stride
        self._scales = scales
        self._ratios = ratios
        self._output_score = strtobool(output_score)
        self._rpn_pre_nms_top_n = int(rpn_pre_nms_top_n)
        self._rpn_post_nms_top_n = int(rpn_post_nms_top_n)
        self._threshold = float(threshold)
        self._rpn_min_size = int(rpn_min_size)
        self.output_pyramid_rois = strtobool(output_pyramid_rois)

    def list_arguments(self):
        arg_list = []
        for s in np.fromstring(self._feat_stride[1:-1], dtype=int, sep=','):
            arg_list.append('rpn_cls_prob_stride' + str(s))
        for s in np.fromstring(self._feat_stride[1:-1], dtype=int, sep=','):
            arg_list.append('rpn_bbox_pred_stride' + str(s))
        arg_list.append('im_info')
        return arg_list

    def list_outputs(self):
        if self.output_pyramid_rois:
            return ['output', 'output_p3', 'output_p4', 'output_p5', 'output_idx']
        else:
            if self._output_score:
                return ['output', 'score']
            else:
                return ['output']

    def infer_shape(self, in_shape):
        output_shape = (self._rpn_post_nms_top_n, 5)
        score_shape = (self._rpn_post_nms_top_n, 1)

        if self.output_pyramid_rois:
            return in_shape, [output_shape, output_shape, output_shape, output_shape, (self._rpn_post_nms_top_n,)]
        else:
            if self._output_score:
                return in_shape, [output_shape, score_shape]
            else:
                return in_shape, [output_shape]

    def create_operator(self, ctx, shapes, dtypes):
        return PyramidProposalOperator(self._feat_stride, self._scales, self._ratios, self._output_score,
                                       self._rpn_pre_nms_top_n, self._rpn_post_nms_top_n, self._threshold, self._rpn_min_size)

    def declare_backward_dependency(self, out_grad, in_data, out_data):
        return []
