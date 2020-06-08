# -*- coding: utf-8 -*-
# coding=utf-8
# Copyright 2019 The SGNMT Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""This module contains the output handlers. These handlers create 
output files from the n-best lists generated by the ``Decoder``. They
can be activated via --outputs.

This module depends on OpenFST to write FST files in binary format. To
enable Python support in OpenFST, use a recent version (>=1.5.4) and 
compile with ``--enable_python``. Further information can be found here:

http://www.openfst.org/twiki/bin/view/FST/PythonExtension 

"""

from abc import abstractmethod
import os
import errno
import logging
from cam.sgnmt import utils
from cam.sgnmt import io
import numpy as np
import codecs
from collections import defaultdict

try:
    import pywrapfst as fst
except ImportError:
    try:
        import openfst_python as fst
    except ImportError:
        pass # Deal with it in decode.py


def _mkdir(path, name):
    try:
        os.makedirs(path)
    except OSError as exception:
        if exception.errno != errno.EEXIST:
            raise
        else:
            logging.warn("Output %s directory '%s' already exists." 
                         % (name, path))


class OutputHandler(object):
    """Interface for output handlers. """
    
    def __init__(self):
        """ Empty constructor """
        pass
    
    @abstractmethod
    def write_hypos(self, all_hypos, sen_indices=None):
        """This method writes output files to the file system. The
        configuration parameters such as output paths should already
        have been provided via constructor arguments.
        
        Args:
            all_hypos (list): list of nbest lists of hypotheses
            sen_indices (list): List of sentence indices (0-indexed)
        
        Raises:
            IOError. If something goes wrong while writing to the disk
        """
        raise NotImplementedError


class TextOutputHandler(OutputHandler):
    """Writes the first best hypotheses to a plain text file """
    
    def __init__(self, path):
        """Creates a plain text output handler to write to ``path`` """
        super(TextOutputHandler, self).__init__()
        self.path = path
        
    def write_hypos(self, all_hypos, sen_indices=None):
        """Writes the hypotheses in ``all_hypos`` to ``path`` """
        if self.f is not None:
            for hypos in all_hypos:
                self.f.write(io.decode(hypos[0].trgt_sentence))
                self.f.write("\n")
                self.f.flush()
        else:
            with codecs.open(self.path, "w", encoding='utf-8') as f:
                for hypos in all_hypos:
                    f.write(io.decode(hypos[0].trgt_sentence))
                    f.write("\n")
                    self.f.flush()

    def open_file(self):
        self.f = codecs.open(self.path, "w", encoding='utf-8')

    def close_file(self):
        self.f.close()

class ScoreOutputHandler(OutputHandler):
    """Writes the first best hypotheses to a plain text file """
    
    def __init__(self, path):
        """Creates a plain text output handler to write to ``path`` """
        super(ScoreOutputHandler, self).__init__()
        self.path = path
        self.open_file()
        
    def write_score(self, score):
        """Writes the hypotheses in ``all_hypos`` to ``path`` """
        def write(f_, score):
            f_.write(str([s[0][0] for s in score]))
            f_.write("\n")
            f_.flush()

        if self.f is not None:
            write(self.f, score)
        else:
            with codecs.open(self.path, "w", encoding='utf-8') as f:
                write(f, score)

    def write_hypos(self, all_hypos, sen_indices=None):
        pass

    def open_file(self):
        self.f = codecs.open(self.path, "w", encoding='utf-8')

    def close_file(self):
        self.f.close()


class NBestSeparateOutputHandler(OutputHandler):
    """Produces n-best files with hypotheses at respecitve positions
    """
    
    def __init__(self, path, N):
        """
        Args:
            path (string):  Path to the n-best file to write
            N: n-best 
        """
        super(NBestSeparateOutputHandler, self).__init__()
        self.paths = [path + '_' + str(i) + '.txt' for i in range(N)]
        
    def write_hypos(self, all_hypos, sen_indices=None):
        """Writes the hypotheses in ``all_hypos`` to ``path`` """
        if not self.f:
            self.open_file()
        for hypos in all_hypos:
            while len(hypos) < len(self.f):
                hypos.append(hypos[-1])
            for i in range(len(self.f)):
                self.f[i].write(io.decode(hypos[i].trgt_sentence))
                self.f[i].write("\n")
                self.f[i].flush()

    def open_file(self):
        self.f = []
        for p in self.paths:
            self.f.append(codecs.open(p, "w", encoding='utf-8'))

    def close_file(self):
        for f in self.f:
            f.close()


class NBestOutputHandler(OutputHandler):
    """Produces a n-best file in Moses format. The third part of each 
    entry is used to store the separated unnormalized predictor scores.
    Note that the sentence IDs are shifted: Moses n-best files start 
    with the index 0, but in SGNMT and HiFST we usually refer to the 
    first sentence with 1 (e.g. in lattice directories or --range)
    """
    
    def __init__(self, path, predictor_names):
        """Creates a Moses n-best list output handler.
        
        Args:
            path (string):  Path to the n-best file to write
            predictor_names: Names of the predictors whose scores
                             should be included in the score breakdown
                             in the n-best list
        """
        super(NBestOutputHandler, self).__init__()
        self.path = path
        self.predictor_names = []
        name_count = {}
        for name in predictor_names:
            if not name in name_count:
                name_count[name] = 1
                final_name = name
            else:
                name_count[name] += 1
                final_name = "%s%d" % (name, name_count[name])
            self.predictor_names.append(final_name.replace("_", "0"))
        
        
    def write_hypos(self, all_hypos, sen_indices):
        """Writes the hypotheses in ``all_hypos`` to ``path`` """
        with codecs.open(self.path, "w", encoding='utf-8') as f:
            n_predictors = len(self.predictor_names)
            for idx, hypos in zip(sen_indices, all_hypos):
                for hypo in hypos:
                    f.write("%d ||| %s ||| %s ||| %f" %
                            (idx,
                             io.decode(hypo.trgt_sentence),
                             ' '.join("%s= %f" % (
                                  self.predictor_names[i],
                                  sum([s[i][0] for s in hypo.score_breakdown]))
                                      for i in range(n_predictors)),
                             hypo.total_score))
                    f.write("\n")
                idx += 1


class TimeCSVOutputHandler(OutputHandler):
    """Produces one CSV file for each sentence. The CSV files contain
    the predictor score breakdown for each translation prefix length.
    """
    
    def __init__(self, path, predictor_names):
        """Creates a Moses n-best list output handler.
        
        Args:
            path (string):  Path to the n-best file to write
            predictor_names: Names of the predictors whose scores
                             should be included in the score breakdown
                             in the n-best list
        """
        super(TimeCSVOutputHandler, self).__init__()
        self.path = path
        self.file_pattern = path + "/%d.csv" 
        self.predictor_names = []
        name_count = {}
        for name in predictor_names:
            if not name in name_count:
                name_count[name] = 1
                final_name = name
            else:
                name_count[name] += 1
                final_name = "%s%d" % (name, name_count[name])
            self.predictor_names.append(final_name)
        
    def write_hypos(self, all_hypos, sen_indices):
        """Writes ngram files for each sentence in ``all_hypos``.
        
        Args:
            all_hypos (list): list of nbest lists of hypotheses
            sen_indices (list): List of sentence indices (0-indexed)
        
        Raises:
            OSError. If the directory could not be created
            IOError. If something goes wrong while writing to the disk
        """
        _mkdir(self.path, "TimeCSV")
        n_predictors = len(self.predictor_names)
        placeholder = "\t-" * (n_predictors*2)
        for sen_idx, hypos in zip(sen_indices, all_hypos):
            sen_idx += 1
            with open(self.file_pattern % sen_idx, "w") as f:
                hypo_count = len(hypos)
                # Headers
                f.write("Time")
                for i in range(hypo_count):
                    f.write("".join(["\t%s-%d" % (n, i+1) 
                                       for n in self.predictor_names]))
                    f.write("".join(["\t%s-%d_weight" % (n, i+1) 
                                       for n in self.predictor_names]))
                f.write("\n")
                max_len = max([len(hypo.trgt_sentence) for hypo in hypos])
                for pos in range(max_len+1):
                    f.write(str(pos))
                    for hypo in hypos:
                        if pos >= len(hypo.score_breakdown):
                            f.write(placeholder)
                        else:
                            for pred_idx in range(n_predictors):
                                acc_pred_score = sum([s[pred_idx][0] for s in hypo.score_breakdown[:pos+1]])
                                f.write("\t%f" % acc_pred_score)
                            for pred_idx in range(n_predictors):
                                f.write("\t%f" % hypo.score_breakdown[pos][pred_idx][1])
                    f.write("\n")


class NgramOutputHandler(OutputHandler):
    """This output handler extracts MBR-style ngram posteriors from the 
    hypotheses returned by the decoder. The hypothesis scores are assumed to
    be loglikelihoods, which we renormalize to make sure that we operate on a
    valid distribution. The scores produced by the output handler are 
    probabilities of an ngram being in the translation.
    """
    
    def __init__(self, path, min_order, max_order):
        """Creates an ngram output handler.
        
        Args:
            path (string):  Path to the ngram directory to create
            min_order (int):  Minimum order of extracted ngrams
            max_order (int):  Maximum order of extracted ngrams
        """
        super(NgramOutputHandler, self).__init__()
        self.path = path
        self.min_order = min_order
        self.max_order = max_order
        self.file_pattern = path + "/%d.txt" 
      
    def write_hypos(self, all_hypos, sen_indices):
        """Writes ngram files for each sentence in ``all_hypos``.
        
        Args:
            all_hypos (list): list of nbest lists of hypotheses
            sen_indices (list): List of sentence indices (0-indexed)
        
        Raises:
            OSError. If the directory could not be created
            IOError. If something goes wrong while writing to the disk
        """
        _mkdir(self.path, "ngram")
        for sen_idx, hypos in zip(sen_indices, all_hypos):
            sen_idx += 1
            total = utils.log_sum([hypo.total_score for hypo in hypos])
            normed_scores = [hypo.total_score - total for hypo in hypos]
            ngrams = defaultdict(dict)
            # Collect ngrams
            for hypo_idx, hypo in enumerate(hypos):
                sen_eos = [utils.GO_ID] + hypo.trgt_sentence + [utils.EOS_ID]
                for pos in range(1, len(sen_eos) + 1):
                    hist = sen_eos[:pos]
                    for order in range(self.min_order, self.max_order + 1):
                        ngram = ' '.join(map(str, hist[-order:]))
                        ngrams[ngram][hypo_idx] = True
            with open(self.file_pattern % sen_idx, "w") as f:
                for ngram, hypo_indices in ngrams.items():
                    ngram_score = np.exp(utils.log_sum(
                       [normed_scores[hypo_idx] for hypo_idx in hypo_indices]))
                    f.write("%s : %f\n" % (ngram, min(1.0, ngram_score)))


def write_fst(f, path):
    """Writes FST f to the file system after epsilon removal, determinization,
    and minimization.
    """
    f.rmepsilon()
    f = fst.determinize(f)
    f.minimize()
    f.write(path)


class FSTOutputHandler(OutputHandler):
    """This output handler creates FSTs with with sparse tuple arcs 
    from the n-best lists from the decoder. The predictor scores are 
    kept separately in the sparse tuples. Note that this means that 
    the parameter ``--combination_scheme`` might not be visible in the 
    lattices because predictor scores are not combined. The order in 
    the sparse tuples corresponds to the order of the predictors in 
    the ``--predictors`` argument.
    
    Note that the created FSTs use another ID for UNK to avoid 
    confusion with the epsilon symbol used by OpenFST.
    """
    
    def __init__(self, path, unk_id):
        """Creates a sparse tuple FST output handler.
        
        Args:
            path (string):  Path to the VECLAT directory to create
            unk_id (int): Id which should be used in the FST for UNK
        """
        super(FSTOutputHandler, self).__init__()
        self.path = path
        self.unk_id = unk_id
        self.file_pattern = path + "/%d.fst" 
      
    def write_weight(self, score_breakdown):
        """Helper method to create the weight string """
        els = ['0']
        for (idx,score) in enumerate(score_breakdown):
            els.append(str(idx+1))
            # We need to take the negative here since the tropical
            # FST arc type expects negative log probs instead of log probs
            els.append(str(-score[0]))
        return ','.join(els)

    def write_hypos(self, all_hypos, sen_indices):
        """Writes FST files with sparse tuples for each sentence in 
        ``all_hypos``. The created lattices are not optimized in any
        way: We create a distinct path for each entry in 
        ``all_hypos``. We advise you to determinize/minimize them if 
        you are planning to use them for further processing.
        
        Args:
            all_hypos (list): list of nbest lists of hypotheses
            sen_indices (list): List of sentence indices (0-indexed)
        
        Raises:
            OSError. If the directory could not be created
            IOError. If something goes wrong while writing to the disk
        """
        _mkdir(self.path, "FST")
        for fst_idx, hypos in zip(sen_indices, all_hypos):
            fst_idx += 1
            c = fst.Compiler(arc_type="tropicalsparsetuple")
            # state ID 0 is start, 1 is final state
            next_free_id = 2
            for hypo in hypos:
                syms = hypo.trgt_sentence
                # Connect with start node
                c.write("0\t%d\t%d\t%d\n" % (next_free_id,
                                             utils.GO_ID,
                                             utils.GO_ID))
                next_free_id += 1
                for pos in range(len(hypo.score_breakdown)-1):
                    c.write("%d\t%d\t%d\t%d\t%s\n" % (
                            next_free_id-1, # last state id
                            next_free_id, # next state id 
                            syms[pos], syms[pos], # arc labels
                            self.write_weight(hypo.score_breakdown[pos])))
                    next_free_id += 1
                # Connect with final node
                c.write("%d\t1\t%d\t%d\t%s\n" % (
                                next_free_id-1,
                                utils.EOS_ID,
                                utils.EOS_ID,
                                self.write_weight(hypo.score_breakdown[-1])))
            c.write("1\n") # Add final node
            write_fst(c.compile(), self.file_pattern % fst_idx)


class StandardFSTOutputHandler(OutputHandler):
    """This output handler creates FSTs with standard arcs. In contrast
    to ``FSTOutputHandler``, predictor scores are combined using 
    ``--combination_scheme``.
    
    Note that the created FSTs use another ID for UNK to avoid 
    confusion with the epsilon symbol used by OpenFST.
    """
    
    def __init__(self, path, unk_id):
        """Creates a standard arc FST output handler.
        
        Args:
            path (string):  Path to the fst directory to create
            unk_id (int): Id which should be used in the FST for UNK
        """
        super(StandardFSTOutputHandler, self).__init__()
        self.path = path
        self.unk_id = unk_id
        self.file_pattern = path + "/%d.fst" 
      
    def write_hypos(self, all_hypos, sen_indices):
        """Writes FST files with standard arcs for each
        sentence in ``all_hypos``. The created lattices are not 
        optimized in any way: We create a distinct path for each entry 
        in ``all_hypos``. We advise you to determinize/minimize them if
        you are planning to use them for further processing. 
        
        Args:
            all_hypos (list): list of nbest lists of hypotheses
            sen_indices (list): List of sentence indices (0-indexed)
        
        Raises:
            OSError. If the directory could not be created
            IOError. If something goes wrong while writing to the disk
        """
        _mkdir(self.path, "FST")
        for fst_idx, hypos in zip(sen_indices, all_hypos):
            fst_idx += 1
            c = fst.Compiler()
            # state ID 0 is start, 1 is final state
            next_free_id = 2
            for hypo in hypos:
                # Connect with start node
                c.write("0\t%d\t%d\t%d\t%f\n" % (next_free_id,
                                                 utils.GO_ID,
                                                 utils.GO_ID,
                                                 -hypo.total_score))
                next_free_id += 1
                for sym in hypo.trgt_sentence:
                    c.write("%d\t%d\t%d\t%d\n" % (next_free_id-1,
                                                  next_free_id,
                                                  sym, sym))
                    next_free_id += 1
                # Connect with final node
                c.write("%d\t1\t%d\t%d\n" % (next_free_id-1,
                                             utils.EOS_ID,
                                             utils.EOS_ID))
            c.write("1\n")
            write_fst(c.compile(), self.file_pattern % fst_idx)
