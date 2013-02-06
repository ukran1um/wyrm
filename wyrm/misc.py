#!/usr/bin/env python


from os import path
import logging
import re

import numpy as np
from matplotlib import pyplot as plt
import scipy as sp
from scipy import signal
from sklearn.lda import LDA

logging.basicConfig(level=logging.NOTSET)
logger = logging.getLogger('foo')


def load_brain_vision_data(vhdr):
    logger.debug('Loading Brain Vision Data Exchange Header File')
    with open(vhdr) as fh:
        fdata = map(str.strip, fh.readlines())
    fdata = filter(lambda x: not x.startswith(';'), fdata)
    fdata = filter(lambda x: len(x) > 0, fdata)
    # check for the correct file version:
    assert fdata[0].endswith('1.0')
    # read all data into a dict where the key is the stanza of the file
    file_dict = dict()
    for line in fdata[1:]:
        if line.startswith('[') and line.endswith(']'):
            current_stanza = line[1:-1]
            file_dict[current_stanza] = []
        else:
            file_dict[current_stanza].append(line)
    # translate known stanzas from simple list of strings to a dict
    for stanza in 'Common Infos', 'Binary Infos', 'Channel Infos':
        logger.debug(stanza)
        file_dict[stanza] = {line.split('=', 1)[0]: line.split('=', 1)[1] for line in file_dict[stanza]}
    # now file_dict contains the parsed data from the vhdr file
    # load the rest
    data_f = file_dict['Common Infos']['DataFile']
    marker_f = file_dict['Common Infos']['MarkerFile']
    data_f = path.sep.join([path.dirname(vhdr), data_f])
    marker_f = path.sep.join([path.dirname(vhdr), marker_f])
    n_channels = int(file_dict['Common Infos']['NumberOfChannels'])
    sampling_interval_microseconds = float(file_dict['Common Infos']['SamplingInterval'])
    fs = 1 / (sampling_interval_microseconds / 10**6)
    channels = [file_dict['Channel Infos']['Ch%i' % (i + 1)] for i in range(n_channels)]
    channels = map(lambda x: x.split(',')[0], channels)
    # some assumptions about the data...
    assert file_dict['Common Infos']['DataFormat'] == 'BINARY'
    assert file_dict['Common Infos']['DataOrientation'] == 'MULTIPLEXED'
    assert file_dict['Binary Infos']['BinaryFormat'] == 'INT_16'
    print fs, n_channels
    print marker_f
    print data_f
    print channels
    # load EEG data
    logger.debug('Loading EEG Data.')
    data = np.fromfile(data_f, np.int16)
    data = data.reshape(-1, n_channels)
    # load marker
    logger.debug('Loading Marker.')
    regexp = r'^Mk(?P<mrk_nr>[0-9]*)=.*,(?P<mrk_descr>.*),(?P<mrk_pos>[0-9]*),[0-9]*,[0-9]*$'
    mrk = []
    with open(marker_f) as fh:
        for line in fh:
            line = line.strip()
            match = re.match(regexp, line)
            if match is None:
                continue
            mrk_pos = match.group('mrk_pos')
            mrk_descr = match.group('mrk_descr')
            if len(mrk_descr) > 1:
                mrk.append([mrk_pos, mrk_descr])
    return data, mrk, channels, fs


def plot_channels(data, n_channels):
    ax = []
    for i in range(n_channels):
        if i == 0:
            a = plt.subplot(10, n_channels / 10 + 1, i + 1)
        else:
            a = plt.subplot(10, n_channels / 10 + 1, i + 1, sharex=ax[0], sharey=ax[0])
        ax.append(a)
        a.plot(data[:, i])
        a.set_title(channels[i])


def segmentation(data, mrk, start, end):
    data2 = []
    for i in mrk:
        i_start, i_end = i+start, i+end
        chunk = data[i_start:i_end]
        data2.append(chunk)
    return np.array(data2)


def filter_bp(data, fs, low, high):
    # band pass filter the data
    fs_n = fs * 0.5
    #logger.debug('Calculating butter order...')
    #butter_ord, f_butter = signal.buttord(ws=[(low - .1) / fs_n, (high + .1) / fs_n],
    #                                      wp=[low / fs_n, high / fs_n],
    #                                      gpass=0.1,
    #                                      gstop=3.0
    #                                      )

    #logger.debug("{ord} {fbutter} {low} {high}".format(**{'ord': butter_ord,
    #                                                      'fbutter': f_butter,
    #                                                      'low': low / fs_n,
    #                                                      'high': high / fs_n}))
    butter_ord = 4
    b, a = signal.butter(butter_ord, [low / fs_n, high / fs_n], btype='band')
    return signal.lfilter(b, a, data, axis=0)


def calculate_csp(class1, class2):
    """Calculate the Common Spatial Pattern (CSP) for two classes.

    Example:
        Calculate the CSP for two classes:

        >>> w, a, d = calculate_csp(c1, c2)

        Take the first two and the last two columns of the sorted filter:

        >>> w = w[:, (0, 1, -2, -1)]

        Apply the new filter to your data d of the form (time, channels)

        >>> filtered = np.dot(d, w)

        You'll probably want to get the log-variance along the time axis

        >>> filtered = np.log(np.var(filtered, 0))

        This should result in four numbers (one for each channel).

    Args:
        class1: A matrix of the form (trials, time, channels) representing
            class 1.
        class2: A matrix of the form (trials, time, channels) representing the
            second class.

    Returns:
        A tuple (v, a, d). You should use the columns of the matrices.

        v: The sorted spacial filter.
        a: The sorted spacial pattern.
        d: The variances of the components.

    See:
        http://en.wikipedia.org/wiki/Common_spatial_pattern

    """
    # sven's super simple matlab code
    # function [W, A, lambda] = my_csp(X1, X2)
    #     % compute covariance matrices of the two classes
    #     C1 = compute_Covariance_Matrix(X1);
    #     C2 = compute_Covariance_Matrix(X2);
    #     % solution of CSP objective via generalized eigenvalue problem
    #     [W, D] = eig(C1-C2, C1+C2);
    #     % make sure the eigenvalues and eigenvectors are sorted correctly
    #     [lambda, sort_idx] = sort(diag(D), 'descend');
    #     W = W(:,sort_idx);
    #     A = inv(W)';

    n_channels = class1.shape[2]
    # we need a matrix of the form (observations, channels) so we stack trials
    # and time per channel together
    x1 = class1.reshape(-1, n_channels)
    x2 = class2.reshape(-1, n_channels)
    # compute covariance matrices of the two classes
    c1 = np.cov(x1.transpose())
    c2 = np.cov(x2.transpose())
    # solution of csp objective via generalized eigenvalue problem
    # in matlab the signature is v, d = eig(a, b)
    d, v = sp.linalg.eig(c1-c2, c1+c2)
    d = d.real
    # make sure the eigenvalues and -vectors are correctly sorted
    indx = np.argsort(d)
    # reverse
    indx = indx[::-1]
    d = d.take(indx)
    v = v.take(indx, axis=1)
    a = sp.linalg.inv(v).transpose()
    return v, a, d


# TODO: use that method
def moving_average(data, ws):
    window = numpy.ones(ws) / float(ws)
    return np.convolve(data, window, 'same')
