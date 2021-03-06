import os
import os.path as op
from ..externals.six.moves import cPickle as pickle
import glob
import warnings

import numpy as np
from numpy.testing import assert_array_equal, assert_array_almost_equal
from nose.tools import assert_true, assert_raises

from mne.datasets import sample
from mne import (label_time_courses, read_label, stc_to_label,
                 read_source_estimate, read_source_spaces, grow_labels,
                 labels_from_parc, parc_from_labels)
from mne.label import Label
from mne.utils import requires_mne, run_subprocess, _TempDir, requires_sklearn
from mne.fixes import in1d

warnings.simplefilter('always')  # enable b/c these tests throw warnings

data_path = sample.data_path(download=False)
subjects_dir = op.join(data_path, 'subjects')
stc_fname = op.join(data_path, 'MEG', 'sample', 'sample_audvis-meg-lh.stc')
real_label_fname = op.join(data_path, 'MEG', 'sample', 'labels',
                           'Aud-lh.label')
real_label_rh_fname = op.join(data_path, 'MEG', 'sample', 'labels',
                              'Aud-rh.label')
src_fname = op.join(data_path, 'MEG', 'sample',
                    'sample_audvis-eeg-oct-6p-fwd.fif')

test_path = op.join(op.split(__file__)[0], '..', 'fiff', 'tests', 'data')
label_fname = op.join(test_path, 'test-lh.label')
label_rh_fname = op.join(test_path, 'test-rh.label')
tempdir = _TempDir()

# This code was used to generate the "fake" test labels:
#for hemi in ['lh', 'rh']:
#    label = Label(np.unique((np.random.rand(100) * 10242).astype(int)),
#                  hemi=hemi, comment='Test ' + hemi, subject='fsaverage')
#    label.save(op.join(test_path, 'test-%s.label' % hemi))


def assert_labels_equal(l0, l1, decimal=5):
    for attr in ['comment', 'hemi', 'subject']:
        assert_true(getattr(l0, attr) == getattr(l1, attr))
    for attr in ['vertices', 'pos', 'values']:
        a0 = getattr(l0, attr)
        a1 = getattr(l1, attr)
        assert_array_almost_equal(a0, a1, decimal)


def test_label_subject():
    """Test label subject name extraction
    """
    label = read_label(label_fname)
    assert_true(label.subject is None)
    assert_true('unknown' in repr(label))
    label = read_label(label_fname, subject='fsaverage')
    assert_true(label.subject == 'fsaverage')
    assert_true('fsaverage' in repr(label))


def test_label_addition():
    """Test label addition
    """
    pos = np.random.rand(10, 3)
    values = np.arange(10.) / 10
    idx0 = list(range(7))
    idx1 = list(range(7, 10))  # non-overlapping
    idx2 = list(range(5, 10))  # overlapping
    l0 = Label(idx0, pos[idx0], values[idx0], 'lh')
    l1 = Label(idx1, pos[idx1], values[idx1], 'lh')
    l2 = Label(idx2, pos[idx2], values[idx2], 'lh')

    assert len(l0) == len(idx0)

    # adding non-overlapping labels
    l01 = l0 + l1
    assert len(l01) == len(l0) + len(l1)
    assert_array_equal(l01.values[:len(l0)], l0.values)

    # adding overlappig labels
    l = l0 + l2
    i0 = np.where(l0.vertices == 6)[0][0]
    i2 = np.where(l2.vertices == 6)[0][0]
    i = np.where(l.vertices == 6)[0][0]
    assert l.values[i] == l0.values[i0] + l2.values[i2]
    assert l.values[0] == l0.values[0]
    assert_array_equal(np.unique(l.vertices), np.unique(idx0 + idx2))

    # adding lh and rh
    l2.hemi = 'rh'
    # this now has deprecated behavior
    bhl = l0 + l2
    assert bhl.hemi == 'both'
    assert len(bhl) == len(l0) + len(l2)

    bhl = l1 + bhl
    assert_labels_equal(bhl.lh, l01)


@sample.requires_sample_data
def test_label_io_and_time_course_estimates():
    """Test IO for label + stc files
    """
    values, times, vertices = label_time_courses(real_label_fname, stc_fname)
    assert_true(len(times) == values.shape[1])
    assert_true(len(vertices) == values.shape[0])


def test_label_io():
    """Test IO of label files
    """
    label = read_label(label_fname)
    label.save(op.join(tempdir, 'foo'))
    label2 = read_label(op.join(tempdir, 'foo-lh.label'))
    assert_labels_equal(label, label2)

    # pickling
    dest = op.join(tempdir, 'foo.pickled')
    with open(dest, 'wb') as fid:
        pickle.dump(label, fid, pickle.HIGHEST_PROTOCOL)
    with open(dest, 'rb') as fid:
        label2 = pickle.load(fid)
    assert_labels_equal(label, label2)


def _assert_labels_equal(labels_a, labels_b, ignore_pos=False):
    """Make sure two sets of labels are equal"""
    for label_a, label_b in zip(labels_a, labels_b):
        assert_array_equal(label_a.vertices, label_b.vertices)
        assert_true(label_a.name == label_b.name)
        assert_true(label_a.hemi == label_b.hemi)
        if not ignore_pos:
            assert_array_equal(label_a.pos, label_b.pos)


@sample.requires_sample_data
def test_labels_from_parc():
    """Test reading labels from FreeSurfer parcellation
    """
    # test some invalid inputs
    assert_raises(ValueError, labels_from_parc, 'sample', hemi='bla',
                  subjects_dir=subjects_dir)
    assert_raises(ValueError, labels_from_parc, 'sample',
                  annot_fname='bla.annot', subjects_dir=subjects_dir)

    # read labels using hemi specification
    labels_lh, colors_lh = labels_from_parc('sample', hemi='lh',
                                            subjects_dir=subjects_dir)
    for label in labels_lh:
        assert_true(label.name.endswith('-lh'))
        assert_true(label.hemi == 'lh')

    assert_true(len(labels_lh) == len(colors_lh))

    # read labels using annot_fname
    annot_fname = op.join(subjects_dir, 'sample', 'label', 'rh.aparc.annot')
    labels_rh, colors_rh = labels_from_parc('sample', annot_fname=annot_fname,
                                            subjects_dir=subjects_dir)

    assert_true(len(labels_rh) == len(colors_rh))

    for label in labels_rh:
        assert_true(label.name.endswith('-rh'))
        assert_true(label.hemi == 'rh')

    # combine the lh, rh, labels and sort them
    labels_lhrh = list()
    labels_lhrh.extend(labels_lh)
    labels_lhrh.extend(labels_rh)

    names = [label.name for label in labels_lhrh]
    labels_lhrh = [label for (name, label) in sorted(zip(names, labels_lhrh))]

    # read all labels at once
    labels_both, colors = labels_from_parc('sample', subjects_dir=subjects_dir)

    assert_true(len(labels_both) == len(colors))

    # we have the same result
    _assert_labels_equal(labels_lhrh, labels_both)

    # aparc has 68 cortical labels
    assert_true(len(labels_both) == 68)

    # test regexp
    label = labels_from_parc('sample', parc='aparc.a2009s', regexp='Angu',
                             subjects_dir=subjects_dir)[0][0]
    assert_true(label.name == 'G_pariet_inf-Angular-lh')
    # silly, but real regexp:
    label = labels_from_parc('sample', parc='aparc.a2009s',
                             regexp='.*-.{4,}_.{3,3}-L',
                             subjects_dir=subjects_dir)[0][0]
    assert_true(label.name == 'G_oc-temp_med-Lingual-lh')
    assert_raises(RuntimeError, labels_from_parc, 'sample', parc='aparc',
                  annot_fname=annot_fname, regexp='JackTheRipper',
                  subjects_dir=subjects_dir)


@sample.requires_sample_data
@requires_mne
def test_labels_from_parc_annot2labels():
    """Test reading labels from parc. by comparing with mne_annot2labels
    """

    def _mne_annot2labels(subject, subjects_dir, parc):
        """Get labels using mne_annot2lables"""
        label_dir = _TempDir()
        cwd = os.getcwd()
        try:
            os.chdir(label_dir)
            env = os.environ.copy()
            env['SUBJECTS_DIR'] = subjects_dir
            cmd = ['mne_annot2labels', '--subject', subject, '--parc', parc]
            run_subprocess(cmd, env=env)
            label_fnames = glob.glob(label_dir + '/*.label')
            label_fnames.sort()
            labels = [read_label(fname) for fname in label_fnames]
        finally:
            del label_dir
            os.chdir(cwd)

        return labels

    labels, _ = labels_from_parc('sample', subjects_dir=subjects_dir)
    labels_mne = _mne_annot2labels('sample', subjects_dir, 'aparc')

    # we have the same result, mne does not fill pos, so ignore it
    _assert_labels_equal(labels, labels_mne, ignore_pos=True)


@sample.requires_sample_data
def test_parc_from_labels():
    """Test writing FreeSurfer parcellation from labels"""

    labels, colors = labels_from_parc('sample', subjects_dir=subjects_dir)

    # write left and right hemi labels:
    fnames = ['%s/%s-myparc' % (tempdir, hemi) for hemi in ['lh', 'rh']]

    for fname in fnames:
        parc_from_labels(labels, colors, annot_fname=fname)

    # read it back
    labels2, colors2 = labels_from_parc('sample', subjects_dir=subjects_dir,
                                        annot_fname=fnames[0])
    labels22, colors22 = labels_from_parc('sample', subjects_dir=subjects_dir,
                                          annot_fname=fnames[1])
    labels2.extend(labels22)
    colors2.extend(colors22)

    names = [label.name for label in labels2]

    for label, color in zip(labels, colors):
        idx = names.index(label.name)
        assert_labels_equal(label, labels2[idx])
        assert_array_almost_equal(np.array(color), np.array(colors2[idx]))

    # make sure we can't overwrite things
    assert_raises(ValueError, parc_from_labels, labels, colors,
                  annot_fname=fnames[0])

    # however, this works
    parc_from_labels(labels, colors=None, annot_fname=fnames[0],
                     overwrite=True)

    # test some other invalid inputs
    assert_raises(ValueError, parc_from_labels, labels[:-1], colors,
                  annot_fname=fnames[0], overwrite=True)
    colors2 = np.asarray(colors)
    assert_raises(ValueError, parc_from_labels, labels, colors2[:, :3],
                  annot_fname=fnames[0], overwrite=True)
    colors2[0] = 1.1
    assert_raises(ValueError, parc_from_labels, labels, colors2,
                  annot_fname=fnames[0], overwrite=True)


@sample.requires_sample_data
@requires_sklearn
def test_stc_to_label():
    """Test stc_to_label
    """
    src = read_source_spaces(src_fname)
    stc = read_source_estimate(stc_fname, 'sample')
    os.environ['SUBJECTS_DIR'] = op.join(data_path, 'subjects')
    labels1 = stc_to_label(stc, src='sample', smooth=3)
    with warnings.catch_warnings(record=True) as w:  # connectedness warning
        warnings.simplefilter('always')
        labels2 = stc_to_label(stc, src=src, smooth=3)
    assert_true(len(w) == 1)
    assert_true(len(labels1) == len(labels2))
    for l1, l2 in zip(labels1, labels2):
        assert_labels_equal(l1, l2, decimal=4)

    with warnings.catch_warnings(record=True) as w:  # connectedness warning
        warnings.simplefilter('always')
        labels_lh, labels_rh = stc_to_label(stc, src=src, smooth=3,
                                            connected=True)
    assert_true(len(w) == 1)
    assert_raises(ValueError, stc_to_label, stc, 'sample', smooth=3,
                  connected=True)
    assert_true(len(labels_lh) == 1)
    assert_true(len(labels_rh) == 1)


@sample.requires_sample_data
def test_morph():
    """Test inter-subject label morphing
    """
    label_orig = read_label(real_label_fname)
    label_orig.subject = 'sample'
    # should work for specifying vertices for both hemis, or just the
    # hemi of the given label
    vals = list()
    for grade in [5, [np.arange(10242), np.arange(10242)], np.arange(10242)]:
        label = label_orig.copy()
        # this should throw an error because the label has all zero values
        assert_raises(ValueError, label.morph, 'sample', 'fsaverage')
        label.values.fill(1)
        label.morph(None, 'fsaverage', 5, grade, subjects_dir, 2,
                    copy=False)
        label.morph('fsaverage', 'sample', 5, None, subjects_dir, 2,
                    copy=False)
        assert_true(np.mean(in1d(label_orig.vertices, label.vertices)) == 1.0)
        assert_true(len(label.vertices) < 3 * len(label_orig.vertices))
        vals.append(label.vertices)
    assert_array_equal(vals[0], vals[1])
    # make sure label smoothing can run
    label.morph(label.subject, 'fsaverage', 5,
                [np.arange(10242), np.arange(10242)], subjects_dir, 2,
                copy=False)
    # subject name should be inferred now
    label.smooth(subjects_dir=subjects_dir)


@sample.requires_sample_data
def test_grow_labels():
    """Test generation of circular source labels"""
    seeds = [0, 50000]
    # these were chosen manually in mne_analyze
    should_be_in = [[49, 227], [51207, 48794]]
    hemis = [0, 1]
    labels = grow_labels('sample', seeds, 3, hemis, n_jobs=2)

    for label, seed, hemi, sh in zip(labels, seeds, hemis, should_be_in):
        assert(np.any(label.vertices == seed))
        assert np.all(in1d(sh, label.vertices))
        if hemi == 0:
            assert(label.hemi == 'lh')
        else:
            assert(label.hemi == 'rh')


@sample.requires_sample_data
def test_label_time_course():
    """Test extracting label data from SourceEstimate"""
    values, times, vertices = label_time_courses(real_label_fname, stc_fname)
    stc = read_source_estimate(stc_fname)
    label_lh = read_label(real_label_fname)
    stc_lh = stc.in_label(label_lh)
    assert_array_almost_equal(stc_lh.data, values)
    assert_array_almost_equal(stc_lh.times, times)
    assert_array_almost_equal(stc_lh.vertno[0], vertices)

    label_rh = read_label(real_label_rh_fname)
    stc_rh = stc.in_label(label_rh)
    label_bh = label_rh + label_lh
    stc_bh = stc.in_label(label_bh)
    assert_array_equal(stc_bh.data, np.vstack((stc_lh.data, stc_rh.data)))
